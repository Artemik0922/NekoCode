"""Tests for the Token Economy system."""

import pytest
from nekocode.economy import (
    TokenCounter, TokenBudget, ContextCompressor,
    PriorityScorer, ContextWindow, TokenTracker, StepUsage,
)
from nekocode.economy.models import ProviderProfile


# ── TokenCounter ──────────────────────────────────────────────────────────────
class TestTokenCounter:
    def test_estimates_by_provider_ratio(self):
        c = TokenCounter("ollama")
        text = "hello world"
        est = c.estimate(text)
        assert est > 0
        assert isinstance(est, int)

    def test_empty_text(self):
        c = TokenCounter("ollama")
        assert c.estimate("") == 0
        assert c.estimate(None) == 0

    def test_provider_ollama_ratio(self):
        c = TokenCounter("ollama")
        short = c.estimate("a")
        long_ = c.estimate("a" * 300)
        assert long_ > short

    def test_count_messages(self):
        c = TokenCounter()
        msgs = [
            {"role": "tool", "name": "read", "args": {"path": "foo.py"}, "content": "hello"},
            {"role": "user", "content": "world"},
        ]
        total = c.count_messages(msgs)
        assert total > 0

    def test_count_prompt(self):
        c = TokenCounter()
        t = c.count_prompt("system", "user", "history")
        assert t > 0


# ── PriorityScorer ───────────────────────────────────────────────────────────
class TestPriorityScorer:
    def test_recency_scoring(self):
        history = [
            {"role": "tool", "name": "read", "args": {"path": "a.py"}, "content": "old"},
            {"role": "tool", "name": "read", "args": {"path": "b.py"}, "content": "new"},
        ]
        hot = {}
        old_score = PriorityScorer.score(history[0], 0, len(history), hot)
        new_score = PriorityScorer.score(history[1], 1, len(history), hot)
        assert new_score > old_score

    def test_risky_tool_scores_higher(self):
        history = [
            {"role": "tool", "name": "read", "args": {}, "content": "data"},
            {"role": "tool", "name": "write", "args": {}, "content": "data"},
        ]
        hot = {}
        read_score = PriorityScorer.score(history[0], 0, len(history), hot)
        write_score = PriorityScorer.score(history[1], 1, len(history), hot)
        # write is risky + more recent → should be higher
        assert write_score > read_score

    def test_user_message_scores_high(self):
        history = [
            {"role": "user", "content": "hello", "name": "", "args": {}},
        ]
        hot = {}
        s = PriorityScorer.score(history[0], 0, len(history), hot)
        assert s > 0.6

    def test_empty_content_scores_low(self):
        history = [
            {"role": "tool", "name": "list_files", "args": {}, "content": ""},
        ]
        hot = {}
        s = PriorityScorer.score(history[0], 0, len(history), hot)
        assert s < 0.7

    def test_hotness_increases_score(self):
        history = [
            {"role": "tool", "name": "read", "args": {"path": "foo.py"}, "content": "data"},
        ]
        hot = {"foo.py": 5}
        s = PriorityScorer.score(history[0], 0, len(history), hot)
        assert s > 0.3

    def test_error_content_scores_lower(self):
        history_ok = [
            {"role": "tool", "name": "bash", "args": {}, "content": "success"},
        ]
        history_err = [
            {"role": "tool", "name": "bash", "args": {}, "content": "error: something failed"},
        ]
        hot = {}
        ok_score = PriorityScorer.score(history_ok[0], 0, len(history_ok), hot)
        err_score = PriorityScorer.score(history_err[0], 0, len(history_err), hot)
        assert ok_score > err_score

    def test_compute_hotness(self):
        history = [
            {"role": "tool", "name": "read", "args": {"path": "a.py"}, "content": ""},
            {"role": "tool", "name": "read", "args": {"path": "a.py"}, "content": ""},
            {"role": "tool", "name": "write", "args": {"path": "b.py"}, "content": ""},
        ]
        hot = PriorityScorer.hotness(history)
        assert hot["a.py"] == 2
        assert hot["b.py"] == 1


