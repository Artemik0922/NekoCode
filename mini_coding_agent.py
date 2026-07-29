"""
Architecture-First Coding Agent
--------------------------------
A minimal local coding agent that documents architecture decisions
and tracks tech debt — with a beautiful terminal UI.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from rich import box
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text


DOC_NAMES = ("AGENTS.md", "README.md", "pyproject.toml", "package.json")
MAX_TOOL_OUTPUT = 4000
MAX_HISTORY = 12000
IGNORED_PATH_NAMES = {".git", ".mini-coding-agent", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "venv"}
TECH_DEBT_LOG = ".tech-debt-log.md"
BLUEPRINT_DIR = ".agent/blueprints"

console = Console()


def now():
    return datetime.now(timezone.utc).isoformat()


def clip(text, limit=MAX_TOOL_OUTPUT):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


##########################
#### Workspace Context ###
##########################
class WorkspaceContext:
    def __init__(self, cwd, repo_root, branch, default_branch, status, recent_commits, project_docs):
        self.cwd = cwd
        self.repo_root = repo_root
        self.branch = branch
        self.default_branch = default_branch
        self.status = status
        self.recent_commits = recent_commits
        self.project_docs = project_docs

    @classmethod
    def build(cls, cwd):
        cwd = Path(cwd).resolve()

        def git(args, fallback=""):
            try:
                result = subprocess.run(
                    ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=5,
                )
                return result.stdout.strip() or fallback
            except Exception:
                return fallback

        repo_root = Path(git(["rev-parse", "--show-toplevel"], str(cwd))).resolve()
        docs = {}
        for base in (repo_root, cwd):
            for name in DOC_NAMES:
                path = base / name
                if not path.exists():
                    continue
                key = str(path.relative_to(repo_root))
                if key in docs:
                    continue
                docs[key] = clip(path.read_text(encoding="utf-8", errors="replace"), 1200)

        return cls(
            cwd=str(cwd),
            repo_root=str(repo_root),
            branch=git(["branch", "--show-current"], "-") or "-",
            default_branch=(git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], "origin/main") or "origin/main").removeprefix("origin/"),
            status=clip(git(["status", "--short"], "clean") or "clean", 1500),
            recent_commits=[line for line in git(["log", "--oneline", "-5"]).splitlines() if line],
            project_docs=docs,
        )

    def text(self):
        commits = "\n".join(f"- {line}" for line in self.recent_commits) or "- none"
        docs = "\n".join(f"- {path}\n{snippet}" for path, snippet in self.project_docs.items()) or "- none"
        return "\n".join([
            "Workspace:", f"- cwd: {self.cwd}", f"- repo_root: {self.repo_root}",
            f"- branch: {self.branch}", f"- default_branch: {self.default_branch}",
            "- status:", self.status, "- recent_commits:", commits, "- project_docs:", docs,
        ])


##########################
#### Tech Debt Ledger ####
##########################
class TechDebtLedger:
    @staticmethod
    def path(root):
        return Path(root) / TECH_DEBT_LOG

    @staticmethod
    def init_if_missing(root):
        path = TechDebtLedger.path(root)
        if not path.exists():
            path.write_text(
                "# Tech Debt Ledger\n\n| Date | File | Debt | Reason | Status |\n|------|------|------|--------|--------|\n",
                encoding="utf-8",
            )

    @staticmethod
    def log(root, file, debt, reason):
        TechDebtLedger.init_if_missing(root)
        path = TechDebtLedger.path(root)
        date = datetime.now().strftime("%Y-%m-%d")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"| {date} | {file.replace('|', '\\|')} | {debt.replace('|', '\\|')} | {reason.replace('|', '\\|')} | open |\n")
        return f"tech debt logged: {file}"

    @staticmethod
    def read(root):
        path = TechDebtLedger.path(root)
        if not path.exists():
            return "No tech debt logged yet."
        return path.read_text(encoding="utf-8")

    @staticmethod
    def entries(root):
        path = TechDebtLedger.path(root)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines:
            if line.startswith("| ") and not line.startswith("| Date |") and not line.startswith("|------|"):
                parts = [p.strip() for p in line.strip("| ").split("|")]
                if len(parts) >= 5:
                    entries.append({"date": parts[0], "file": parts[1], "debt": parts[2], "reason": parts[3], "status": parts[4]})
        return entries

    @staticmethod
    def resolve(root, index):
        entries = TechDebtLedger.entries(root)
        if index < 0 or index >= len(entries):
            return f"error: entry {index} not found (have {len(entries)} entries)"
        entry = entries[index]
        lines = TechDebtLedger.path(root).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.startswith("| ") and not line.startswith("| Date |") and not line.startswith("|------|"):
                parts = [p.strip() for p in line.strip("| ").split("|")]
                if len(parts) >= 5 and parts[0] == entry["date"] and parts[1] == entry["file"] and parts[2] == entry["debt"]:
                    lines[i] = line.replace(" open |", " resolved |")
                    TechDebtLedger.path(root).write_text("\n".join(lines) + "\n", encoding="utf-8")
                    return f"resolved tech debt #{index}: {entry['file']} - {entry['debt']}"
        return "error: could not find entry to resolve"


##########################
#### Blueprint Store #####
##########################
class BlueprintStore:
    @staticmethod
    def dir(root):
        return Path(root) / BLUEPRINT_DIR

    @staticmethod
    def save(root, blueprint_id, pattern, scope, rationale, alternatives, risks):
        store_dir = BlueprintStore.dir(root)
        store_dir.mkdir(parents=True, exist_ok=True)
        data = {"id": blueprint_id, "created_at": now(), "pattern": pattern, "scope": scope,
                "rationale": rationale, "alternatives": alternatives, "risks": risks}
        (store_dir / f"{blueprint_id}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return f"saved blueprint {blueprint_id}: {pattern}"

    @staticmethod
    def list_all(root):
        store_dir = BlueprintStore.dir(root)
        if not store_dir.exists():
            return []
        blueprints = []
        for path in sorted(store_dir.glob("*.json")):
            blueprints.append(json.loads(path.read_text(encoding="utf-8")))
        return blueprints


##########################
#### Session Store #######
##########################
class SessionStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, session_id):
        return self.root / f"{session_id}.json"

    def save(self, session):
        path = self.path(session["id"])
        path.write_text(json.dumps(session, indent=2), encoding="utf-8")
        return path

    def load(self, session_id):
        return json.loads(self.path(session_id).read_text(encoding="utf-8"))

    def latest(self):
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime)
        return files[-1].stem if files else None


class FakeModelClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def complete(self, prompt, max_new_tokens):
        self.prompts.append(prompt)
        if not self.outputs:
            raise RuntimeError("fake model ran out of outputs")
        return self.outputs.pop(0)


class OllamaModelClient:
    def __init__(self, model, host, temperature, top_p, timeout):
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout

    def complete(self, prompt, max_new_tokens):
        payload = {"model": self.model, "prompt": prompt, "stream": False, "raw": False, "think": False,
                   "options": {"num_predict": max_new_tokens, "temperature": self.temperature, "top_p": self.top_p}}
        request = urllib.request.Request(
            self.host + "/api/generate", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Ollama request failed with HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Could not reach Ollama. Make sure `ollama serve` is running.\n"
                f"Host: {self.host}\nModel: {self.model}"
            ) from exc
        if data.get("error"):
            raise RuntimeError(f"Ollama error: {data['error']}")
        return data.get("response", "")


##########################
#### MiniAgent Core ######
##########################
class MiniAgent:
    def __init__(self, model_client, workspace, session_store, session=None,
                 approval_policy="ask", max_steps=6, max_new_tokens=512,
                 depth=0, max_depth=1, read_only=False):
        self.model_client = model_client
        self.workspace = workspace
        self.root = Path(workspace.repo_root)
        self.session_store = session_store
        self.approval_policy = approval_policy
        self.max_steps = max_steps
        self.max_new_tokens = max_new_tokens
        self.depth = depth
        self.max_depth = max_depth
        self.read_only = read_only
        self.session = session or {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "created_at": now(), "workspace_root": workspace.repo_root,
            "history": [], "memory": {"task": "", "files": [], "notes": [], "blueprints": []},
        }
        self.tools = self.build_tools()
        self.prefix = self.build_prefix()
        self.session_path = self.session_store.save(self.session)

    @classmethod
    def from_session(cls, model_client, workspace, session_store, session_id, **kwargs):
        return cls(model_client=model_client, workspace=workspace, session_store=session_store,
                   session=session_store.load(session_id), **kwargs)

    @staticmethod
    def remember(bucket, item, limit):
        if not item:
            return
        if item in bucket:
            bucket.remove(item)
        bucket.append(item)
        del bucket[:-limit]

    def build_tools(self):
        tools = {
            "list_files": {"schema": {"path": "str='.'"}, "risky": False,
                           "description": "List files in the workspace.", "run": self.tool_list_files},
            "read_file": {"schema": {"path": "str", "start": "int=1", "end": "int=200"}, "risky": False,
                          "description": "Read a UTF-8 file by line range.", "run": self.tool_read_file},
            "search": {"schema": {"pattern": "str", "path": "str='.'"}, "risky": False,
                       "description": "Search the workspace with rg or fallback.", "run": self.tool_search},
            "run_shell": {"schema": {"command": "str", "timeout": "int=20"}, "risky": True,
                          "description": "Run a shell command in the repo root.", "run": self.tool_run_shell},
            "write_file": {"schema": {"path": "str", "content": "str"}, "risky": True,
                           "description": "Write a text file.", "run": self.tool_write_file},
            "patch_file": {"schema": {"path": "str", "old_text": "str", "new_text": "str"}, "risky": True,
                           "description": "Replace one exact text block in a file.", "run": self.tool_patch_file},
            "submit_blueprint": {"schema": {"pattern": "str", "scope": "str", "rationale": "str",
                                            "alternatives": "str", "risks": "str"}, "risky": False,
                                 "description": "Record an architecture decision before writing code.", "run": self.tool_submit_blueprint},
            "log_tech_debt": {"schema": {"file": "str", "debt": "str", "reason": "str"}, "risky": False,
                              "description": "Log a tech debt entry when accepting a compromise.", "run": self.tool_log_tech_debt},
        }
        if self.depth < self.max_depth:
            tools["delegate"] = {"schema": {"task": "str", "max_steps": "int=3"}, "risky": False,
                                 "description": "Ask a bounded read-only child agent to investigate.", "run": self.tool_delegate}
        return tools

    def build_prefix(self):
        tool_lines = []
        for name, tool in self.tools.items():
            fields = ", ".join(f"{k}: {v}" for k, v in tool["schema"].items())
            risk = "approval required" if tool["risky"] else "safe"
            tool_lines.append(f"- {name}({fields}) [{risk}] {tool['description']}")
        tool_text = "\n".join(tool_lines)
        examples = "\n".join([
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":80}}</tool>',
            '<tool>{"name":"submit_blueprint","args":{"pattern":"Repository Pattern","scope":"data layer","rationale":"Separation","alternatives":"Active Record","risks":"Extra abstraction"}}</tool>',
            '<tool name="write_file" path="file.py"><content>...</content></tool>',
            '<tool name="patch_file" path="file.py"><old_text>a</old_text><new_text>b</new_text></tool>',
            '<tool>{"name":"run_shell","args":{"command":"pytest -q","timeout":20}}</tool>',
            '<tool>{"name":"log_tech_debt","args":{"file":"file.py","debt":"Skipped validation","reason":"demo"}}</tool>',
            "<final>Done.</final>",
        ])
        rules = "\n".join([
            "- Use tools instead of guessing about the workspace.",
            "- Return exactly one <tool>...</tool> or one <final>...</final>.",
            "- Tool calls must look like: <tool>{\"name\":\"tool_name\",\"args\":{...}}</tool>",
            "- For write_file and patch_file with multi-line text, prefer XML style.",
            "- Final answers must look like: <final>your answer</final>",
            "- Never invent tool results. Keep answers concise.",
            "- Do not repeat the same tool call with the same arguments.",
            "- Required tool arguments must not be empty.",
        ])
        arch_rules = "\n".join([
            "ARCHITECTURE-FIRST (на русском):",
            "- Перед написанием кода вызови submit_blueprint.",
            "- submit_blueprint сохраняет: паттерн, область, обоснование, альтернативы, риски.",
            "- Если пользователь просит компромисс — предложи log_tech_debt.",
            "- После логирования долга добавь комментарий '// [TECH DEBT]: причина'.",
        ])
        return "\n\n".join([
            "You are an Architecture-First Coding Agent. Your job is not just to write code, but to document WHY it was written that way.",
            "Rules:\n" + rules, "Architecture rules:\n" + arch_rules,
            "Tools:\n" + tool_text, "Valid response examples:\n" + examples,
            self.workspace.text(),
        ])

    def memory_text(self):
        memory = self.session["memory"]
        notes = "\n".join(f"- {note}" for note in memory["notes"]) or "- none"
        blueprints = "\n".join(f"- {bp}" for bp in memory["blueprints"]) or "- none"
        return "\n".join([
            "Memory:", f"- task: {memory['task'] or '-'}",
            f"- files: {', '.join(memory['files']) or '-'}",
            "- notes:", notes, "- blueprints:", blueprints,
        ])

    def history_text(self):
        history = self.session["history"]
        if not history:
            return "- empty"
        lines = []
        seen_reads = set()
        recent_start = max(0, len(history) - 6)
        for index, item in enumerate(history):
            recent = index >= recent_start
            if item["role"] == "tool" and item["name"] in ("write_file", "patch_file"):
                seen_reads.discard(str(item["args"].get("path", "")))
            if item["role"] == "tool" and item["name"] == "read_file" and not recent:
                path = str(item["args"].get("path", ""))
                if path in seen_reads:
                    continue
                seen_reads.add(path)
            if item["role"] == "tool":
                limit = 900 if recent else 180
                lines.append(f"[tool:{item['name']}] {json.dumps(item['args'], sort_keys=True)}")
                lines.append(clip(item["content"], limit))
            else:
                limit = 900 if recent else 220
                lines.append(f"[{item['role']}] {clip(item['content'], limit)}")
        return clip("\n".join(lines), MAX_HISTORY)

    def prompt(self, user_message):
        return "\n\n".join([self.prefix, self.memory_text(), "Transcript:\n" + self.history_text(), f"Current user request:\n{user_message}"])

    def record(self, item):
        self.session["history"].append(item)
        self.session_path = self.session_store.save(self.session)

    def note_tool(self, name, args, result):
        memory = self.session["memory"]
        path = args.get("path")
        if name in {"read_file", "write_file", "patch_file"} and path:
            self.remember(memory["files"], str(path), 8)
        if name == "submit_blueprint":
            self.remember(memory["blueprints"], f"{args.get('pattern', '?')} -> {args.get('scope', '?')}", 8)
        self.remember(memory["notes"], f"{name}: {clip(str(result).replace(chr(10), ' '), 220)}", 5)

    def ask(self, user_message):
        memory = self.session["memory"]
        if not memory["task"]:
            memory["task"] = clip(user_message.strip(), 300)
        self.record({"role": "user", "content": user_message, "created_at": now()})
        tool_steps = 0
        attempts = 0
        max_attempts = max(self.max_steps * 3, self.max_steps + 4)

        while tool_steps < self.max_steps and attempts < max_attempts:
            attempts += 1
            with console.status("[bold yellow]Думаю...[/]", spinner="dots"):
                raw = self.model_client.complete(self.prompt(user_message), self.max_new_tokens)
            kind, payload = self.parse(raw)

            if kind == "tool":
                tool_steps += 1
                name = payload.get("name", "")
                args = payload.get("args", {})
                result = self.run_tool(name, args)
                self.record({"role": "tool", "name": name, "args": args, "content": result, "created_at": now()})
                self.note_tool(name, args, result)
                self._display_tool_result(name, args, result)
                continue

            if kind == "retry":
                self.record({"role": "assistant", "content": payload, "created_at": now()})
                continue

            final = (payload or raw).strip()
            self.record({"role": "assistant", "content": final, "created_at": now()})
            self.remember(memory["notes"], clip(final, 220), 5)
            return final

        final = "Остановлен: достигнут лимит шагов без финального ответа."
        if attempts >= max_attempts and tool_steps < self.max_steps:
            final = "Остановлен: слишком много некорректных ответов модели."
        self.record({"role": "assistant", "content": final, "created_at": now()})
        return final

    def _display_tool_result(self, name, args, result):
        tool_colors = {
            "list_files": "blue", "read_file": "cyan", "search": "magenta",
            "run_shell": "yellow", "write_file": "green", "patch_file": "green",
            "submit_blueprint": "bright_blue", "log_tech_debt": "bright_red",
            "delegate": "bright_yellow",
        }
        tool_icons = {
            "list_files": "📂", "read_file": "📄", "search": "🔍",
            "run_shell": "⚡", "write_file": "✏️", "patch_file": "🔧",
            "submit_blueprint": "📐", "log_tech_debt": "⚠️", "delegate": "🤖",
        }
        color = tool_colors.get(name, "white")
        icon = tool_icons.get(name, "🔹")
        title = Text(f" {icon} {name}", style=f"bold {color}")

        if name == "submit_blueprint" and "saved blueprint" in result:
            blueprint_panel = Panel(
                f"[bold]Паттерн:[/] {args.get('pattern', '')}\n"
                f"[bold]Область:[/]  {args.get('scope', '')}\n"
                f"[bold]Зачем:[/]    {args.get('rationale', '')}\n"
                f"[bold]Вместо:[/]   {args.get('alternatives', '')}\n"
                f"[bold]Риски:[/]    {args.get('risks', '')}\n"
                f"\n[dim]{result}[/]",
                title=title, border_style=color, box=box.ROUNDED,
            )
            console.print(blueprint_panel)
        elif name == "log_tech_debt" and "tech debt logged" in result:
            debt_panel = Panel(
                f"[bold]Файл:[/]    {args.get('file', '')}\n"
                f"[bold]Долг:[/]    {args.get('debt', '')}\n"
                f"[bold]Причина:[/] {args.get('reason', '')}\n"
                f"\n[dim]{result}[/]",
                title=title, border_style=color, box=box.ROUNDED,
            )
            console.print(debt_panel)
        elif name == "delegate":
            delegate_panel = Panel(
                f"[bold]Задача:[/] {args.get('task', '')}\n\n{clip(result, 600)}",
                title=title, border_style=color, box=box.ROUNDED,
            )
            console.print(delegate_panel)
        else:
            content = result[:800] + ("..." if len(result) > 800 else "")
            tool_panel = Panel(
                f"{content}",
                title=title, border_style=color, box=box.ROUNDED,
            )
            console.print(tool_panel)

    def run_tool(self, name, args):
        tool = self.tools.get(name)
        if tool is None:
            return f"ошибка: неизвестный инструмент '{name}'"
        try:
            self.validate_tool(name, args)
        except Exception as exc:
            example = self.tool_example(name)
            msg = f"ошибка: неверные аргументы для {name}: {exc}"
            if example:
                msg += f"\nпример: {example}"
            return msg
        if self.repeated_tool_call(name, args):
            return f"ошибка: повторный вызов {name} с теми же аргументами; выберите другой инструмент или верните финальный ответ"
        if tool["risky"] and not self.approve(name, args):
            return f"ошибка: подтверждение отклонено для {name}"
        try:
            return clip(tool["run"](args))
        except Exception as exc:
            return f"ошибка: инструмент {name} не сработал: {exc}"

    def repeated_tool_call(self, name, args):
        tool_events = [item for item in self.session["history"] if item["role"] == "tool"]
        if len(tool_events) < 2:
            return False
        recent = tool_events[-2:]
        return all(item["name"] == name and item["args"] == args for item in recent)

    def tool_example(self, name):
        examples = {
            "list_files": '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            "read_file": '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":80}}</tool>',
            "search": '<tool>{"name":"search","args":{"pattern":"...","path":"."}}</tool>',
            "run_shell": '<tool>{"name":"run_shell","args":{"command":"pytest -q","timeout":20}}</tool>',
            "write_file": '<tool name="write_file" path="f.py"><content>...</content></tool>',
            "patch_file": '<tool name="patch_file" path="f.py"><old_text>a</old_text><new_text>b</new_text></tool>',
            "delegate": '<tool>{"name":"delegate","args":{"task":"inspect README.md","max_steps":3}}</tool>',
            "submit_blueprint": '<tool>{"name":"submit_blueprint","args":{"pattern":"MVC","scope":"web","rationale":"Separation","alternatives":"...","risks":"..."}}</tool>',
            "log_tech_debt": '<tool>{"name":"log_tech_debt","args":{"file":"f.py","debt":"Skipped X","reason":"deadline"}}</tool>',
        }
        return examples.get(name, "")

    def validate_tool(self, name, args):
        args = args or {}
        if name == "list_files":
            path = self.path(args.get("path", "."))
            if not path.is_dir():
                raise ValueError("path is not a directory")
        elif name == "read_file":
            path = self.path(args["path"])
            if not path.is_file():
                raise ValueError("path is not a file")
            start = int(args.get("start", 1))
            end = int(args.get("end", 200))
            if start < 1 or end < start:
                raise ValueError("invalid line range")
        elif name == "search":
            pattern = str(args.get("pattern", "")).strip()
            if not pattern:
                raise ValueError("pattern must not be empty")
            self.path(args.get("path", "."))
        elif name == "run_shell":
            command = str(args.get("command", "")).strip()
            if not command:
                raise ValueError("command must not be empty")
            timeout = int(args.get("timeout", 20))
            if timeout < 1 or timeout > 120:
                raise ValueError("timeout must be in [1, 120]")
        elif name == "write_file":
            path = self.path(args["path"])
            if path.exists() and path.is_dir():
                raise ValueError("path is a directory")
            if "content" not in args:
                raise ValueError("missing content")
        elif name == "patch_file":
            path = self.path(args["path"])
            if not path.is_file():
                raise ValueError("path is not a file")
            old_text = str(args.get("old_text", ""))
            if not old_text:
                raise ValueError("old_text must not be empty")
            if "new_text" not in args:
                raise ValueError("missing new_text")
            text = path.read_text(encoding="utf-8")
            if text.count(old_text) != 1:
                raise ValueError(f"old_text must occur exactly once, found {text.count(old_text)}")
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
        elif name == "delegate":
            if self.depth >= self.max_depth:
                raise ValueError("delegate depth exceeded")
            task = str(args.get("task", "")).strip()
            if not task:
                raise ValueError("task must not be empty")

    def approve(self, name, args):
        if self.read_only:
            return False
        if self.approval_policy == "auto":
            return True
        if self.approval_policy == "never":
            return False
        try:
            answer = Prompt.ask(
                f"[bold yellow]⚠ Подтвердить[/] [bold]{name}[/] [dim]{json.dumps(args, ensure_ascii=True)}[/]",
                choices=["y", "Y", "n", "N"], default="n",
            )
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() == "y"

    @staticmethod
    def parse(raw):
        raw = str(raw)
        if "<tool>" in raw and ("<final>" not in raw or raw.find("<tool>") < raw.find("<final>")):
            body = MiniAgent.extract(raw, "tool")
            try:
                payload = json.loads(body)
            except Exception:
                return "retry", MiniAgent.retry_notice("malformed tool JSON")
            if not isinstance(payload, dict):
                return "retry", MiniAgent.retry_notice("tool payload must be a JSON object")
            if not str(payload.get("name", "")).strip():
                return "retry", MiniAgent.retry_notice("tool payload is missing a tool name")
            args = payload.get("args", {})
            if args is None:
                payload["args"] = {}
            elif not isinstance(args, dict):
                return "retry", MiniAgent.retry_notice()
            return "tool", payload
        if "<tool" in raw and ("<final>" not in raw or raw.find("<tool") < raw.find("<final>")):
            payload = MiniAgent.parse_xml_tool(raw)
            if payload is not None:
                return "tool", payload
            return "retry", MiniAgent.retry_notice()
        if "<final>" in raw:
            final = MiniAgent.extract(raw, "final").strip()
            if final:
                return "final", final
            return "retry", MiniAgent.retry_notice("empty <final> answer")
        raw = raw.strip()
        if raw:
            return "final", raw
        return "retry", MiniAgent.retry_notice("empty response")

    @staticmethod
    def retry_notice(problem=None):
        prefix = "Runtime notice" + (f": {problem}" if problem else ": malformed tool output")
        return f"{prefix}. Reply with a valid <tool> call or a non-empty <final> answer."

    @staticmethod
    def parse_xml_tool(raw):
        match = re.search(r"<tool(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", raw, re.S)
        if not match:
            return None
        attrs = MiniAgent.parse_attrs(match.group("attrs"))
        name = str(attrs.pop("name", "")).strip()
        if not name:
            return None
        body = match.group("body")
        args = dict(attrs)
        for key in ("content", "old_text", "new_text", "command", "task", "pattern", "path"):
            if f"<{key}>" in body:
                args[key] = MiniAgent.extract_raw(body, key)
        body_text = body.strip("\n")
        if name == "write_file" and "content" not in args and body_text:
            args["content"] = body_text
        if name == "delegate" and "task" not in args and body_text:
            args["task"] = body_text.strip()
        return {"name": name, "args": args}

    @staticmethod
    def parse_attrs(text):
        attrs = {}
        for match in re.finditer(r"""([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""", text):
            attrs[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
        return attrs

    @staticmethod
    def extract(text, tag):
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start = text.find(start_tag)
        if start == -1:
            return text
        start += len(start_tag)
        end = text.find(end_tag, start)
        if end == -1:
            return text[start:].strip()
        return text[start:end].strip()

    @staticmethod
    def extract_raw(text, tag):
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start = text.find(start_tag)
        if start == -1:
            return text
        start += len(start_tag)
        end = text.find(end_tag, start)
        if end == -1:
            return text[start:]
        return text[start:end]

    def reset(self):
        self.session["history"] = []
        self.session["memory"] = {"task": "", "files": [], "notes": [], "blueprints": []}
        self.session_store.save(self.session)

    def path_is_within_root(self, resolved):
        probe = resolved
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        for candidate in (probe, *probe.parents):
            try:
                if candidate.samefile(self.root):
                    return True
            except OSError:
                continue
        return False

    def path(self, raw_path):
        path = Path(raw_path)
        path = path if path.is_absolute() else self.root / path
        resolved = path.resolve()
        if not self.path_is_within_root(resolved):
            raise ValueError(f"path escapes workspace: {raw_path}")
        return resolved

    def tool_list_files(self, args):
        path = self.path(args.get("path", "."))
        if not path.is_dir():
            raise ValueError("path is not a directory")
        entries = [e for e in sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name.lower())) if e.name not in IGNORED_PATH_NAMES]
        lines = []
        for entry in entries[:200]:
            lines.append(f"{'[D]' if entry.is_dir() else '[F]'} {entry.relative_to(self.root)}")
        return "\n".join(lines) or "(empty)"

    def tool_read_file(self, args):
        path = self.path(args["path"])
        if not path.is_file():
            raise ValueError("path is not a file")
        start = int(args.get("start", 1))
        end = int(args.get("end", 200))
        if start < 1 or end < start:
            raise ValueError("invalid line range")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        body = "\n".join(f"{n:>4}: {l}" for n, l in enumerate(lines[start - 1:end], start=start))
        return f"# {path.relative_to(self.root)}\n{body}"

    def tool_search(self, args):
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            raise ValueError("pattern must not be empty")
        path = self.path(args.get("path", "."))
        if shutil.which("rg"):
            result = subprocess.run(["rg", "-n", "--smart-case", "--max-count", "200", pattern, str(path)],
                                    cwd=self.root, capture_output=True, text=True)
            return result.stdout.strip() or result.stderr.strip() or "(no matches)"
        matches = []
        files = [path] if path.is_file() else [f for f in path.rglob("*") if f.is_file() and not any(
            part in IGNORED_PATH_NAMES for part in f.relative_to(self.root).parts)]
        for file_path in files:
            for n, line in enumerate(file_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                if pattern.lower() in line.lower():
                    matches.append(f"{file_path.relative_to(self.root)}:{n}:{line}")
                    if len(matches) >= 200:
                        return "\n".join(matches)
        return "\n".join(matches) or "(no matches)"

    def tool_run_shell(self, args):
        command = str(args.get("command", "")).strip()
        if not command:
            raise ValueError("command must not be empty")
        timeout = int(args.get("timeout", 20))
        if timeout < 1 or timeout > 120:
            raise ValueError("timeout must be in [1, 120]")
        result = subprocess.run(command, cwd=self.root, shell=True, capture_output=True, text=True, timeout=timeout)
        return f"exit_code: {result.returncode}\nstdout:\n{result.stdout.strip() or '(empty)'}\nstderr:\n{result.stderr.strip() or '(empty)'}"

    def tool_write_file(self, args):
        path = self.path(args["path"])
        content = str(args["content"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"wrote {path.relative_to(self.root)} ({len(content)} chars)"

    def tool_patch_file(self, args):
        path = self.path(args["path"])
        if not path.is_file():
            raise ValueError("path is not a file")
        old_text = str(args.get("old_text", ""))
        if not old_text:
            raise ValueError("old_text must not be empty")
        if "new_text" not in args:
            raise ValueError("missing new_text")
        text = path.read_text(encoding="utf-8")
        if text.count(old_text) != 1:
            raise ValueError(f"old_text must occur exactly once, found {text.count(old_text)}")
        path.write_text(text.replace(old_text, str(args["new_text"]), 1), encoding="utf-8")
        return f"patched {path.relative_to(self.root)}"

    def tool_submit_blueprint(self, args):
        blueprint_id = uuid.uuid4().hex[:8]
        return BlueprintStore.save(self.root, blueprint_id, args.get("pattern", ""),
                                   args.get("scope", ""), args.get("rationale", ""),
                                   args.get("alternatives", ""), args.get("risks", ""))

    def tool_log_tech_debt(self, args):
        return TechDebtLedger.log(self.root, args.get("file", ""), args.get("debt", ""), args.get("reason", ""))

    def tool_delegate(self, args):
        if self.depth >= self.max_depth:
            raise ValueError("delegate depth exceeded")
        task = str(args.get("task", "")).strip()
        if not task:
            raise ValueError("task must not be empty")
        child = MiniAgent(
            model_client=self.model_client, workspace=self.workspace, session_store=self.session_store,
            approval_policy="never", max_steps=int(args.get("max_steps", 3)),
            max_new_tokens=self.max_new_tokens, depth=self.depth + 1, max_depth=self.max_depth, read_only=True,
        )
        child.session["memory"]["task"] = task
        child.session["memory"]["notes"] = [clip(self.history_text(), 300)]
        return "delegate_result:\n" + child.ask(task)


##########################
#### CLI — Rich UI #######
##########################
WELCOME_ART = (
    "⡆⣐⢕⢕⢕⢕⢕⢕⢕⢕⠅⢗⢕⢕⢕⢕⢕⢕⢕⠕⠕⢕⢕⢕⢕⢕⢕⢕⢕⢕\n"
    "⢐⢕⢕⢕⢕⢕⣕⢕⢕⠕⠁⢕⢕⢕⢕⢕⢕⢕⢕⠅⡄⢕⢕⢕⢕⢕⢕⢕⢕⢕\n"
    "⢕⢕⢕⢕⢕⠅⢗⢕⠕⣠⠄⣗⢕⢕⠕⢕⢕⢕⠕⢠⣿⠐⢕⢕⢕⠑⢕⢕⠵⢕\n"
    "⢕⢕⢕⢕⠁⢜⠕⢁⣴⣿⡇⢓⢕⢵⢐⢕⢕⠕⢁⣾⢿⣧⠑⢕⢕⠄⢑⢕⠅⢕\n"
    "⢕⢕⠵⢁⠔⢁⣤⣤⣶⣶⣶⡐⣕⢽⠐⢕⠕⣡⣾⣶⣶⣶⣤⡁⢓⢕⠄⢑⢅⢑\n"
    "⠍⣧⠄⣶⣾⣿⣿⣿⣿⣿⣿⣷⣔⢕⢄⢡⣾⣿⣿⣿⣿⣿⣿⣿⣦⡑⢕⢤⠱⢐\n"
    "⢠⢕⠅⣾⣿⠋⢿⣿⣿⣿⠉⣿⣿⣷⣦⣶⣽⣿⣿⠈⣿⣿⣿⣿⠏⢹⣷⣷⡅⢐\n"
    "⣔⢕⢥⢻⣿⡀⠈⠛⠛⠁⢠⣿⣿⣿⣿⣿⣿⣿⣿⡀⠈⠛⠛⠁⠄⣼⣿⣿⡇⢔\n"
    "⢕⢕⢽⢸⢟⢟⢖⢖⢤⣶⡟⢻⣿⡿⠻⣿⣿⡟⢀⣿⣦⢤⢤⢔⢞⢿⢿⣿⠁⢕\n"
    "⢕⢕⠅⣐⢕⢕⢕⢕⢕⣿⣿⡄⠛⢀⣦⠈⠛⢁⣼⣿⢗⢕⢕⢕⢕⢕⢕⡏⣘⢕\n"
    "⢕⢕⠅⢓⣕⣕⣕⣕⣵⣿⣿⣿⣾⣿⣿⣿⣿⣿⣿⣿⣷⣕⢕⢕⢕⢕⡵⢀⢕⢕\n"
    "⢑⢕⠃⡈⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⢃⢕⢕⢕\n"
    "⣆⢕⠄⢱⣄⠛⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⢁⢕⢕⠕⢁\n"
    "⣿⣦⡀⣿⣿⣷⣶⣬⣍⣛⣛⣛⡛⠿⠿⠿⠛⠛⢛⣛⣉⣭⣤⣂⢜⠕⢑⣡⣴⣿"
)


def build_welcome(agent, model, host):
    debt_count = len(TechDebtLedger.entries(agent.root))
    bp_count = len(BlueprintStore.list_all(agent.root))

    stats = Table.grid(padding=(0, 2))
    stats.add_column()
    stats.add_column()
    stats.add_row(f"[bold yellow]Долг:[/] {debt_count}", f"[bold blue]Блюпринтов:[/] {bp_count}")

    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold")
    info.add_column()
    info.add_column(style="bold")
    info.add_column()
    info.add_row("Директория", f"[cyan]{middle(agent.workspace.cwd, 40)}[/]", "Модель", f"[green]{model}[/]")
    info.add_row("Ветка", f"[magenta]{agent.workspace.branch}[/]", "Сессия", f"[dim]{agent.session['id']}[/]")
    info.add_row("Подтвержд.", f"[yellow]{agent.approval_policy}[/]", "", "")

    layout = Panel(
        Align.center(
            Text(WELCOME_ART, style="bright_yellow") + "\n" +
            Text("NEKOCODE", style="bold white on blue", no_wrap=True) + "\n\n" +
            info + "\n" +
            Align.center(stats),
            vertical="middle",
        ),
        box=box.DOUBLE_EDGE,
        border_style="bright_blue",
        padding=(1, 2),
    )
    return layout


def audit_tech_debt(agent):
    entries = TechDebtLedger.entries(agent.root)
    if not entries:
        return Panel(Align.center("[green]Техдолга нет. Чистый код.[/]"), border_style="green", box=box.ROUNDED)

    open_entries = [e for e in entries if e["status"] == "open"]
    resolved_entries = [e for e in entries if e["status"] == "resolved"]

    table = Table(box=box.SIMPLE, header_style="bold")
    table.add_column("#", style="dim")
    table.add_column("Дата")
    table.add_column("Файл")
    table.add_column("Долг")
    table.add_column("Причина")
    table.add_column("Статус")

    for i, entry in enumerate(entries):
        status_style = "green" if entry["status"] == "resolved" else "red"
        table.add_row(str(i), entry["date"], entry["file"], entry["debt"],
                      entry["reason"], f"[{status_style}]{'закрыт' if entry['status'] == 'resolved' else 'открыт'}[/]")

    bp_count = len(BlueprintStore.list_all(agent.root))
    summary = f"[bold]Открыто:[/] {len(open_entries)}  [bold]Закрыто:[/] {len(resolved_entries)}  [bold]Блюпринтов:[/] {bp_count}"

    return Panel(
        table,
        title=f"[bold]Аудит Техдолга[/] — {agent.workspace.repo_root}",
        subtitle=summary,
        border_style="yellow",
        box=box.ROUNDED,
    )


def show_memory(agent):
    memory = agent.session["memory"]
    task = memory["task"] or "-"
    files = ", ".join(memory["files"]) or "-"

    content = Text()
    content.append(f"Задача: {task}\n\n", style="bold")
    content.append(f"Файлы: {files}\n", style="cyan")

    if memory["blueprints"]:
        content.append("\nБлюпринты:\n", style="bold blue")
        for bp in memory["blueprints"]:
            content.append(f"  • {bp}\n", style="blue")

    if memory["notes"]:
        content.append(f"\nПоследние заметки:\n", style="bold")
        for note in memory["notes"][-5:]:
            content.append(f"  ℹ {note}\n", style="dim")

    return Panel(content, title="🧠 Рабочая Память", border_style="cyan", box=box.ROUNDED)


def show_blueprints(agent):
    blueprints = BlueprintStore.list_all(agent.root)
    if not blueprints:
        return Panel(Align.center("[blue]Блюпринтов пока нет.[/]"), border_style="blue", box=box.ROUNDED)

    table = Table(box=box.SIMPLE, header_style="bold blue")
    table.add_column("ID", style="dim")
    table.add_column("Паттерн")
    table.add_column("Область")
    table.add_column("Обоснование")
    table.add_column("Альтернативы")
    table.add_column("Риски")

    for bp in blueprints:
        table.add_row(bp["id"], bp["pattern"], bp["scope"], bp["rationale"], bp.get("alternatives", "-"), bp.get("risks", "-"))

    return Panel(table, title="📐 Архитектурные Блюпринты", border_style="blue", box=box.ROUNDED)


def show_help():
    help_text = """[bold]Команды:[/]

  [bold]/help[/]       Показать справку
  [bold]/memory[/]     Показать рабочую память
  [bold]/session[/]    Путь к файлу сессии
  [bold]/blueprints[/] Список архитектурных блюпринтов
  [bold]/audit[/]      Аудит техдолга
  [bold]/resolve[/] <n> Закрыть запись техдолга
  [bold]/reset[/]      Сбросить историю сессии
  [bold]/exit[/]       Выйти

[bold]Советы:[/]
  • Агент вызывает [bold]submit_blueprint[/] перед написанием кода
  • Используйте [bold]log_tech_debt[/] для логирования компромиссов
  • Запустите [bold]/audit[/] чтобы увидеть, что нужно рефакторить"""
    return Panel(help_text, title="💡 Help", border_style="magenta", box=box.ROUNDED)


def build_agent(args):
    workspace = WorkspaceContext.build(args.cwd)
    store = SessionStore(Path(workspace.repo_root) / ".mini-coding-agent" / "sessions")
    model = OllamaModelClient(model=args.model, host=args.host, temperature=args.temperature,
                              top_p=args.top_p, timeout=args.ollama_timeout)
    session_id = args.resume
    if session_id == "latest":
        session_id = store.latest()
    if session_id:
        return MiniAgent.from_session(model_client=model, workspace=workspace, session_store=store,
                                      session_id=session_id, approval_policy=args.approval,
                                      max_steps=args.max_steps, max_new_tokens=args.max_new_tokens)
    return MiniAgent(model_client=model, workspace=workspace, session_store=store,
                     approval_policy=args.approval, max_steps=args.max_steps, max_new_tokens=args.max_new_tokens)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="NekoCode — архитектурный агент кода с блюпринтами и учётом техдолга.",
    )
    parser.add_argument("prompt", nargs="*", help="Одноразовый запрос (без интерактива).")
    parser.add_argument("--cwd", default=".", help="Рабочая директория.")
    parser.add_argument("--model", default="qwen3.5:4b", help="Имя модели Ollama.")
    parser.add_argument("--host", default="http://127.0.0.1:11434", help="URL сервера Ollama.")
    parser.add_argument("--ollama-timeout", type=int, default=300, help="Таймаут запроса к Ollama (сек).")
    parser.add_argument("--resume", default=None, help="ID сессии для возобновления или 'latest'.")
    parser.add_argument("--approval", choices=("ask", "auto", "never"), default="ask",
                        help="Политика подтверждения рискованных инструментов.")
    parser.add_argument("--max-steps", type=int, default=6, help="Максимум итераций инструментов на запрос.")
    parser.add_argument("--max-new-tokens", type=int, default=512, help="Максимум токенов в ответе модели.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Температура семплирования.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Top-p семплирования.")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    agent = build_agent(args)

    console.print()
    console.print(build_welcome(agent, model=args.model, host=args.host))
    console.print()

    if args.prompt:
        prompt = " ".join(args.prompt).strip()
        if prompt:
            try:
                response = agent.ask(prompt)
                console.print(Panel(Markdown(response), title="💬 Ответ", border_style="green", box=box.ROUNDED))
            except RuntimeError as exc:
                console.print(f"[red]Ошибка:[/] {exc}")
                return 1
        return 0

    while True:
        try:
            user_input = Prompt.ask("\n[bold bright_blue]❯[/] [bold]nekocode[/]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]До свидания![/]")
            return 0

        if not user_input:
            continue

        if user_input in {"/exit", "/quit"}:
            console.print("[yellow]До свидания![/]")
            return 0
        if user_input == "/help":
            console.print(show_help())
            continue
        if user_input == "/memory":
            console.print(show_memory(agent))
            continue
        if user_input == "/session":
            console.print(f"[dim]Сессия:[/] [cyan]{agent.session_path}[/]")
            continue
        if user_input == "/blueprints":
            console.print(show_blueprints(agent))
            continue
        if user_input == "/audit":
            console.print(audit_tech_debt(agent))
            continue
        if user_input == "/reset":
            agent.reset()
            console.print("[yellow]Сессия сброшена.[/]")
            continue
        if user_input.startswith("/resolve "):
            try:
                index = int(user_input.split(" ", 1)[1])
                result = TechDebtLedger.resolve(agent.root, index)
                console.print(Panel(f"[green]{result}[/]", border_style="green", box=box.ROUNDED))
            except (ValueError, IndexError):
                console.print("[red]Использование: /resolve <номер_записи>[/]")
            continue

        try:
            response = agent.ask(user_input)
            console.print(Panel(Markdown(response), title="💬 Ответ", border_style="green", box=box.ROUNDED))
        except RuntimeError as exc:
            console.print(f"[red]Ошибка:[/] {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
