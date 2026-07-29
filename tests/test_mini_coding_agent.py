import json
import pytest
from unittest.mock import patch

from rich.panel import Panel

from nekocode.agent import (
    BlueprintStore,
    FakeModelClient,
    MiniAgent,
    OllamaModelClient,
    SessionStore,
    TechDebtLedger,
    WorkspaceContext,
)
from nekocode.cli import (
    audit_tech_debt,
    build_welcome,
)


def build_workspace(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def build_agent(tmp_path, outputs, **kwargs):
    workspace = build_workspace(tmp_path)
    store = SessionStore(tmp_path)
    approval_policy = kwargs.pop("approval_policy", "auto")
    return MiniAgent(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def test_agent_runs_tool_then_final(tmp_path):
    (tmp_path / "hello.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read","args":{"path":"hello.txt","offset":1,"limit":2}}</tool>',
            "<final>Read the file successfully.</final>",
        ],
    )

    answer = agent.ask("Inspect hello.txt")

    assert answer == "Read the file successfully."
    assert any(item["role"] == "tool" and item["name"] == "read" for item in agent.session["history"])
    assert "hello.txt" in agent.session["memory"]["files"]


def test_agent_retries_after_empty_model_output(tmp_path):
    agent = build_agent(
        tmp_path,
        ["", "<final>Recovered after retry.</final>"],
    )

    answer = agent.ask("Do the task")

    assert answer == "Recovered after retry."
    notices = [item["content"] for item in agent.session["history"] if item["role"] == "assistant"]
    assert any("empty response" in item for item in notices)


def test_agent_retries_after_malformed_tool_payload(tmp_path):
    (tmp_path / "hello.txt").write_text("alpha\n", encoding="utf-8")
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read","args":"bad"}</tool>',
            '<tool>{"name":"read","args":{"path":"hello.txt","offset":1,"limit":1}}</tool>',
            "<final>Recovered after malformed tool output.</final>",
        ],
    )

    answer = agent.ask("Inspect hello.txt")

    assert answer == "Recovered after malformed tool output."
    assert any(item["role"] == "tool" and item["name"] == "read" for item in agent.session["history"])
    notices = [item["content"] for item in agent.session["history"] if item["role"] == "assistant"]
    assert any("valid <tool> call" in item for item in notices)


def test_agent_accepts_xml_write_file_tool(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool name="write" path="hello.py"><content>print("hi")\n</content></tool>',
            "<final>Done.</final>",
        ],
    )

    answer = agent.ask("Create hello.py")

    assert answer == "Done."
    assert (tmp_path / "hello.py").read_text(encoding="utf-8") == 'print("hi")\n'


def test_retries_do_not_consume_the_whole_budget(tmp_path):
    agent = build_agent(
        tmp_path,
        ["", "", "<final>Recovered after several retries.</final>"],
        max_steps=1,
    )

    answer = agent.ask("Do the task")

    assert answer == "Recovered after several retries."


def test_agent_saves_and_resumes_session(tmp_path):
    agent = build_agent(tmp_path, ["<final>First pass.</final>"])
    assert agent.ask("Start a session") == "First pass."

    resumed = MiniAgent.from_session(
        model_client=FakeModelClient(["<final>Resumed.</final>"]),
        workspace=agent.workspace,
        session_store=agent.session_store,
        session_id=agent.session["id"],
        approval_policy="auto",
    )

    assert resumed.session["history"][0]["content"] == "Start a session"
    assert resumed.ask("Continue") == "Resumed."


def test_delegate_uses_child_agent(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"delegate","args":{"task":"inspect README","max_steps":2}}</tool>',
            "<final>Child result.</final>",
            "<final>Parent incorporated the child result.</final>",
        ],
    )

    answer = agent.ask("Use delegation")

    assert answer == "Parent incorporated the child result."
    tool_events = [item for item in agent.session["history"] if item["role"] == "tool"]
    assert tool_events[0]["name"] == "delegate"
    assert "SUBAGENT RESULT" in tool_events[0]["content"]


