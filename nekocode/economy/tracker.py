"""TokenTracker — per-step token usage monitoring with dashboard."""

from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class StepUsage:
    def __init__(self, step_number):
        self.step_number = step_number
        self.tool_name = None
        self.prompt_tokens = 0
        self.response_tokens = 0
        self.input_chars = 0
        self.output_chars = 0
        self.uncompressed_chars = 0
        self.time = now()

    @property
    def saved(self):
        if self.uncompressed_chars <= 0:
            return 0.0
        compressed = self.input_chars
        if compressed <= 0:
            return 0.0
        raw_ratio = self.uncompressed_chars / compressed
        return round((1 - 1 / raw_ratio) * 100) if raw_ratio > 1 else 0

    @property
    def total(self):
        return self.prompt_tokens + self.response_tokens


class TokenTracker:
    def __init__(self):
        self.steps = []
        self.current = None

    def begin_step(self, step_number):
        self.current = StepUsage(step_number)

    def record_prompt(self, text, counter, uncompressed_text=None):
        if not self.current:
            return
        self.current.input_chars = len(str(text))
        self.current.prompt_tokens = counter.estimate(text)
        if uncompressed_text:
            self.current.uncompressed_chars = len(str(uncompressed_text))

    def record_response(self, text, counter):
        if not self.current:
            return
        self.current.output_chars = len(str(text))
        self.current.response_tokens = counter.estimate(text)

    def record_tool(self, name, input_tokens, output_tokens):
        if not self.current:
            return
        self.current.tool_name = name

    def end_step(self):
        if self.current:
            self.steps.append(self.current)
            self.current = None

    def reset(self):
        self.steps = []
        self.current = None

    @property
    def total_prompt_tokens(self):
        return sum(s.prompt_tokens for s in self.steps)

    @property
    def total_response_tokens(self):
        return sum(s.response_tokens for s in self.steps)

    @property
    def total_tokens(self):
        return self.total_prompt_tokens + self.total_response_tokens

    @property
    def total_saved_pct(self):
        total_uncompressed = sum(s.uncompressed_chars for s in self.steps if s.uncompressed_chars > 0)
        total_compressed = sum(s.input_chars for s in self.steps if s.input_chars > 0)
        if total_compressed <= 0 or total_uncompressed <= total_compressed:
            return 0.0
        return round((1 - total_compressed / total_uncompressed) * 100)

    def dashboard(self):
        from rich.table import Table
        from rich.panel import Panel
        from rich.console import Group
        from rich.text import Text

        total_prompt = self.total_prompt_tokens
        total_response = self.total_response_tokens
        total = total_prompt + total_response
        saved_pct = self.total_saved_pct

        # Overview
        overview = Table.grid(padding=(0, 2))
        overview.add_column(style="bold bright_cyan")
        overview.add_column(style="bold white")
        overview.add_row("Prompt", f"{total_prompt:,}")
        overview.add_row("Response", f"{total_response:,}")
        overview.add_row("Total", f"{total:,}")
        overview.add_row("Saved", f"{saved_pct}%" if saved_pct > 0 else "0%")

        info = Panel(overview, title="[bold]Token Usage[/]", border_style="bright_blue")

        if not self.steps:
            return info

        # Per-step table
        table = Table(show_header=True, header_style="bold bright_magenta", box=None, padding=(0, 1))
        table.add_column("Step", style="dim")
        table.add_column("Tool", style="bold")
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        table.add_column("Total", justify="right")
        table.add_column("Saved", justify="right")

        for s in self.steps:
            table.add_row(
                str(s.step_number),
                s.tool_name or "-",
                str(s.prompt_tokens),
                str(s.response_tokens),
                str(s.total),
                f"{s.saved}%" if s.saved else "-",
            )

        return Group(info, Panel(table, title="[bold]Per Step[/]", border_style="bright_blue"))
