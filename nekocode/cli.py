"""NekoCode CLI — rich terminal UI with Russian locale, cat art, slash commands."""

import argparse
from pathlib import Path

from rich import box
from rich.align import Align
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from nekocode.agent import (
    BlueprintStore, MiniAgent, OllamaModelClient, SessionStore,
    TechDebtLedger, WorkspaceContext, MemoryStore,
)

console = Console()

# ── Cat ASCII art ──────────────────────────────────────────────────
CAT_ART = (
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


def middle(text, width):
    text = str(text)
    if len(text) <= width:
        return text
    half = (width - 3) // 2
    return text[:half] + "..." + text[-half:]


# ── Welcome Screen ─────────────────────────────────────────────────
def build_welcome(agent, model, host):
    debt_count = len(TechDebtLedger.entries(agent.root))
    bp_count = len(BlueprintStore.list_all(agent.root))
    mem_count = len(agent.memory_store.list_all())

    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold")
    info.add_column()
    info.add_column(style="bold")
    info.add_column()
    info.add_row("Директория", f"[cyan]{middle(agent.workspace.cwd, 40)}[/]", "Модель", f"[green]{model}[/]")
    info.add_row("Ветка", f"[magenta]{agent.workspace.branch}[/]", "Сессия", f"[dim]{agent.session['id']}[/]")
    info.add_row("Подтвержд.", f"[yellow]{agent.approval_policy}[/]", "Шаги", f"[cyan]{agent.max_steps}[/]")

    stats = Table.grid(padding=(0, 2))
    stats.add_column()
    stats.add_column()
    stats.add_column()
    stats.add_row(f"[bold yellow]Долг:[/] {debt_count}",
                  f"[bold blue]Блюпринтов:[/] {bp_count}",
                  f"[bold green]Воспоминаний:[/] {mem_count}")

    from rich.text import Text as RichText
    title = RichText("NEKOCODE v0.4", style="bold white on blue", no_wrap=True)
    cat = RichText(CAT_ART, style="bright_yellow")
    layout = Panel(
        Align.center(RichText.assemble(cat, "\n\n", title), vertical="middle"),
        box=box.DOUBLE_EDGE,
        border_style="bright_blue",
        padding=(1, 2),
    )
    return layout


# ── Help ───────────────────────────────────────────────────────────
def show_help():
    help_text = """[bold]Команды:[/]

  [bold]/help[/]       Показать справку
  [bold]/memory[/]     Показать рабочую память сессии
  [bold]/session[/]    Путь к файлу сессии
  [bold]/blueprints[/] Список архитектурных блюпринтов
  [bold]/audit[/]      Аудит техдолга
  [bold]/resolve[/] <n> Закрыть запись техдолга
  [bold]/recall[/]     Показать всё из постоянной памяти
  [bold]/task[/]       Список активных задач
  [bold]/reset[/]      Сбросить историю сессии
  [bold]/exit[/]       Выйти

[bold]Инструменты:[/]
  • read, write, edit — работа с файлами
  • glob, grep — поиск файлов и кода
  • bash — запуск команд
  • agent — делегирование под-агенту (explore, plan, general)
  • task_create, task_update, task_done — управление задачами
  • submit_blueprint — запись архитектурного решения
  • log_tech_debt — логирование техдолга
  • remember, recall — постоянная память

[bold]Советы:[/]
  • Используйте [bold]submit_blueprint[/] перед написанием кода
  • Используйте [bold]log_tech_debt[/] для компромиссов
  • Запустите [bold]/audit[/] чтобы увидеть, что нужно рефакторить
  • Память сохраняется между сессиями — используйте [bold]remember[/]"""
    return Panel(help_text, title="💡 NekoCode Help", border_style="magenta", box=box.ROUNDED)


# ── Memory Panel ───────────────────────────────────────────────────
def show_memory(agent):
    m = agent.session["memory"]
    task = m["task"] or "-"
    files = ", ".join(m["files"]) or "-"

    content = Text()
    content.append(f"Задача: {task}\n\n", style="bold")
    content.append(f"Файлы: {files}\n", style="cyan")

    if m["blueprints"]:
        content.append("\nБлюпринты:\n", style="bold blue")
        for bp in m["blueprints"]:
            content.append(f"  • {bp}\n", style="blue")

    if m["notes"]:
        content.append("\nЗаметки:\n", style="bold")
        for note in m["notes"][-5:]:
            content.append(f"  ℹ {note}\n", style="dim")

    tasks = agent.task_manager.list()
    if tasks:
        content.append("\nЗадачи:\n", style="bold green")
        for t in tasks:
            status_color = "green" if t["status"] == "completed" else "yellow" if t["status"] == "in_progress" else "red"
            content.append(f"  [{status_color}]{t['status']}[/] {t['title']} [dim]{t['id']}[/]\n")

    return Panel(content, title="🧠 Память Сессии", border_style="cyan", box=box.ROUNDED)


# ── Audit Panel ────────────────────────────────────────────────────
def audit_tech_debt(agent):
    entries = TechDebtLedger.entries(agent.root)
    if not entries:
        return Panel(Align.center("[green]Техдолга нет. Чистый код.[/]"), border_style="green", box=box.ROUNDED)

    open_e = [e for e in entries if e["status"] == "open"]
    resolved_e = [e for e in entries if e["status"] == "resolved"]

    table = Table(box=box.SIMPLE, header_style="bold")
    table.add_column("#", style="dim")
    table.add_column("Дата")
    table.add_column("Файл")
    table.add_column("Долг")
    table.add_column("Причина")
    table.add_column("Статус")

    for i, e in enumerate(entries):
        s_style = "green" if e["status"] == "resolved" else "red"
        s_label = "закрыт" if e["status"] == "resolved" else "открыт"
        table.add_row(str(i), e["date"], e["file"], e["debt"], e["reason"], f"[{s_style}]{s_label}[/]")

    bp_count = len(BlueprintStore.list_all(agent.root))
    summary = f"[bold]Открыто:[/] {len(open_e)}  [bold]Закрыто:[/] {len(resolved_e)}  [bold]Блюпринтов:[/] {bp_count}"

    return Panel(table, title=f"Аудит Техдолга — {agent.workspace.repo_root}",
                 subtitle=summary, border_style="yellow", box=box.ROUNDED)


# ── Blueprints Panel ───────────────────────────────────────────────
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
        table.add_row(bp["id"], bp["pattern"], bp["scope"], bp["rationale"],
                       bp.get("alternatives", "-"), bp.get("risks", "-"))

    return Panel(table, title="📐 Архитектурные Блюпринты", border_style="blue", box=box.ROUNDED)


# ── Persistent Memory Panel ────────────────────────────────────────
def show_persistent_memory(agent):
    items = agent.memory_store.list_all()
    if not items:
        return Panel(Align.center("[dim]Постоянная память пуста.[/]"))
    content = Text()
    for item in items:
        content.append(f"  {item}\n")
    return Panel(content, title="💾 Постоянная Память (.agent/memory/)",
                 border_style="green", box=box.ROUNDED)


# ── Tasks Panel ────────────────────────────────────────────────────
def show_tasks(agent):
    tasks = agent.task_manager.list()
    if not tasks:
        return Panel(Align.center("[dim]Нет активных задач.[/]"))
    table = Table(box=box.SIMPLE, header_style="bold green")
    table.add_column("ID")
    table.add_column("Задача")
    table.add_column("Статус")
    for t in tasks:
        sc = "green" if t["status"] == "completed" else "yellow" if t["status"] == "in_progress" else "red"
        table.add_row(t["id"], t["title"], f"[{sc}]{t['status']}[/]")
    return Panel(table, title="📋 Задачи", border_style="green", box=box.ROUNDED)


# ── Tool display ───────────────────────────────────────────────────
def display_tool_result(name, args, result):
    color_map = {
        "read": "cyan", "write": "green", "edit": "green",
        "glob": "blue", "grep": "magenta",
        "bash": "yellow",
        "submit_blueprint": "bright_blue", "log_tech_debt": "bright_red",
        "agent": "bright_yellow",
        "task_create": "green", "task_update": "green", "task_done": "green",
        "remember": "bright_green", "recall": "bright_green",
    }
    icon_map = {
        "read": "📄", "write": "✏️", "edit": "🔧",
        "glob": "📂", "grep": "🔍",
        "bash": "⚡",
        "submit_blueprint": "📐", "log_tech_debt": "⚠️",
        "agent": "🤖",
        "task_create": "📝", "task_update": "📋", "task_done": "✅",
        "remember": "💾", "recall": "🔎",
    }
    color = color_map.get(name, "white")
    icon = icon_map.get(name, "🔹")
    title = Text(f" {icon} {name}", style=f"bold {color}")

    if name == "submit_blueprint" and "saved blueprint" in result:
        panel = Panel(
            f"[bold]Паттерн:[/] {args.get('pattern', '')}\n"
            f"[bold]Область:[/]  {args.get('scope', '')}\n"
            f"[bold]Зачем:[/]    {args.get('rationale', '')}\n"
            f"[bold]Вместо:[/]   {args.get('alternatives', '')}\n"
            f"[bold]Риски:[/]    {args.get('risks', '')}\n"
            f"\n[dim]{result}[/]",
            title=title, border_style=color, box=box.ROUNDED,
        )
    elif name == "log_tech_debt" and "tech debt logged" in result:
        panel = Panel(
            f"[bold]Файл:[/]    {args.get('file', '')}\n"
            f"[bold]Долг:[/]    {args.get('debt', '')}\n"
            f"[bold]Причина:[/] {args.get('reason', '')}\n"
            f"\n[dim]{result}[/]",
            title=title, border_style=color, box=box.ROUNDED,
        )
    elif name == "agent":
        panel = Panel(
            f"[bold]Тип:[/] {args.get('subagent_type', 'general-purpose')}\n"
            f"[bold]Задача:[/] {args.get('task', '')}\n\n"
            f"[dim]{result[:800]}[/]",
            title=title, border_style=color, box=box.ROUNDED,
        )
    else:
        content = result[:800] + ("..." if len(result) > 800 else "")
        panel = Panel(content, title=title, border_style=color, box=box.ROUNDED)

    console.print(panel)


# ── Argument Parser ────────────────────────────────────────────────
def build_arg_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="NekoCode — агент кода с блюпринтами, техдолгом и русским интерфейсом.",
    )
    parser.add_argument("prompt", nargs="*", help="Одноразовый запрос (без интерактива).")
    parser.add_argument("--cwd", default=".", help="Рабочая директория.")
    parser.add_argument("--model", default="qwen3.5:4b", help="Имя модели Ollama.")
    parser.add_argument("--host", default="http://127.0.0.1:11434", help="URL сервера Ollama.")
    parser.add_argument("--ollama-timeout", type=int, default=300, help="Таймаут запроса к Ollama (сек).")
    parser.add_argument("--resume", default=None, help="ID сессии для возобновления или 'latest'.")
    parser.add_argument("--approval", choices=("ask", "auto", "never"), default="ask",
                        help="Политика подтверждения рискованных инструментов.")
    parser.add_argument("--max-steps", type=int, default=8, help="Максимум итераций инструментов на запрос.")
    parser.add_argument("--max-new-tokens", type=int, default=1024, help="Максимум токенов в ответе модели.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Температура семплирования.")
    parser.add_argument("--top-p", type=float, default=0.9, help="Top-p семплирования.")
    return parser