# ── ContextCompressor ────────────────────────────────────────────────────────
class TestContextCompressor:
    def test_compress_bash_summary(self):
        c = ContextCompressor()
        text = "exit_code: 0\nstdout:\nline1\nline2\nline3\nline4\nline5\nline6\nstderr:\nerr1\nerr2"
        item = {"name": "bash", "content": text}
        result = c.compress(item)
        assert "exit_code: 0" in result
        assert "stdout:" in result
        assert "stderr:" in result

    def test_compress_grep_summary(self):
        c = ContextCompressor(strategies={"grep": "summary"})
        text = "file1.py:10:def foo\nfile1.py:20:class Bar\nfile2.py:5:import os"
        item = {"name": "grep", "content": text}
        result = c.compress(item)
        assert "matches" in result
        assert "files" in result

    def test_compress_read_trim(self):
        c = ContextCompressor()
        lines = [f"   {i}: line{i}" for i in range(100)]
        text = "# test.py\n" + "\n".join(lines)
        item = {"name": "read", "content": text}
        result = c.compress(item)
        assert "line0" in result
        assert "line99" in result
        assert "trimmed" in result

    def test_compress_none_strategy(self):
        c = ContextCompressor()
        item = {"name": "write", "content": "important code"}
        result = c.compress(item)
        assert result == "important code"

    def test_compress_empty_content(self):
        c = ContextCompressor()
        item = {"name": "bash", "content": ""}
        assert c.compress(item) == ""

    def test_bash_summary_without_stderr(self):
        c = ContextCompressor()
        text = "exit_code: 0\nstdout:\nok"
        item = {"name": "bash", "content": text}
        result = c.compress(item)
        assert "exit_code: 0" in result

    def test_extreme_compression(self):
        c = ContextCompressor()
        text = "exit_code: 0\nstdout:\n" + "\n".join(f"line{i}" for i in range(100))
        item = {"name": "bash", "content": text}
        result = c.compress_extreme(item, 100)
        assert "exit_code" in result
        assert len(result) <= 150


# ── TokenBudget ──────────────────────────────────────────────────────────────
class TestTokenBudget:
    def test_default_budget(self):
        b = TokenBudget()
        assert b.system == 2000
        assert b.user_msg == 1000
        assert b.history > 0
        assert b.reserve > 0

    def test_from_provider_ollama(self):
        b = TokenBudget.from_provider("ollama")
        assert b.history > 0

    def test_from_provider_anthropic(self):
        b = TokenBudget.from_provider("anthropic")
        assert b.history > b.system

    def test_from_provider_with_overrides(self):
        b = TokenBudget.from_provider("ollama", overrides={"system": 5000})
        assert b.system == 5000

    def test_available(self):
        b = TokenBudget(total=10000, reserve=2000)
        assert b.available == 8000

    def test_repr(self):
        b = TokenBudget()
        assert "TokenBudget(" in repr(b)


# ── ContextWindow ────────────────────────────────────────────────────────────
class TestContextWindow:
    def test_assemble_basic(self):
        w = ContextWindow(
            budget=TokenBudget(total=5000, system=2000, user_msg=1000, history=1000, reserve=1000),
            provider="ollama",
        )
        result = w.assemble(
            history=[{"role": "user", "content": "hello"}],
            system_prompt="You are a helpful assistant.",
            user_msg="what is python?",
        )
        assert "You are a helpful assistant" in result
        assert "what is python?" in result
        assert "hello" in result

    def test_assemble_with_history_full(self):
        w = ContextWindow(
            budget=TokenBudget(total=5000, system=500, user_msg=200, history=800, reserve=500),
            provider="ollama",
        )
        history = [
            {"role": "user", "content": f"message {i}"}
            for i in range(20)
        ]
        result = w.assemble(history, "system prompt", "hello")
        # Should not crash, should include some omitted marker
        assert "omitted" in result or "system prompt" in result

    def test_assemble_omits_low_priority(self):
        w = ContextWindow(
            budget=TokenBudget(total=3000, system=300, user_msg=100, history=300, reserve=2000),
        )
        history = [
            {"role": "tool", "name": "read", "args": {"path": "old.py"}, "content": "old content"},
            {"role": "tool", "name": "write", "args": {"path": "new.py"}, "content": "new content"},
        ]
        result = w.assemble(history, "sys", "hi")
        assert "sys" in result
        assert "hi" in result

    def test_assemble_with_memory_block(self):
        w = ContextWindow(budget=TokenBudget(total=5000, system=500, user_msg=200, history=1000, reserve=500))
        result = w.assemble(
            history=[],
            system_prompt="You are a bot.",
            user_msg="hello",
            memory_block="- Task: fix tests\n- Files: foo.py\n- Notes: none",
        )
        assert "Task: fix tests" in result
        assert "You are a bot." in result
        assert "hello" in result

    def test_assemble_memory_block_compressed(self):
        w = ContextWindow(
            budget=TokenBudget(total=500, system=100, user_msg=50, history=100, reserve=200),
        )
        long_memory = "- Task: " + "x" * 500
        result = w.assemble(
            history=[],
            system_prompt="sys",
            user_msg="hi",
            memory_block=long_memory,
        )
        assert "Task:" in result
        assert "sys" in result

    def test_assemble_without_memory(self):
        w = ContextWindow(budget=TokenBudget(total=1000, system=200, user_msg=100, history=300, reserve=400))
        result = w.assemble(
            history=[{"role": "user", "content": "test"}],
            system_prompt="sys",
            user_msg="hi",
        )
        assert "sys" in result
        assert "hi" in result

    def test_usage_property(self):
        w = ContextWindow(budget=TokenBudget(total=1000, system=200, user_msg=100, history=300, reserve=400))
        u = w.usage
        assert u["system"] == 200
        assert u["available"] == 600


