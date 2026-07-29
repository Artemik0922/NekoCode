"""Core agent loop with Claude Code-inspired tool system."""

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from nekocode.prompts import build_system_prompt
from nekocode.memory import MemoryStore
from nekocode.economy import (
    TokenCounter, TokenBudget, ContextWindow,
    ContextCompressor, PriorityScorer, TokenTracker,
)


MAX_TOOL_OUTPUT = 4000
MAX_HISTORY = 12000
IGNORED_PATH_NAMES = {".git", ".mini-coding-agent", "__pycache__",
                       ".pytest_cache", ".ruff_cache", ".venv", "venv",
                       ".agent", "node_modules"}
TECH_DEBT_LOG = ".tech-debt-log.md"
BLUEPRINT_DIR = ".agent/blueprints"
MEMORY_DIR = ".agent/memory"
MEMORY_INDEX = "MEMORY.md"
SESSIONS_DIR = ".mini-coding-agent/sessions"


def now():
    return datetime.now(timezone.utc).isoformat()


def clip(text, limit=MAX_TOOL_OUTPUT):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


# ── Workspace ──────────────────────────────────────────────────────
class WorkspaceContext:
    def __init__(self, cwd, repo_root, branch, default_branch, status, recent_commits, diff_unstaged="", diff_staged=""):
        self.cwd = cwd
        self.repo_root = repo_root
        self.branch = branch
        self.default_branch = default_branch
        self.status = status
        self.recent_commits = recent_commits
        self.diff_unstaged = diff_unstaged
        self.diff_staged = diff_staged

    @classmethod
    def build(cls, cwd):
        cwd = Path(cwd).resolve()

        def git(args, fallback=""):
            try:
                r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5)
                return r.stdout.strip() or fallback if r.returncode == 0 else fallback
            except Exception:
                return fallback

        repo_root = Path(git(["rev-parse", "--show-toplevel"], str(cwd))).resolve()
        branch = git(["branch", "--show-current"]) or "-"
        default = git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], "origin/main")
        def git_full(args, fallback=""):
            try:
                r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5)
                return r.stdout.strip() if r.returncode == 0 else fallback
            except Exception:
                return fallback

        return cls(
            cwd=str(cwd),
            repo_root=str(repo_root),
            branch=branch,
            default_branch=default.removeprefix("origin/"),
            status=clip(git(["status", "--short"], "clean") or "clean", 1500),
            recent_commits=[l for l in git(["log", "--oneline", "-5"]).splitlines() if l],
            diff_unstaged=git(["diff"], ""),
            diff_staged=git(["diff", "--cached"], ""),
        )


# ── Tech Debt Ledger ───────────────────────────────────────────────
class TechDebtLedger:
    @staticmethod
    def path(root):
        return Path(root) / TECH_DEBT_LOG

    @staticmethod
    def init_if_missing(root):
        p = TechDebtLedger.path(root)
        if not p.exists():
            p.write_text("# Tech Debt Ledger\n\n| Date | File | Debt | Reason | Status |\n|------|------|------|--------|--------|\n", encoding="utf-8")

    @staticmethod
    def log(root, file, debt, reason):
        TechDebtLedger.init_if_missing(root)
        date = datetime.now().strftime("%Y-%m-%d")
        with open(TechDebtLedger.path(root), "a", encoding="utf-8") as f:
            f.write(f"| {date} | {file.replace('|', '\\|')} | {debt.replace('|', '\\|')} | {reason.replace('|', '\\|')} | open |\n")
        return f"tech debt logged: {file}"

    @staticmethod
    def entries(root):
        p = TechDebtLedger.path(root)
        if not p.exists():
            return []
        result = []
        for line in p.read_text(encoding="utf-8").strip().splitlines():
            if line.startswith("| ") and not line.startswith("| Date |") and not line.startswith("|------|"):
                parts = [x.strip() for x in line.strip("| ").split("|")]
                if len(parts) >= 5:
                    result.append({"date": parts[0], "file": parts[1], "debt": parts[2], "reason": parts[3], "status": parts[4]})
        return result

    @staticmethod
    def resolve(root, index):
        entries = TechDebtLedger.entries(root)
        if index < 0 or index >= len(entries):
            return f"error: entry {index} not found (have {len(entries)} entries)"
        e = entries[index]
        lines = TechDebtLedger.path(root).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.startswith("| ") and not line.startswith("| Date |") and not line.startswith("|------|"):
                parts = [x.strip() for x in line.strip("| ").split("|")]
                if len(parts) >= 5 and parts[0] == e["date"] and parts[1] == e["file"] and parts[2] == e["debt"]:
                    lines[i] = line.replace(" open |", " resolved |")
                    TechDebtLedger.path(root).write_text("\n".join(lines) + "\n", encoding="utf-8")
                    return f"resolved tech debt #{index}: {e['file']} - {e['debt']}"
        return "error: could not find entry"


# ── Blueprint Store ────────────────────────────────────────────────
class BlueprintStore:
    @staticmethod
    def save(root, pattern, scope, rationale, alternatives, risks):
        d = Path(root) / BLUEPRINT_DIR
        d.mkdir(parents=True, exist_ok=True)
        bid = uuid.uuid4().hex[:8]
        data = {"id": bid, "created_at": now(), "pattern": pattern, "scope": scope,
                "rationale": rationale, "alternatives": alternatives, "risks": risks}
        (d / f"{bid}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return f"saved blueprint {bid}: {pattern}"

    @staticmethod
    def list_all(root):
        d = Path(root) / BLUEPRINT_DIR
        if not d.exists():
            return []
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]

    @staticmethod
    def text_summary(root):
        bps = BlueprintStore.list_all(root)
        if not bps:
            return "No blueprints recorded yet."
        return "\n".join(f"- {bp['pattern']} ({bp['scope']})" for bp in bps)