# ── Agent Factory ──────────────────────────────────────────────────
def build_agent(args):
    workspace = WorkspaceContext.build(args.cwd)
    store = SessionStore(Path(workspace.repo_root))
    mem = MemoryStore(Path(workspace.repo_root)).init()
    model = OllamaModelClient(model=args.model, host=args.host, temperature=args.temperature,
                              top_p=args.top_p, timeout=args.ollama_timeout)
    session_id = args.resume
    if session_id == "latest":
        session_id = store.latest()
    if session_id:
        return MiniAgent.from_session(
            model_client=model, workspace=workspace, session_store=store,
            memory_store=mem, session_id=session_id,
            approval_policy=args.approval, max_steps=args.max_steps,
            max_new_tokens=args.max_new_tokens)
    return MiniAgent(
        model_client=model, workspace=workspace, session_store=store,
        memory_store=mem, approval_policy=args.approval,
        max_steps=args.max_steps, max_new_tokens=args.max_new_tokens)


# ── Main ───────────────────────────────────────────────────────────
def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    agent = build_agent(args)

    console.print()
    console.print(build_welcome(agent, model=args.model, host=args.host))
    console.print()

    if args.prompt:
        prompt = " ".join(args.prompt).strip()
        if prompt:
            response = agent.ask(prompt)
            console.print(Panel(Markdown(response), title="💬 Ответ", border_style="green", box=box.ROUNDED))
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
        if user_input == "/recall":
            console.print(show_persistent_memory(agent))
            continue
        if user_input == "/task":
            console.print(show_tasks(agent))
            continue
        if user_input == "/reset":
            agent.reset()
            console.print("[yellow]Сессия сброшена.[/]")
            continue
        if user_input.startswith("/resolve "):
            try:
                idx = int(user_input.split(" ", 1)[1])
                result = TechDebtLedger.resolve(agent.root, idx)
                console.print(Panel(f"[green]{result}[/]", border_style="green", box=box.ROUNDED))
            except (ValueError, IndexError):
                console.print("[red]Использование: /resolve <номер_записи>[/]")
            continue

        response = agent.ask(user_input)
        console.print(Panel(Markdown(response), title="💬 Ответ", border_style="green", box=box.ROUNDED))