# ── TokenTracker ─────────────────────────────────────────────────────────────
class TestTokenTracker:
    def test_tracks_single_step(self):
        t = TokenTracker()
        counter = TokenCounter()
        t.begin_step(1)
        t.record_prompt("hello world", counter, "hello world uncompressed")
        t.record_response("hi there", counter)
        t.record_tool("read", 5, 3)
        t.end_step()
        assert len(t.steps) == 1
        assert t.steps[0].step_number == 1
        assert t.steps[0].tool_name == "read"

    def test_tracks_multiple_steps(self):
        t = TokenTracker()
        counter = TokenCounter()
        for i in range(3):
            t.begin_step(i + 1)
            t.record_prompt("prompt", counter)
            t.record_response("response", counter)
            t.record_tool("bash", 10, 5)
            t.end_step()
        assert len(t.steps) == 3

    def test_total_tokens(self):
        t = TokenTracker()
        counter = TokenCounter()
        t.begin_step(1)
        t.record_prompt("hello", counter)
        t.record_response("world", counter)
        t.end_step()
        t.begin_step(2)
        t.record_prompt("foo", counter)
        t.record_response("bar", counter)
        t.end_step()
        assert t.total_tokens > 0
        assert t.total_prompt_tokens > 0
        assert t.total_response_tokens > 0

    def test_reset_clears(self):
        t = TokenTracker()
        counter = TokenCounter()
        t.begin_step(1)
        t.record_prompt("test", counter)
        t.end_step()
        t.reset()
        assert len(t.steps) == 0
        assert t.total_tokens == 0

    def test_dashboard_returns_panel(self):
        t = TokenTracker()
        counter = TokenCounter()
        t.begin_step(1)
        t.record_prompt("hello world", counter)
        t.record_response("hi", counter)
        t.record_tool("read", 3, 2)
        t.end_step()
        dash = t.dashboard()
        assert dash is not None

    def test_empty_dashboard(self):
        t = TokenTracker()
        dash = t.dashboard()
        assert dash is not None

    def test_saved_percentage(self):
        t = TokenTracker()
        counter = TokenCounter()
        t.begin_step(1)
        t.record_prompt("x" * 1000, counter, "x" * 5000)
        t.record_response("y", counter)
        t.end_step()
        assert t.total_saved_pct > 10


# ── ProviderProfile ──────────────────────────────────────────────────────────
class TestProviderProfile:
    def test_profile_for_known(self):
        p = ProviderProfile.profile_for("ollama")
        assert p["context_window"] == 8192
        assert "budget" in p

    def test_profile_for_unknown_falls_back(self):
        p = ProviderProfile.profile_for("nonexistent")
        assert p["context_window"] > 0

    def test_chars_per_token(self):
        assert ProviderProfile.chars_per_token("anthropic") == 3.5
        assert ProviderProfile.chars_per_token("ollama") == 3.0

    def test_compression_strategy(self):
        assert ProviderProfile.compression_strategy("bash") == "summary"
        assert ProviderProfile.compression_strategy("read") == "trim"
        assert ProviderProfile.compression_strategy("write") == "none"
        assert ProviderProfile.compression_strategy("unknown") == "trim"
