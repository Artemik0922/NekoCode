"""Content-aware compression per tool type."""

from nekocode.economy.models import ProviderProfile


class ContextCompressor:
    def __init__(self, provider=None, strategies=None):
        self.provider = provider
        self.strategies = strategies or {}

    def strategy_for(self, item):
        name = item.get("name", "")
        return self.strategies.get(name) or ProviderProfile.compression_strategy(name)

    def compress(self, item, budget_chars=None):
        content = str(item.get("content", ""))
        if not content:
            return content

        strategy = self.strategy_for(item)
        if strategy == "none":
            return content

        if strategy == "summary":
            return self._summary(item, content, budget_chars)
        if strategy == "counts":
            return self._counts(content, budget_chars)
        if strategy == "trim":
            return self._trim(content, budget_chars)
        return self._trim(content, budget_chars)

    def compress_extreme(self, item, budget_chars=200):
        content = str(item.get("content", ""))
        name = item.get("name", "")
        if name == "bash":
            return self._bash_summary_exit_only(content)
        return content[:budget_chars] + "..."

    @staticmethod
    def _trim(text, budget_chars=None):
        if budget_chars and len(text) <= budget_chars:
            return text
        lines = text.splitlines()
        if len(lines) <= 3:
            return text[:budget_chars] + "..." if budget_chars and len(text) > budget_chars else text
        head_count = max(1, len(lines) // 4)
        tail_count = max(1, min(len(lines) - head_count, 8))
        head = lines[:head_count]
        tail = lines[-tail_count:]
        result = "\n".join(head) + f"\n... [{len(lines) - head_count - tail_count} lines trimmed] ...\n" + "\n".join(tail)
        if budget_chars and len(result) > budget_chars:
            return result[:budget_chars] + "..."
        return result

    def _summary(self, item, content, budget_chars=None):
        name = item.get("name", "")
        if name == "bash":
            return self._bash_summary(content, budget_chars)
        if name == "grep":
            return self._grep_summary(content, budget_chars)
        if name in ("web_fetch", "web_search"):
            return self._web_summary(content, budget_chars)
        if name == "read":
            return self._read_summary(content, budget_chars)
        return self._trim(content, budget_chars)

    @staticmethod
    def _bash_summary(text, budget_chars=None):
        lines = text.splitlines()
        exit_code = ""
        stdout_lines = 0
        stderr_lines = 0
        stdout_tail = []
        stderr_tail = []
        mode = None
        for line in lines:
            if line.startswith("exit_code:"):
                exit_code = line
                mode = None
            elif line == "stdout:" or line == "(empty)":
                mode = "out"
            elif line == "stderr:" or line == "(empty)":
                if mode == "out":
                    stdout_lines = max(stdout_lines, 1)
                mode = "err"
            elif mode == "out":
                stdout_lines += 1
                if stdout_lines > len(stdout_tail):
                    stdout_tail.append(line)
                    if len(stdout_tail) > 5:
                        stdout_tail.pop(0)
            elif mode == "err":
                stderr_lines += 1
                if stderr_lines > len(stderr_tail):
                    stderr_tail.append(line)
                    if len(stderr_tail) > 5:
                        stderr_tail.pop(0)
        base = f"{exit_code}, stdout: {stdout_lines} lines, stderr: {stderr_lines} lines"
        if stdout_tail:
            base += "\n[stdout tail]\n" + "\n".join(stdout_tail)
        if budget_chars and len(base) > budget_chars:
            return base[:budget_chars] + "..."
        if not budget_chars and len(base) > 1000:
            return base
        return base

    @staticmethod
    def _grep_summary(text, budget_chars=None):
        lines = text.splitlines()
        file_counts = {}
        for line in lines:
            if ":" in line and not line.startswith("["):
                parts = line.split(":", 1)
                fname = parts[0]
                file_counts[fname] = file_counts.get(fname, 0) + 1
        if file_counts:
            result = f"[grep results: {sum(file_counts.values())} matches in {len(file_counts)} files]\n"
            result += "\n".join(f"  {f}: {c} matches" for f, c in sorted(file_counts.items())[:20])
            if len(file_counts) > 20:
                result += f"\n  ... and {len(file_counts) - 20} more files"
        else:
            result = f"[grep: {len(lines)} matches]"
            result += "\n" + "\n".join(lines[:10])
        if budget_chars and len(result) > budget_chars:
            return result[:budget_chars] + "..."
        return result

    @staticmethod
    def _web_summary(text, budget_chars=None):
        lines = text.splitlines()
        if not lines:
            return text
        head = lines[:5]
        tail = lines[-5:] if len(lines) > 10 else []
        result = "\n".join(head)
        if tail:
            result += f"\n... [{len(lines) - 10} lines trimmed] ...\n" + "\n".join(tail)
        if budget_chars and len(result) > budget_chars:
            return result[:budget_chars] + "..."
        return result

    @staticmethod
    def _read_summary(text, budget_chars=None):
        lines = text.splitlines()
        if not lines:
            return text
        total = len(lines)
        file_header = lines[0] if lines[0].startswith("# ") else ""
        content_lines = [l for l in lines if l and not l.startswith("# ")]
        head = content_lines[:5]
        tail = content_lines[-10:] if len(content_lines) > 15 else []
        result = file_header + f"\n[{total} lines total]"
        if head:
            result += "\n" + "\n".join(head)
        if tail:
            result += f"\n... [{max(0, len(content_lines) - 5 - len(tail))} lines between] ...\n" + "\n".join(tail)
        if budget_chars and len(result) > budget_chars:
            return result[:budget_chars] + "..."
        return result

    @staticmethod
    def _counts(text, budget_chars=None):
        lines = text.splitlines()
        result = f"[{len(lines)} entries]"
        if len(lines) <= 10:
            result = text
        else:
            result += "\n" + "\n".join(lines[:5]) + f"\n... [{len(lines) - 10} more] ...\n" + "\n".join(lines[-5:])
        if budget_chars and len(result) > budget_chars:
            return result[:budget_chars] + "..."
        return result

    @staticmethod
    def _bash_summary_exit_only(text):
        lines = text.splitlines()
        exit_line = next((l for l in lines if l.startswith("exit_code:")), "exit_code: ?")
        out_count = sum(1 for l in lines if l and not l.startswith("exit_") and not l.startswith("stdout:") and not l.startswith("stderr:"))
        return f"{exit_line}, {out_count} lines total"
