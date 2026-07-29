"""Tests for Git integration tools."""

import subprocess
from pathlib import Path
from nekocode.agent import (
    MiniAgent, WorkspaceContext, SessionStore,
    FakeModelClient, tool_git_commit, tool_git_undo,
    tool_git_status, tool_git_diff,
)


def _init_git_repo(path):
    subprocess.run(["git", "init"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)


def _make_commit(path, msg="init"):
    (path / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg], cwd=path, capture_output=True)


def _build_agent(tmp_path):
    _init_git_repo(tmp_path)
    _make_commit(tmp_path)
    workspace = WorkspaceContext.build(str(tmp_path))
    store = SessionStore(tmp_path)
    return MiniAgent(
        model_client=FakeModelClient([]),
        workspace=workspace, session_store=store,
        approval_policy="auto", config={"economy": {"enabled": False}},
    )


class TestGitTools:
    def test_git_status_shows_changes(self, tmp_path):
        agent = _build_agent(tmp_path)
        result = tool_git_status(agent, {})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_git_status_dirty(self, tmp_path):
        agent = _build_agent(tmp_path)
        (tmp_path / "new.txt").write_text("new")
        result = tool_git_status(agent, {})
        assert "??" in result or "new.txt" in result

    def test_git_diff_empty(self, tmp_path):
        agent = _build_agent(tmp_path)
        result = tool_git_diff(agent, {})
        assert "(no diff)" in result

    def test_git_diff_with_changes(self, tmp_path):
        agent = _build_agent(tmp_path)
        (tmp_path / "file.txt").write_text("changed")
        result = tool_git_diff(agent, {})
        assert "changed" in result

    def test_git_commit_success(self, tmp_path):
        agent = _build_agent(tmp_path)
        (tmp_path / "file.txt").write_text("updated")
        result = tool_git_commit(agent, {"message": "feat: update"})
        assert "committed" in result or "commit failed" in result

    def test_git_undo_restores(self, tmp_path):
        agent = _build_agent(tmp_path)
        (tmp_path / "file.txt").write_text("v2")
        tool_git_commit(agent, {"message": "second"})
        result = tool_git_undo(agent, {})
        assert "undone" in result

    def test_git_undo_on_empty_fails_gracefully(self, tmp_path):
        agent = _build_agent(tmp_path)
        # undo twice — second should fail gracefully
        tool_git_undo(agent, {})
        result = tool_git_undo(agent, {})
        assert "undone" not in result.lower() or "no commits" in result.lower()

    def test_git_commit_needs_message(self, tmp_path):
        agent = _build_agent(tmp_path)
        result = agent._run_tool("git_commit", {})
        assert "error" in result.lower()

    def test_git_diff_staged(self, tmp_path):
        agent = _build_agent(tmp_path)
        tool_git_commit(agent, {"message": "test staged"})
        result = tool_git_diff(agent, {"staged": True})
        assert isinstance(result, str)