def test_patch_file_replaces_exact_match(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello world\n", encoding="utf-8")
    agent = build_agent(tmp_path, [])

    result = agent.run_tool(
        "edit",
        {"path": "sample.txt", "old_text": "world", "new_text": "agent"},
    )

    assert result == "edited sample.txt"
    assert file_path.read_text(encoding="utf-8") == "hello agent\n"


def test_invalid_risky_tool_does_not_prompt_for_approval(tmp_path):
    agent = build_agent(tmp_path, [], approval_policy="ask")

    with patch("builtins.input") as mock_input:
        result = agent.run_tool("write", {})

    assert result.startswith("error: invalid args for write")
    mock_input.assert_not_called()


def test_list_files_hides_internal_agent_state(tmp_path):
    agent = build_agent(tmp_path, [])
    (tmp_path / ".mini-coding-agent").mkdir(exist_ok=True)
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / "hello.txt").write_text("hi\n", encoding="utf-8")

    result = agent.run_tool("list_files", {})

    assert ".mini-coding-agent" not in result
    assert ".git" not in result
    assert "[F] hello.txt" in result


def test_path_rejects_parent_escape(tmp_path):
    agent = build_agent(tmp_path, [])

    with pytest.raises(ValueError, match="path escapes workspace"):
        agent._path("../outside.txt")


def test_path_rejects_symlink_escape(tmp_path):
    agent = build_agent(tmp_path, [])
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "outside-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available in this environment")

    with pytest.raises(ValueError, match="path escapes workspace"):
        agent._path("outside-link/secret.txt")


def test_path_accepts_case_variant_on_case_insensitive_filesystems(tmp_path):
    project_root = tmp_path / "Proj"
    project_root.mkdir()
    agent = build_agent(project_root, [])
    variant = project_root.parent / project_root.name.lower() / "README.md"

    if not variant.exists():
        pytest.skip("case-sensitive filesystem")

    resolved = agent._path(str(variant))
    assert resolved.samefile(project_root / "README.md")