# ── Session Store ──────────────────────────────────────────────────
class SessionStore:
    def __init__(self, root):
        self.root = Path(root) / SESSIONS_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, session):
        p = self.root / f"{session['id']}.json"
        p.write_text(json.dumps(session, indent=2), encoding="utf-8")
        return p

    def load(self, session_id):
        return json.loads((self.root / f"{session_id}.json").read_text(encoding="utf-8"))

    def latest(self):
        files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime)
        return files[-1].stem if files else None


# ── Model Clients ──────────────────────────────────────────────────
class FakeModelClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def complete(self, prompt, max_new_tokens):
        self.prompts.append(prompt)
        if not self.outputs:
            raise RuntimeError("fake model ran out of outputs")
        return self.outputs.pop(0)

    def stream(self, prompt, max_new_tokens):
        yield self.complete(prompt, max_new_tokens)


class OllamaModelClient:
    def __init__(self, model, host, temperature, top_p, timeout):
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout

    def complete(self, prompt, max_new_tokens):
        import urllib.request
        import urllib.error
        payload = {"model": self.model, "prompt": prompt, "stream": False, "raw": False, "think": False,
                   "options": {"num_predict": max_new_tokens, "temperature": self.temperature, "top_p": self.top_p}}
        req = urllib.request.Request(
            self.host + "/api/generate", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Ollama HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Cannot reach Ollama. Is `ollama serve` running?\n"
                               f"Host: {self.host}\nModel: {self.model}") from exc
        if data.get("error"):
            raise RuntimeError(f"Ollama error: {data['error']}")
        return data.get("response", "")


# ── Task Manager ───────────────────────────────────────────────────
class TaskManager:
    def __init__(self):
        self.tasks = {}

    def create(self, title, description=""):
        tid = uuid.uuid4().hex[:8]
        self.tasks[tid] = {"id": tid, "title": title, "description": description, "status": "pending", "created_at": now()}
        return tid

    def update(self, task_id, status):
        if task_id not in self.tasks:
            return f"error: task {task_id} not found"
        if status not in ("pending", "in_progress", "completed", "cancelled"):
            return f"error: invalid status '{status}'"
        self.tasks[task_id]["status"] = status
        return f"task {task_id} marked as {status}"

    def done(self, task_id):
        return self.update(task_id, "completed")

    def list(self):
        return list(self.tasks.values())


# ── Skills Manager ─────────────────────────────────────────────────
class SkillsManager:
    def __init__(self, root, dirs=None):
        self.root = Path(root)
        self.dirs = [Path(d) if Path(d).is_absolute() else self.root / d for d in (dirs or [])]

    def list_names(self):
        names = []
        for d in self.dirs:
            if d.exists():
                for entry in d.iterdir():
                    if entry.is_dir() and (entry / "SKILL.md").exists():
                        names.append(entry.name)
        return sorted(set(names))

    def load(self, name):
        for d in self.dirs:
            skill_dir = d / name
            if skill_dir.exists() and (skill_dir / "SKILL.md").exists():
                text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                return {"name": name, "content": text, "dir": str(skill_dir)}
        return None

    def descriptions(self):
        result = []
        for name in self.list_names():
            skill = self.load(name)
            if skill:
                desc = ""
                for line in skill["content"].splitlines():
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip('"')
                        break
                result.append(f"- {name}: {desc}" if desc else f"- {name}")
        return "\n".join(result) if result else "No skills installed."