def test_repeated_identical_tool_call_is_rejected(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.record({"role": "tool", "name": "list_files", "args": {}, "content": "(empty)", "created_at": "1"})
    agent.record({"role": "tool", "name": "list_files", "args": {}, "content": "(empty)", "created_at": "2"})

    result = agent.run_tool("list_files", {})

    assert result.startswith("error: repeated identical call to list_files")


def test_welcome_screen_contains_title_and_info(tmp_path):
    deep = tmp_path / "very" / "long" / "path" / "for" / "the" / "mini" / "agent" / "welcome" / "screen"
    deep.mkdir(parents=True)
    agent = build_agent(deep, [])

    from rich.console import Console
    from io import StringIO
    buf = StringIO()
    console = Console(file=buf, width=120)
    console.print(build_welcome(agent, model="qwen3.5:4b", host="http://127.0.0.1:11434"))
    output = buf.getvalue()

    assert "NEKOCODE" in output
    assert "⡆⣐⢕⢕" in output


def test_prompt_top_level_sections_stay_flush_left_with_multiline_content(tmp_path):
    workspace = WorkspaceContext(
        cwd=str(tmp_path),
        repo_root=str(tmp_path),
        branch="fix/prompt-indentation",
        default_branch="main",
        status=" M mini_coding_agent.py\n?? tests/test_prompt.py",
        recent_commits=["abc123 first commit", "def456 second commit"],
    )
    store = SessionStore(tmp_path)
    agent = MiniAgent(
        model_client=FakeModelClient([]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
    )
    agent.session["memory"] = {
        "task": "verify prompt formatting",
        "files": ["mini_coding_agent.py"],
        "notes": ["saw inconsistent indentation", "need regression coverage"],
        "blueprints": [],
    }
    agent.record({"role": "user", "content": "inspect prompt()", "created_at": "1"})
    agent.record(
        {
            "role": "tool",
            "name": "read",
            "args": {"path": "mini_coding_agent.py"},
            "content": "    def prompt(self, user_message):\n        ...",
            "created_at": "2",
        }
    )

    prompt = agent.prompt("is this issue legit?")
    lines = prompt.splitlines()

    for label in ["## System", "## Doing tasks", "## Tone and style", "## Tools", "## Transcript", "## Current user request"]:
        assert label in lines
        assert f"            {label}" not in prompt


def _make_filler(i):
    return {"role": "tool", "name": "list_files", "args": {}, "content": "", "created_at": str(i)}


def test_history_text_deduplicates_reads_but_not_after_write(tmp_path):
    agent = build_agent(tmp_path, [])

    agent.record({"role": "user", "content": "update config", "created_at": "0"})
    agent.record({"role": "assistant", "content": '<tool>{"name":"read","args":{"path":"config.txt"}}</tool>', "created_at": "1"})
    agent.record({"role": "tool", "name": "read", "args": {"path": "config.txt"}, "content": "# config.txt\n   1: setting=true\n", "created_at": "2"})
    agent.record({"role": "assistant", "content": '<tool>{"name":"write","args":{"path":"config.txt","content":"setting=false\n"}}</tool>', "created_at": "3"})
    agent.record({"role": "tool", "name": "write", "args": {"path": "config.txt", "content": "setting=false\n"}, "content": "wrote config.txt", "created_at": "4"})
    agent.record({"role": "assistant", "content": '<tool>{"name":"read","args":{"path":"config.txt"}}</tool>', "created_at": "5"})
    agent.record({"role": "tool", "name": "read", "args": {"path": "config.txt"}, "content": "# config.txt\n   1: setting=false\n", "created_at": "6"})
    for i in range(7, 13):
        agent.record(_make_filler(i))

    history = agent._history_text()

    assert "# config.txt\n   1: setting=true\n" in history
    assert "# config.txt\n   1: setting=false\n" in history
    assert history.count("setting=true") == 1


def test_history_text_deduplicates_unchanged_repeated_reads(tmp_path):
    agent = build_agent(tmp_path, [])

    agent.record({"role": "user", "content": "check logs", "created_at": "0"})
    agent.record({"role": "assistant", "content": '<tool>{"name":"read","args":{"path":"log.txt"}}</tool>', "created_at": "1"})
    agent.record({"role": "tool", "name": "read", "args": {"path": "log.txt"}, "content": "# log.txt\n   1: stable\n", "created_at": "2"})
    agent.record({"role": "assistant", "content": '<tool>{"name":"read","args":{"path":"log.txt"}}</tool>', "created_at": "3"})
    for i in range(4, 10):
        agent.record(_make_filler(i))

    history = agent._history_text()

    assert history.count("stable") == 1


def test_ollama_client_posts_expected_payload():
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"response": "<final>ok</final>"}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    client = OllamaModelClient(
        model="qwen3.5:4b",
        host="http://127.0.0.1:11434",
        temperature=0.2,
        top_p=0.9,
        timeout=30,
    )

    with patch("urllib.request.urlopen", fake_urlopen):
        result = client.complete("hello", 42)

    assert result == "<final>ok</final>"
    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
    assert captured["timeout"] == 30
    assert captured["body"]["model"] == "qwen3.5:4b"
    assert captured["body"]["prompt"] == "hello"
    assert captured["body"]["stream"] is False
    assert captured["body"]["raw"] is False
    assert captured["body"]["think"] is False
    assert captured["body"]["options"]["num_predict"] == 42


def test_submit_blueprint_creates_file(tmp_path):
    agent = build_agent(tmp_path, [])
    result = agent.run_tool(
        "submit_blueprint",
        {
            "pattern": "Repository Pattern",
            "scope": "data access layer",
            "rationale": "Separate concerns",
            "alternatives": "Active Record",
            "risks": "Extra abstraction",
        },
    )
    assert "saved blueprint" in result
    assert "Repository Pattern" in result
    bp_dir = tmp_path / ".agent" / "blueprints"
    assert bp_dir.exists()
    files = list(bp_dir.glob("*.json"))
    assert len(files) == 1


def test_submit_blueprint_with_empty_pattern_fails(tmp_path):
    agent = build_agent(tmp_path, [])
    result = agent.run_tool(
        "submit_blueprint",
        {"pattern": "", "scope": "test", "rationale": "test", "alternatives": "", "risks": ""},
    )
    assert "error: invalid args" in result
    assert "pattern must not be empty" in result


def test_log_tech_debt_creates_file(tmp_path):
    agent = build_agent(tmp_path, [])
    result = agent.run_tool(
        "log_tech_debt",
        {"file": "binary_search.py", "debt": "Skipped input validation", "reason": "demo deadline"},
    )
    assert "tech debt logged:" in result
    ledger_path = tmp_path / ".tech-debt-log.md"
    assert ledger_path.exists()
    content = ledger_path.read_text(encoding="utf-8")
    assert "binary_search.py" in content
    assert "demo deadline" in content


def test_log_tech_debt_with_empty_file_fails(tmp_path):
    agent = build_agent(tmp_path, [])
    result = agent.run_tool(
        "log_tech_debt",
        {"file": "", "debt": "test", "reason": "test"},
    )
    assert "error: invalid args" in result


def test_tech_debt_ledger_entries(tmp_path):
    TechDebtLedger.log(tmp_path, "file1.py", "bad pattern", "rush")
    TechDebtLedger.log(tmp_path, "file2.py", "no tests", "deadline")
    entries = TechDebtLedger.entries(tmp_path)
    assert len(entries) == 2
    assert entries[0]["file"] == "file1.py"
    assert entries[1]["file"] == "file2.py"
    assert entries[0]["status"] == "open"
    assert entries[1]["status"] == "open"


def test_tech_debt_ledger_resolve(tmp_path):
    TechDebtLedger.log(tmp_path, "file1.py", "bad pattern", "rush")
    result = TechDebtLedger.resolve(tmp_path, 0)
    assert "resolved" in result
    entries = TechDebtLedger.entries(tmp_path)
    assert entries[0]["status"] == "resolved"


def test_tech_debt_ledger_resolve_out_of_range(tmp_path):
    result = TechDebtLedger.resolve(tmp_path, 99)
    assert "error: entry 99 not found" in result


def test_blueprint_store_list(tmp_path):
    BlueprintStore.save(tmp_path, "MVC", "web layer", "Standard pattern", "", "")
    BlueprintStore.save(tmp_path, "Event Sourcing", "audit log", "Traceability", "CQRS", "Complexity")
    blueprints = BlueprintStore.list_all(tmp_path)
    assert len(blueprints) == 2
    patterns = {bp["pattern"] for bp in blueprints}
    assert "MVC" in patterns
    assert "Event Sourcing" in patterns


def test_blueprint_store_empty(tmp_path):
    result = BlueprintStore.text_summary(tmp_path)
    assert "No blueprints recorded yet." in result


def test_audit_with_open_debt(tmp_path):
    TechDebtLedger.log(tmp_path, "bad.py", "hardcoded url", "demo")
    agent = build_agent(tmp_path, [])
    from rich.console import Console
    from io import StringIO
    buf = StringIO()
    console = Console(file=buf, width=120)
    console.print(audit_tech_debt(agent))
    output = buf.getvalue()
    assert "hardcoded url" in output
    assert "bad.py" in output


def test_audit_clean_codebase(tmp_path):
    agent = build_agent(tmp_path, [])
    result = audit_tech_debt(agent)
    assert "Техдолга нет" in str(result.renderable)


def test_submit_blueprint_updates_memory(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"submit_blueprint","args":{"pattern":"MVC","scope":"web","rationale":"Separation","alternatives":"none","risks":"none"}}</tool>',
            "<final>Blueprint submitted.</final>",
        ],
    )
    agent.ask("Design the architecture")
    assert "MVC" in agent.session["memory"]["blueprints"][0]


def test_task_create_and_complete(tmp_path):
    agent = build_agent(tmp_path, [])
    r1 = agent.run_tool("task_create", {"title": "Add tests", "description": "Write unit tests"})
    assert "created task:" in r1
    tid = r1.split()[2]  # "created task: abc12345 - Add tests" -> "abc12345"
    tasks = agent.task_manager.list()
    assert len(tasks) == 1
    assert tasks[0]["status"] == "pending"

    r2 = agent.run_tool("task_done", {"task_id": tid})
    assert "completed" in r2
    assert agent.task_manager.list()[0]["status"] == "completed"


def test_remember_and_recall(tmp_path):
    agent = build_agent(tmp_path, [])
    r1 = agent.run_tool("remember", {
        "type": "user",
        "name": "prefers-terse",
        "description": "User prefers short answers",
        "body": "This user wants terse responses with no trailing summaries.",
    })
    assert "saved memory:" in r1

    r2 = agent.run_tool("recall", {"list": True})
    assert "prefers-terse" in r2