# ── MiniAgent Core ─────────────────────────────────────────────────
class MiniAgent:
    def __init__(self, model_client, workspace, session_store, memory_store=None,
                 session=None, approval_policy="ask", max_steps=8, max_new_tokens=1024,
                 depth=0, max_depth=2, read_only=False, config=None):
        self.model_client = model_client
        self.workspace = workspace
        self.root = Path(workspace.repo_root)
        self.config = config or {}
        self.session_store = session_store
        self.memory_store = memory_store or MemoryStore(self.root).init()
        self.skills = SkillsManager(self.root, self.config.get("skills_dirs", [".claude/skills"]))
        self.task_manager = TaskManager()
        self.approval_policy = approval_policy or self.config.get("approval", "ask")
        self.max_steps = max_steps or int(self.config.get("max_steps", 8))
        self.max_new_tokens = max_new_tokens or int(self.config.get("max_new_tokens", 1024))
        self.depth = depth
        self.max_depth = max_depth
        self.read_only = read_only
        self.session = session or {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "created_at": now(), "workspace_root": workspace.repo_root,
            "history": [], "memory": {"task": "", "files": [], "notes": [], "blueprints": [], "tasks": []},
        }
        self.system_prompt = build_system_prompt(workspace, self.memory_store)

        # Load custom system prompt from .claude/system-prompt.md (Claude Code compat)
        custom_prompt_path = self.root / ".claude" / "system-prompt.md"
        if custom_prompt_path.exists() and not self.config.get("skip_custom_prompt", False):
            custom = custom_prompt_path.read_text(encoding="utf-8").strip()
            if custom:
                self.system_prompt += f"\n\n## Custom Instructions\n{custom}"

        # Also check config for custom_instructions field
        ci = self.config.get("custom_instructions", "") if self.config else ""
        if ci:
            self.system_prompt += f"\n\n## Custom Instructions\n{ci}"

        # History/text caches
        self._cached_history_text = None
        self._cached_history_len = 0
        self._auto_ctx_cache = None

        # Architect mode
        self.architect_mode = self.config.get("architect_mode", False)

        # Token economy
        economy_enabled = self.config.get("economy", {}).get("enabled", True) if self.config else True
        self.economy_enabled = economy_enabled
        self.token_counter = TokenCounter(self._provider_name())
        self.token_budget = TokenBudget.from_provider(self._provider_name(), self._model_name(), overrides=self.config.get("economy", {}).get("budget") if self.config else None)
        self.priority_scorer = PriorityScorer()
        self.context_compressor = ContextCompressor(self._provider_name(), self.config.get("economy", {}).get("strategies") if self.config else None)
        self.context_window = ContextWindow(budget=self.token_budget, counter=self.token_counter, scorer=self.priority_scorer, compressor=self.context_compressor, provider=self._provider_name())
        self.token_tracker = TokenTracker()

        # Architect mode overrides
        if self.architect_mode:
            self.system_prompt += """

## ARCHITECT MODE — You are in architect mode and MUST follow ALL rules below:

- DO NOT write, edit, or delete any code. You are strictly in a planning and design role.
- You MAY use read-only tools (Read, Glob, Grep, GitStatus, GitDiff, web_fetch, web_search, Recall).
- You MUST NOT call: Write, Edit, Bash, GitCommit, GitUndo, agent/delegate (use submit_blueprint instead).
- Create blueprints with submit_blueprint before every non-trivial design decision.
- When the user asks for implementation, respond with a detailed plan including:
  - Files to create/modify
  - Key design decisions and their rationale
  - Potential risks and tradeoffs
  - Recommended implementation order
- Your output should be a complete blueprint or plan document.
- If the user wants you to implement, ask them to exit architect mode with the /architect command."""

        # MCP (Model Context Protocol)
        self.mcp_manager = None
        if self.config.get("mcp", {}).get("enabled", True):
            from nekocode.mcp import MCPManager
            self.mcp_manager = MCPManager(self)
            self.mcp_manager.load_config()
            if self.mcp_manager.servers and self.config.get("mcp", {}).get("auto_connect", True):
                try:
                    import asyncio
                    results = asyncio.run(self.mcp_manager.connect_all())
                    self.mcp_manager.register_tools()
                    mcp_summary = self.mcp_manager.summary()
                    if mcp_summary.strip() and "(no MCP" not in mcp_summary:
                        self.system_prompt += f"\n\n## Connected MCP Servers\n{mcp_summary}"
                except Exception as exc:
                    pass

        self.session_path = self.session_store.save(self.session)

    def _provider_name(self):
        if hasattr(self.model_client, 'provider_name'):
            return self.model_client.provider_name
        if hasattr(self.model_client, 'model'):
            return getattr(self.model_client, 'model', 'ollama')
        return 'ollama'

    def _model_name(self):
        if hasattr(self.model_client, 'model'):
            return self.model_client.model
        return None

    @classmethod
    def from_session(cls, model_client, workspace, session_store, memory_store=None, session_id=None, **kwargs):
        session = session_store.load(session_id) if session_id else None
        return cls(model_client=model_client, workspace=workspace, session_store=session_store,
                   memory_store=memory_store, session=session, **kwargs)

    def prompt(self, user_message):
        auto_ctx = self._auto_ctx_cache or ""
        if self.economy_enabled:
            return self.context_window.assemble(
                history=self.session["history"],
                system_prompt=self.system_prompt,
                user_msg=user_message,
                memory_block=self._memory_text(),
                auto_context=auto_ctx if auto_ctx else None,
            )
        user_section = f"## Current user request\n{user_message}" + auto_ctx
        return "\n\n".join([
            self.system_prompt,
            self._memory_text(),
            "## Transcript\n" + self._history_text(),
            user_section,
        ])

    def _memory_text(self):
        m = self.session["memory"]
        notes = "\n".join(f"- {n}" for n in m["notes"]) or "- none"
        blueprints = "\n".join(f"- {b}" for b in m["blueprints"]) or "- none"
        tasks = "\n".join(f"- [{t['status']}] {t['title']}" for t in self.task_manager.list()) or "- none"
        return f"""## Session Memory
- Task: {m['task'] or '-'}
- Files: {', '.join(m['files']) or '-'}
- Blueprints:\n{blueprints}
- Notes:\n{notes}
- Tasks:\n{tasks}"""

    def _history_text(self):
        hist = self.session["history"]
        if not hist:
            return "- empty"
        if len(hist) == self._cached_history_len and self._cached_history_text is not None:
            return self._cached_history_text

        lines = []
        seen_reads = set()
        recent_start = max(0, len(hist) - 6)
        for idx, item in enumerate(hist):
            recent = idx >= recent_start
            if item["role"] == "tool" and item["name"] in ("write", "edit"):
                seen_reads.discard(str(item["args"].get("path", "")))
            if item["role"] == "tool" and item["name"] == "read" and not recent:
                p = str(item["args"].get("path", ""))
                if p in seen_reads:
                    continue
                seen_reads.add(p)
            if item["role"] == "tool":
                limit = 900 if recent else 180
                lines.append(f"[tool:{item['name']}] {json.dumps(item['args'], sort_keys=True)}")
                lines.append(clip(item["content"], limit))
            else:
                limit = 900 if recent else 220
                lines.append(f"[{item['role']}] {clip(item['content'], limit)}")
        text = clip("\n".join(lines), MAX_HISTORY)
        self._cached_history_text = text
        self._cached_history_len = len(hist)
        return text

    def record(self, item):
        self.session["history"].append(item)
        self._cached_history_text = None  # invalidate cache
        hist_len = len(self.session["history"])
        if hist_len <= 2 or hist_len % 5 == 0:
            self.session_path = self.session_store.save(self.session)

    def ask(self, user_message):
        m = self.session["memory"]
        if not m["task"]:
            m["task"] = clip(user_message.strip(), 300)

        # Cache auto_context once per ask() cycle
        self._auto_ctx_cache = None
        if self.config.get("auto_context", {}).get("enabled", True):
            try:
                from nekocode.auto_context import build_auto_context
                max_files = int(self.config.get("auto_context", {}).get("max_files", 5))
                max_chars = int(self.config.get("auto_context", {}).get("max_chars", 3000))
                ctx = build_auto_context(user_message, self.root, max_files=max_files, max_chars=max_chars)
                if ctx:
                    self._auto_ctx_cache = "\n\n" + ctx
            except Exception:
                pass

        self.record({"role": "user", "content": user_message, "created_at": now()})

        tool_steps = 0
        attempts = 0
        max_att = max(self.max_steps * 3, self.max_steps + 4)

        while tool_steps < self.max_steps and attempts < max_att:
            attempts += 1
            if self.economy_enabled:
                self.token_tracker.begin_step(attempts)
                history_snapshot = self.session["history"][:]
            prompt_text = self.prompt(user_message)
            if self.economy_enabled:
                self.token_tracker.record_prompt(prompt_text, self.token_counter)
            raw = self.model_client.complete(prompt_text, self.max_new_tokens)
            kind, payload = self._parse(raw)

            if kind == "tool":
                tool_steps += 1
                name = payload.get("name", "")
                args = payload.get("args", {})
                if self.economy_enabled:
                    self.token_tracker.record_response(raw, self.token_counter)
                result = self._run_tool(name, args)
                if self.economy_enabled:
                    self.token_tracker.record_tool(name, self.token_counter.estimate(prompt_text), self.token_counter.estimate(raw))
                    self.token_tracker.end_step()
                self.record({"role": "tool", "name": name, "args": args, "content": result, "created_at": now()})
                self._note_tool(name, args, result)
                continue

            if kind == "retry":
                self.record({"role": "assistant", "content": payload, "created_at": now()})
                continue

            final = (payload or raw).strip()
            if self.economy_enabled:
                self.token_tracker.record_response(final, self.token_counter)
                self.token_tracker.end_step()
            self.record({"role": "assistant", "content": final, "created_at": now()})
            self.session_store.save(self.session)
            self._auto_ctx_cache = None
            return final

        msg = "Stopped: max steps reached without final answer."
        if attempts >= max_att and tool_steps < self.max_steps:
            msg = "Stopped: too many invalid model responses."
        self.record({"role": "assistant", "content": msg, "created_at": now()})
        self.session_store.save(self.session)
        self._auto_ctx_cache = None
        return msg

    def ask_stream(self, user_message):
        """Like ask() but yields final response tokens one by one (streaming)."""
        m = self.session["memory"]
        if not m["task"]:
            m["task"] = clip(user_message.strip(), 300)

        self._auto_ctx_cache = None
        if self.config.get("auto_context", {}).get("enabled", True):
            try:
                from nekocode.auto_context import build_auto_context
                max_files = int(self.config.get("auto_context", {}).get("max_files", 5))
                max_chars = int(self.config.get("auto_context", {}).get("max_chars", 3000))
                ctx = build_auto_context(user_message, self.root, max_files=max_files, max_chars=max_chars)
                if ctx:
                    self._auto_ctx_cache = "\n\n" + ctx
            except Exception:
                pass

        self.record({"role": "user", "content": user_message, "created_at": now()})

        tool_steps = 0
        attempts = 0
        max_att = max(self.max_steps * 3, self.max_steps + 4)

        while tool_steps < self.max_steps and attempts < max_att:
            attempts += 1
            prompt_text = self.prompt(user_message)

            # Stream from provider while detecting tool calls
            stream_iter = self.model_client.stream(prompt_text, self.max_new_tokens)
            prelude = []
            is_tool_call = None
            full_text = ""

            for chunk in stream_iter:
                full_text += chunk
                if is_tool_call is None:
                    prelude.append(chunk)
                    stripped = "".join(prelude).lstrip()
                    if len(stripped) >= 6:
                        if stripped.startswith("<tool"):
                            is_tool_call = True
                        else:
                            is_tool_call = False
                            for p in prelude:
                                yield p
                            prelude = None
                elif prelude is None:
                    yield chunk

            # Handle result based on detection
            if is_tool_call:
                kind, payload = self._parse(full_text)
                if kind == "tool":
                    tool_steps += 1
                    name = payload.get("name", "")
                    args = payload.get("args", {})
                    result = self._run_tool(name, args)
                    self.record({"role": "tool", "name": name, "args": args, "content": result, "created_at": now()})
                    self._note_tool(name, args, result)
                    continue
                # fell through: started with <tool but wasn't a valid tool call
                yield full_text

            self.record({"role": "assistant", "content": full_text, "created_at": now()})
            self.session_store.save(self.session)
            self._auto_ctx_cache = None
            return

        msg = "Stopped: max steps reached without final answer."
        if attempts >= max_att and tool_steps < self.max_steps:
            msg = "Stopped: too many invalid model responses."
        self.record({"role": "assistant", "content": msg, "created_at": now()})
        self.session_store.save(self.session)
        self._auto_ctx_cache = None
        yield msg

    def _note_tool(self, name, args, result):
        m = self.session["memory"]
        path = args.get("path")
        if name in ("read", "write", "edit") and path:
            self._remember(m["files"], str(path), 8)
        if name == "submit_blueprint":
            self._remember(m["blueprints"], f"{args.get('pattern', '?')} -> {args.get('scope', '?')}", 8)
        self._remember(m["notes"], f"{name}: {clip(str(result).replace(chr(10), ' '), 220)}", 5)

    @staticmethod
    def _remember(bucket, item, limit):
        if not item:
            return
        if item in bucket:
            bucket.remove(item)
        bucket.append(item)
        del bucket[:-limit]

    # ── Tool dispatch ──────────────────────────────────────────────
    TOOL_REGISTRY = {}

    @classmethod
    def register(cls, name, risky=False, schema=None):
        def dec(fn):
            cls.TOOL_REGISTRY[name] = {"fn": fn, "risky": risky, "schema": schema or {}}
            return fn
        return dec

    @classmethod
    def register_tool(cls, name, fn, risky=False, schema=None):
        """Register a tool at runtime (e.g. from MCP servers)."""
        cls.TOOL_REGISTRY[name] = {"fn": fn, "risky": risky, "schema": schema or {}}

    def _run_tool(self, name, args):
        entry = self.TOOL_REGISTRY.get(name)
        if entry is None:
            return f"error: unknown tool '{name}'"
        try:
            self._validate(name, args)
        except Exception as exc:
            return f"error: invalid args for {name}: {exc}"

        if self.architect_mode and name in ("write", "edit", "bash", "git_commit", "git_undo", "agent", "delegate"):
            return f"error: tool '{name}' is disabled in architect mode (use only read-only tools)"

        if self._repeated_call(name, args):
            return f"error: repeated identical call to {name}; choose a different tool or return a final answer"

        if entry["risky"] and not self._approve(name, args):
            return f"error: approval denied for {name}"

        try:
            return clip(entry["fn"](self, args))
        except Exception as exc:
            return f"error: tool {name} failed: {exc}"

    def _repeated_call(self, name, args):
        events = [i for i in self.session["history"] if i["role"] == "tool"]
        if len(events) < 2:
            return False
        last_two = events[-2:]
        return all(i["name"] == name and i["args"] == args for i in last_two)

    def _validate(self, name, args):
        args = args or {}
        if name == "read":
            p = self._path(args.get("path", ""))
            if not p.is_file():
                raise ValueError(f"not a file: {args.get('path', '')}")
            offset = int(args.get("offset", 1))
            if offset < 1:
                raise ValueError("offset must be >= 1")
        elif name == "write":
            p = self._path(args.get("path", ""))
            if p.exists() and p.is_dir():
                raise ValueError("path is a directory")
            if "content" not in args:
                raise ValueError("missing content")
        elif name == "edit":
            p = self._path(args.get("path", ""))
            if not p.is_file():
                raise ValueError(f"not a file: {args.get('path', '')}")
            old = str(args.get("old_text", ""))
            if not old:
                raise ValueError("old_text must not be empty")
            if "new_text" not in args:
                raise ValueError("missing new_text")
            text = p.read_text(encoding="utf-8")
            if text.count(old) != 1:
                raise ValueError(f"old_text must occur exactly once, found {text.count(old)}")
        elif name == "glob":
            if not str(args.get("pattern", "")).strip():
                raise ValueError("pattern must not be empty")
        elif name == "grep":
            if not str(args.get("pattern", "")).strip():
                raise ValueError("pattern must not be empty")
        elif name == "bash":
            cmd = str(args.get("command", "")).strip()
            if not cmd:
                raise ValueError("command must not be empty")
            timeout = int(args.get("timeout", 30))
            if timeout < 1 or timeout > 120:
                raise ValueError("timeout must be in [1, 120]")
        elif name == "submit_blueprint":
            if not str(args.get("pattern", "")).strip():
                raise ValueError("pattern must not be empty")
            if not str(args.get("scope", "")).strip():
                raise ValueError("scope must not be empty")
            if not str(args.get("rationale", "")).strip():
                raise ValueError("rationale must not be empty")
        elif name == "log_tech_debt":
            if not str(args.get("file", "")).strip():
                raise ValueError("file must not be empty")
            if not str(args.get("debt", "")).strip():
                raise ValueError("debt must not be empty")
            if not str(args.get("reason", "")).strip():
                raise ValueError("reason must not be empty")
        elif name in ("agent", "delegate"):
            if not str(args.get("task", "")).strip():
                raise ValueError("task must not be empty")
            if self.depth >= self.max_depth:
                raise ValueError("agent delegation depth exceeded")
        elif name == "task_create":
            if not str(args.get("title", "")).strip():
                raise ValueError("title must not be empty")
        elif name == "task_update":
            if not str(args.get("task_id", "")).strip():
                raise ValueError("task_id must not be empty")
            if not str(args.get("status", "")).strip():
                raise ValueError("status must not be empty")
        elif name == "task_done":
            if not str(args.get("task_id", "")).strip():
                raise ValueError("task_id must not be empty")
        elif name == "remember":
            mt = args.get("type", "")
            if mt not in ("user", "project", "feedback", "reference"):
                raise ValueError("type must be: user, project, feedback, or reference")
            if not str(args.get("name", "")).strip():
                raise ValueError("name must not be empty")
            if not str(args.get("body", "")).strip():
                raise ValueError("body must not be empty")
        elif name == "recall":
            pass
        elif name == "web_fetch":
            if not str(args.get("url", "")).strip():
                raise ValueError("url must not be empty")
        elif name == "web_search":
            if not str(args.get("query", "")).strip():
                raise ValueError("query must not be empty")
        elif name == "skill":
            if not str(args.get("name", "")).strip():
                raise ValueError("name must not be empty")
        elif name == "git_commit":
            if not str(args.get("message", "")).strip():
                raise ValueError("message must not be empty")
        elif name == "git_create_pr":
            if not str(args.get("title", "")).strip():
                raise ValueError("title must not be empty")
        elif name in ("git_undo", "git_status", "git_diff"):
            pass

    def _approve(self, name, args):
        if self.read_only:
            return False
        if self.approval_policy == "auto":
            return True
        if self.approval_policy == "never":
            return False
        try:
            from rich.prompt import Prompt
            answer = Prompt.ask(
                f"[bold yellow]Confirm[/] [bold]{name}[/] [dim]{json.dumps(args, ensure_ascii=True)}[/]",
                choices=["y", "Y", "n", "N"], default="n")
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() == "y"

    def _path(self, raw_path):
        path = Path(raw_path)
        path = path if path.is_absolute() else self.root / path
        resolved = path.resolve()
        if not self._within_root(resolved):
            raise ValueError(f"path escapes workspace: {raw_path}")
        return resolved

    def _within_root(self, resolved):
        probe = resolved
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        for c in (probe, *probe.parents):
            try:
                if c.samefile(self.root):
                    return True
            except OSError:
                continue
        return False

    # ── Parse ──────────────────────────────────────────────────────
    @staticmethod
    def _parse(raw):
        raw = str(raw)
        if "<tool>" in raw and ("<final>" not in raw or raw.find("<tool>") < raw.find("<final>")):
            body = MiniAgent._extract(raw, "tool")
            try:
                payload = json.loads(body)
            except Exception:
                return "retry", MiniAgent._retry("malformed tool JSON")
            if not isinstance(payload, dict) or not payload.get("name"):
                return "retry", MiniAgent._retry("tool payload must have a name")
            args = payload.get("args")
            if args is None:
                payload["args"] = {}
            elif not isinstance(args, dict):
                return "retry", MiniAgent._retry()
            return "tool", payload
        if "<tool" in raw and ("<final>" not in raw or raw.find("<tool") < raw.find("<final>")):
            payload = MiniAgent._parse_xml(raw)
            if payload:
                return "tool", payload
            return "retry", MiniAgent._retry()
        if "<final>" in raw:
            final = MiniAgent._extract(raw, "final").strip()
            if final:
                return "final", final
            return "retry", MiniAgent._retry("empty <final>")
        raw = raw.strip()
        if raw:
            return "final", raw
        return "retry", MiniAgent._retry("empty response")

    @staticmethod
    def _retry(problem=None):
        p = f": {problem}" if problem else ": malformed output"
        return f"Runtime notice{p}. Reply with a valid <tool> call or a non-empty <final> answer."

    @staticmethod
    def _parse_xml(raw):
        m = re.search(r"<tool(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", raw, re.S)
        if not m:
            return None
        attrs = {}
        for match in re.finditer(r"""([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""", m.group("attrs")):
            attrs[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
        name = attrs.pop("name", "")
        if not name:
            return None
        body = m.group("body")
        args = dict(attrs)
        for key in ("content", "old_text", "new_text", "command", "task", "body"):
            val = MiniAgent._extract_raw(body, key)
            if val is not None:
                args[key] = val
        b = body.strip("\n")
        if name == "write" and "content" not in args and b:
            args["content"] = b
        if name == "agent" and "task" not in args and b:
            args["task"] = b
        return {"name": name, "args": args}

    @staticmethod
    def _extract(text, tag):
        s = text.find(f"<{tag}>")
        if s == -1:
            return text
        s += len(tag) + 2
        e = text.find(f"</{tag}>", s)
        return text[s:e].strip() if e != -1 else text[s:].strip()

    @staticmethod
    def _extract_raw(text, tag):
        s = text.find(f"<{tag}>")
        if s == -1:
            return None
        s += len(tag) + 2
        e = text.find(f"</{tag}>", s)
        return text[s:e] if e != -1 else text[s:]

    def run_tool(self, name, args):
        return self._run_tool(name, args)

    def reset(self):
        self.session["history"] = []
        self.session["memory"] = {"task": "", "files": [], "notes": [], "blueprints": [], "tasks": []}
        self.task_manager = TaskManager()
        self.token_tracker.reset()
        self._cached_history_text = None
        self._cached_history_len = 0
        self._auto_ctx_cache = None
        self.session_store.save(self.session)

    def tokens_dashboard(self):
        return self.token_tracker.dashboard()


# ── Tool Implementations ───────────────────────────────────────────
def tool_read(agent, args):
    path = agent._path(args["path"])
    if not path.is_file():
        raise ValueError("not a file")
    offset = int(args.get("offset", 1))
    limit = int(args.get("limit", 200))
    if offset < 1 or limit < 1:
        raise ValueError("invalid range")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    body = "\n".join(f"{n:>4}: {l}" for n, l in enumerate(lines[offset - 1:offset - 1 + limit], start=offset))
    return f"# {path.relative_to(agent.root)}\n{body}"


def tool_write(agent, args):
    path = agent._path(args["path"])
    content = str(args["content"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.relative_to(agent.root)} ({len(content)} chars)"


def tool_edit(agent, args):
    path = agent._path(args["path"])
    if not path.is_file():
        raise ValueError("not a file")
    old = str(args["old_text"])
    new = str(args["new_text"])
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"old_text must occur exactly once, found {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"edited {path.relative_to(agent.root)}"


def tool_glob(agent, args):
    pattern = str(args["pattern"])
    search_path = agent._path(args.get("path", "."))
    results = sorted(Path(search_path).rglob(pattern))
    ignored = IGNORED_PATH_NAMES
    lines = []
    for p in results:
        rel = p.relative_to(agent.root)
        if any(part in ignored for part in rel.parts):
            continue
        lines.append(str(rel))
    return "\n".join(lines[:500]) or "(no matches)"


def tool_grep(agent, args):
    pattern = str(args["pattern"])
    search_path = agent._path(args.get("path", "."))
    output_mode = args.get("output_mode", "files_with_matches")
    include = args.get("include")
    case_insensitive = args.get("-i", False)

    if shutil.which("rg"):
        cmd = ["rg", "-n", "--max-count", "200"]
        if case_insensitive:
            cmd.append("-i")
        if output_mode == "files_with_matches":
            cmd.append("-l")
        if include:
            cmd.extend(["--glob", include])
        cmd.extend([pattern, str(search_path)])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return r.stdout.strip() or r.stderr.strip() or "(no matches)"
        except subprocess.TimeoutExpired:
            pass

    matches = []
    files = [search_path] if search_path.is_file() else [f for f in search_path.rglob("*") if f.is_file()
              and not any(p in IGNORED_PATH_NAMES for p in f.relative_to(agent.root).parts)]
    if include:
        import fnmatch
        files = [f for f in files if fnmatch.fnmatch(f.name, include)]

    for fp in files:
        for n, line in enumerate(fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            check = line if not case_insensitive else line.lower()
            pat = pattern if not case_insensitive else pattern.lower()
            if pat in check:
                if output_mode == "files_with_matches":
                    matches.append(str(fp.relative_to(agent.root)))
                    break
                else:
                    matches.append(f"{fp.relative_to(agent.root)}:{n}:{line}")
                if len(matches) >= 200:
                    return "\n".join(matches)
    return "\n".join(matches) or "(no matches)"


def tool_bash(agent, args):
    cmd = str(args["command"])
    timeout = int(args.get("timeout", 30))
    r = subprocess.run(cmd, cwd=agent.root, shell=True, capture_output=True, text=True, timeout=timeout)
    out = r.stdout.strip() or "(empty)"
    err = r.stderr.strip() or "(empty)"
    return f"exit_code: {r.returncode}\nstdout:\n{out}\nstderr:\n{err}"


def tool_submit_blueprint(agent, args):
    return BlueprintStore.save(agent.root, args.get("pattern", ""), args.get("scope", ""),
                                args.get("rationale", ""), args.get("alternatives", ""), args.get("risks", ""))


def tool_log_tech_debt(agent, args):
    return TechDebtLedger.log(agent.root, args.get("file", ""), args.get("debt", ""), args.get("reason", ""))


def tool_agent(agent, args):
    task = str(args["task"])
    stype = args.get("subagent_type", "general-purpose")
    child = MiniAgent(
        model_client=agent.model_client, workspace=agent.workspace, session_store=agent.session_store,
        memory_store=agent.memory_store, approval_policy="never",
        max_steps=int(args.get("max_steps", 5)), max_new_tokens=agent.max_new_tokens,
        depth=agent.depth + 1, max_depth=agent.max_depth, read_only=(stype != "worker"))
    child.session["memory"]["task"] = task
    child.session["memory"]["notes"] = [clip(agent._history_text(), 500)]
    return "=== SUBAGENT RESULT ===\n" + child.ask(task)


def tool_task_create(agent, args):
    tid = agent.task_manager.create(args.get("title", ""), args.get("description", ""))
    return f"created task: {tid} - {args['title']}"


def tool_task_update(agent, args):
    return agent.task_manager.update(args["task_id"], args["status"])


def tool_task_done(agent, args):
    return agent.task_manager.done(args["task_id"])


def tool_remember(agent, args):
    p = agent.memory_store.save(args["type"], args["name"], args.get("description", ""), args["body"])
    return f"saved memory: {p.name}"


def tool_recall(agent, args):
    if args.get("list", False) or (not args.get("slug")):
        items = agent.memory_store.list_all()
        return "\n".join(items) if items else "No memories."
    mem = agent.memory_store.load(args["slug"])
    if mem is None:
        return f"memory '{args['slug']}' not found"
    return f"---\nname: {mem['frontmatter'].get('name', '?')}\ntype: {mem['frontmatter'].get('type', '?')}\ndescription: {mem['frontmatter'].get('description', '?')}\n---\n{mem['body']}"


def tool_list_files(agent, args):
    path = agent._path(args.get("path", "."))
    if not path.is_dir():
        raise ValueError("not a directory")
    entries = sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    lines = []
    for e in entries[:200]:
        if e.name in IGNORED_PATH_NAMES:
            continue
        lines.append(f"{'[D]' if e.is_dir() else '[F]'} {e.relative_to(agent.root)}")
    return "\n".join(lines) or "(empty)"


def tool_web_fetch(agent, args):
    url = str(args["url"]).strip()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NekoCode/0.5"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        return clip(content, 8000)
    except Exception as exc:
        return f"error fetching {url}: {exc}"


def tool_web_search(agent, args):
    query = str(args["query"]).strip()
    try:
        import http.client
        encoded = urllib.parse.quote(query)
        req = urllib.request.Request(
            f"https://html.duckduckgo.com/html/?q={encoded}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        results = []
        for match in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.S):
            url = match.group(1)
            title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            results.append(f"- [{title}]({url})")
            if len(results) >= 8:
                break
        return "\n".join(results) if results else "(no results)"
    except Exception as exc:
        return f"error searching: {exc}"


def tool_skill(agent, args):
    name = str(args["name"])
    skill = agent.skills.load(name)
    if skill is None:
        available = agent.skills.list_names()
        return f"skill '{name}' not found. Installed: {', '.join(available) if available else 'none'}"
    return f"# Skill: {name}\n\n{skill['content']}"


def _git(agent, *args):
    r = subprocess.run(["git", *args], cwd=agent.root, capture_output=True, text=True, timeout=15)
    return r


def tool_git_commit(agent, args):
    msg = str(args["message"]).strip()
    add_all = args.get("add_all", True)
    if add_all:
        _git(agent, "add", "-A")
    r = _git(agent, "commit", "-m", msg)
    if r.returncode != 0:
        return f"commit failed:\n{r.stderr.strip()}"
    return f"committed: {msg}\n{r.stdout.strip()}"


def tool_git_create_pr(agent, args):
    title = str(args["title"]).strip()
    body = str(args.get("body", "")).strip()
    r = _git(agent, "push", "origin", "HEAD")
    if r.returncode != 0:
        return f"push failed:\n{r.stderr.strip()}"
    if shutil.which("gh"):
        cmd = ["gh", "pr", "create", "--title", title]
        if body:
            cmd += ["--body", body]
        r2 = subprocess.run(cmd, cwd=agent.root, capture_output=True, text=True, timeout=15)
        if r2.returncode == 0:
            return f"PR created: {r2.stdout.strip()}"
        return f"push ok, but gh failed:\n{r2.stderr.strip()}"
    return f"push ok. Install gh CLI to create PRs, then create a PR with title: {title}"


def tool_git_undo(agent, args):
    r = _git(agent, "log", "--oneline", "-2")
    commits = [l for l in r.stdout.strip().splitlines() if l]
    if not commits:
        return "no commits to undo"
    r2 = _git(agent, "reset", "--soft", "HEAD~1")
    if r2.returncode != 0:
        return f"undo failed:\n{r2.stderr.strip()}"
    return f"undone: {commits[0]}"


def tool_git_status(agent, args):
    r = _git(agent, "status", "--short")
    return r.stdout.strip() or "(clean)"


def tool_git_diff(agent, args):
    staged = args.get("staged", False)
    cmd = ["git", "diff"] if not staged else ["git", "diff", "--cached"]
    r = subprocess.run(cmd, cwd=agent.root, capture_output=True, text=True, timeout=15)
    out = r.stdout.strip()
    if not out:
        return "(no diff)"
    return clip(out, 4000)


# Register tools ────────────────────────────────────────────────────
_RI = MiniAgent.register
_RI("read", False, {"path": "str", "offset": "int=1", "limit": "int=200"})(tool_read)
_RI("write", True, {"path": "str", "content": "str"})(tool_write)
_RI("edit", True, {"path": "str", "old_text": "str", "new_text": "str"})(tool_edit)
_RI("list_files", False, {"path": "str='.'"})(tool_list_files)
_RI("glob", False, {"pattern": "str", "path": "str='.'"})(tool_glob)
_RI("grep", False, {"pattern": "str", "path": "str='.'", "include": "str=''", "output_mode": "str='files_with_matches'", "-i": "bool=False"})(tool_grep)
_RI("bash", True, {"command": "str", "timeout": "int=30"})(tool_bash)
_RI("submit_blueprint", False, {"pattern": "str", "scope": "str", "rationale": "str", "alternatives": "str=''", "risks": "str=''"})(tool_submit_blueprint)
_RI("log_tech_debt", False, {"file": "str", "debt": "str", "reason": "str"})(tool_log_tech_debt)
_RI("agent", False, {"task": "str", "subagent_type": "str='general-purpose'", "max_steps": "int=5"})(tool_agent)
_RI("task_create", False, {"title": "str", "description": "str=''"})(tool_task_create)
_RI("task_update", False, {"task_id": "str", "status": "str"})(tool_task_update)
_RI("task_done", False, {"task_id": "str"})(tool_task_done)
_RI("remember", False, {"type": "str", "name": "str", "description": "str=''", "body": "str"})(tool_remember)
_RI("recall", False, {"slug": "str=''", "list": "bool=False"})(tool_recall)
_RI("web_fetch", False, {"url": "str"})(tool_web_fetch)
_RI("web_search", False, {"query": "str"})(tool_web_search)
_RI("skill", False, {"name": "str", "args": "str=''"})(tool_skill)
_RI("git_commit", True, {"message": "str", "add_all": "bool=True"})(tool_git_commit)
_RI("git_create_pr", True, {"title": "str", "body": "str=''"})(tool_git_create_pr)
_RI("git_undo", True, {})(tool_git_undo)
_RI("git_status", False, {})(tool_git_status)
_RI("git_diff", False, {"staged": "bool=False"})(tool_git_diff)
# Backward compat aliases
_RI("read_file", False, {"path": "str", "offset": "int=1", "limit": "int=200"})(tool_read)
_RI("write_file", True, {"path": "str", "content": "str"})(tool_write)
_RI("patch_file", True, {"path": "str", "old_text": "str", "new_text": "str"})(tool_edit)
_RI("run_shell", True, {"command": "str", "timeout": "int=30"})(tool_bash)
_RI("search", False, {"pattern": "str", "path": "str='.'"})(tool_grep)
_RI("delegate", False, {"task": "str", "subagent_type": "str='general-purpose'", "max_steps": "int=5"})(tool_agent)
