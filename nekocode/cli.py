"""NekoCode CLI — custom TUI console with Rich."""

import argparse
import io
import os
import sys
from datetime import datetime
from pathlib import Path

# ── Windows console setup ─────────────────────────────────────────
def _setup_console():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        m = ctypes.c_uint32()
        k32.GetConsoleMode(h, ctypes.byref(m))
        m.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        k32.SetConsoleMode(h, m)
        k32.SetConsoleOutputCP(65001)
        k32.SetConsoleCP(65001)
        k32.SetConsoleTitleW("NekoCode")
    except Exception:
        pass
    try:
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
# ───────────────────────────────────────────────────────────────────

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

from nekocode.agent import (
    BlueprintStore, MiniAgent, SessionStore,
    TechDebtLedger, WorkspaceContext, MemoryStore,
)
from nekocode.config import Config
from nekocode.providers import create_provider_from_config
from nekocode.theme import MIMO_THEME, Theme, list_themes, load_theme

console = Console(force_terminal=sys.stdout.isatty())

SESSION_START = datetime.now()

CAT_ART = (
    "          /\\__/\\\n"
    "         /  w  \\\n"
    "        /  O O  \\\n"
    "       /  __^__  \\\n"
    "      /  (=====)  \\\n"
    "     /  (=====)    \\\n"
    "    /  (=====)       \\\n"
    "   /  (=====)   _     \\\n"
    "  /  (=====)  ( )      \\\n"
    " /__(=====)__(___)______\\"
)


def middle(text, width):
    text = str(text)
    if len(text) <= width:
        return text
    half = (width - 3) // 2
    return text[:half] + "..." + text[-half:]


def build_header(agent, provider_name, model_name, theme=MIMO_THEME):
    """Status bar — always at top."""
    from nekocode import __version__
    eco = "⏣" if agent.economy_enabled else "⏥"
    mode = "🏛" if agent.architect_mode else "⚡"
    hist_len = len(agent.session.get("history", [])) if agent.session else 0
    branch = agent.workspace.branch
    return Panel(
        Text.assemble(
            (" 🐱 ", ""),
            ("NekoCode", Style(color=theme.primary, bold=True)),
            (f" v{__version__}", Style(color=theme.text_muted)),
            (" │ ", Style(color=theme.border)),
            ("🤖 ", ""),
            (f"{provider_name}/{model_name}", Style(color=theme.text)),
            (" │ ", Style(color=theme.border)),
            (f"🌿 {branch}", Style(color=theme.text_muted)),
            (" │ ", Style(color=theme.border)),
            (eco, Style(color=theme.warning if agent.economy_enabled else theme.text_muted)),
            (" │ ", Style(color=theme.border)),
            (mode, ""),
            (" │ ", Style(color=theme.border)),
            (f"📝 {hist_len}", Style(color=theme.text_muted)),
        ),
        box=box.HORIZONTALS,
        border_style=theme.border,
        padding=(0, 1),
        style=Style(bgcolor=theme.panel_bg),
    )


def build_footer(agent, theme=MIMO_THEME):
    """Status bar at the bottom."""
    cwd = middle(os.path.basename(os.path.abspath(agent.root)), 40)
    session_id = agent.session["id"][:8] if agent.session else "-"
    mcp_count = len(agent.mcp_manager.servers) if agent.mcp_manager else 0
    parts = [
        (f" 📁 {cwd}", Style(color=theme.text_muted)),
        (" │ ", Style(color=theme.border_subtle)),
        (f"💾 {session_id}", Style(color=theme.text_muted)),
    ]
    if mcp_count:
        parts += [
            (" │ ", Style(color=theme.border_subtle)),
            (f"⊙ {mcp_count}", Style(color=theme.success)),
        ]
    return Text.assemble(*parts)


def render_message(msg, theme=MIMO_THEME):
    """Render a chat message as a styled block."""
    cached = msg.get("_rendered")
    if cached is not None:
        return cached
    if msg["role"] == "user":
        panel = Panel(
            Markdown(msg["content"]),
            title=Text.assemble((" Вы ", Style(color=theme.text, bold=True))),
            border_style=theme.primary,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    elif msg["role"] == "assistant":
        panel = Panel(
            Markdown(msg["content"]),
            title=Text.assemble((" NekoCode ", Style(color=theme.accent, bold=True))),
            border_style=theme.accent,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    elif msg["role"] == "tool":
        t = msg.get("name", "?")
        a = msg.get("args", {})
        c = msg.get("content", "")[:200]
        panel = Panel(
            Text.assemble(
                (f" {t} ", Style(color=theme.text_muted, bold=True)),
                (f"{a}", Style(color=theme.text_muted)),
                "\n",
                (c[:200], Style(color=theme.text_muted, dim=True)),
            ),
            border_style=theme.border,
            box=box.SQUARE,
            padding=(0, 1),
        )
    else:
        panel = Text("")
    msg["_rendered"] = panel
    return panel


def build_messages(agent, max_messages=10, theme=MIMO_THEME):
    """Render recent conversation."""
    hist = agent.session.get("history", [])
    if not hist:
        return Panel(
            Align.center(Text.assemble(("Начните диалог...", Style(color=theme.text_muted)))),
            border_style=theme.border,
            box=box.ROUNDED,
        )
    recent = hist[-max_messages:]
    return Group(*[render_message(m, theme) for m in recent])


def build_welcome(agent, model, provider_name, theme=MIMO_THEME):
    from nekocode import __version__
    cat = Text(CAT_ART, style=Style(color=theme.primary, bold=True))
    title = Text("NEKOCODE", style=Style(color=theme.primary, bold=True))
    version = Text(f"v{__version__}", style=Style(color=theme.text_muted))
    eco_label = "включена" if agent.economy_enabled else "выключена"
    eco_st = theme.text if agent.economy_enabled else theme.text_muted
    mode_label = "архитектор" if agent.architect_mode else "нормальный"
    mode_st = theme.warning if agent.architect_mode else theme.text
    info = Text.assemble(
        ("\n", ""),
        (f"Провайдер: {provider_name}  ", Style(color=theme.secondary)),
        (f"Модель: {model}  ", Style(color=theme.text)),
        (f"Ветка: {agent.workspace.branch}  ", Style(color=theme.text_muted)),
        ("\n", ""),
        ("Экономия: ", Style(color=theme.text_muted)), (eco_label, Style(color=eco_st)),
        ("  Режим: ", Style(color=theme.text_muted)), (mode_label, Style(color=mode_st)),
        ("  Шаги: ", Style(color=theme.text_muted)), (f"{agent.max_steps}", Style(color=theme.accent)),
    )
    return Panel(
        Align.center(Text.assemble(cat, "\n\n", title, "  ", version, "\n", info), vertical="middle"),
        box=box.DOUBLE_EDGE,
        border_style=theme.primary,
        padding=(1, 2),
    )


def show_help():
    help_text = """[bold]Команды:[/]

  [bold]/help[/]       Показать справку
  [bold]/memory[/]     Память сессии
  [bold]/session[/]    Путь к файлу сессии
  [bold]/blueprints[/] Список архитектурных блюпринтов
  [bold]/audit[/]      Аудит техдолга
  [bold]/resolve[/] <n> Закрыть запись техдолга
  [bold]/recall[/]     Постоянная память
  [bold]/task[/]       Список активных задач
  [bold]/skills[/]     Список установленных скиллов
  [bold]/config[/]     Показать конфиг
  [bold]/providers[/]  Список доступных провайдеров
  [bold]/provider[/] <name> Переключить провайдера
  [bold]/model[/] <name> Сменить модель
  [bold]/tokens[/]     Статистика токенов
  [bold]/economy[/] on|off|profile Вкл/выкл экономию, показать профиль
  [bold]/reset[/]      Сбросить сессию
  [bold]/exit[/]       Выйти
  [bold]/undo[/]       Откатить последний коммит
  [bold]/mcp[/]        Список подключённых MCP серверов
  [bold]/architect[/]  Переключить режим архитектора (plan only)
  [bold]/commit[/]     Создать коммит (staged changes)

[bold]Провайдеры:[/] ollama (по умолч.), openai, anthropic, google, custom
  Настройка: [italic]nekocode.json[/] в корне проекта или ~/.config/nekocode/config.json

[bold]Инструменты:[/]
  • read, write, edit — работа с файлами
  • glob, grep — поиск
  • bash — запуск команд
  • agent — под-агенты (explore, plan, general)
  • task_create, task_update, task_done — задачи
  • web_fetch, web_search — веб
  • skill — загрузка скилла
  • submit_blueprint, log_tech_debt — архитектура
  • remember, recall — память

[bold]Советы:[/]
  • submit_blueprint перед написанием кода
  • log_tech_debt для компромиссов
  • /audit чтобы увидеть долги
  • /config чтобы проверить настройки"""
    return Panel(help_text, title="NekoCode Help", border_style="magenta", box=box.ROUNDED)


def show_memory(agent):
    m = agent.session["memory"]
    content = Text()
    content.append(f"Задача: {m['task'] or '-'}\n\n", style="bold")
    content.append(f"Файлы: {', '.join(m['files']) or '-'}\n", style="cyan")
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
            sc = "green" if t["status"] == "completed" else "yellow" if t["status"] == "in_progress" else "red"
            content.append(f"  [{sc}]{t['status']}[/] {t['title']} [dim]{t['id']}[/]\n")
    return Panel(content, title="Память Сессии", border_style="cyan", box=box.ROUNDED)


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
        ss = "green" if e["status"] == "resolved" else "red"
        sl = "закрыт" if e["status"] == "resolved" else "открыт"
        table.add_row(str(i), e["date"], e["file"], e["debt"], e["reason"], f"[{ss}]{sl}[/]")
    bp_count = len(BlueprintStore.list_all(agent.root))
    summary = f"[bold]Открыто:[/] {len(open_e)}  [bold]Закрыто:[/] {len(resolved_e)}  [bold]Блюпринтов:[/] {bp_count}"
    return Panel(table, title=f"Аудит Техдолга — {agent.workspace.repo_root}",
                 subtitle=summary, border_style="yellow", box=box.ROUNDED)


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
    return Panel(table, title="Архитектурные Блюпринты", border_style="blue", box=box.ROUNDED)


def show_persistent_memory(agent):
    items = agent.memory_store.list_all()
    if not items:
        return Panel(Align.center("[dim]Постоянная память пуста.[/]"))
    content = Text()
    for item in items:
        content.append(f"  {item}\n")
    return Panel(content, title="Постоянная Память (.agent/memory/)", border_style="green", box=box.ROUNDED)


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
    return Panel(table, title="Задачи", border_style="green", box=box.ROUNDED)


def show_config(agent, cfg):
    lines = [
        f"[bold]Файл:[/] {cfg.path or 'по умолчанию'}",
        f"[bold]Провайдер:[/] {cfg.get('provider', 'ollama')}",
        f"[bold]Модель:[/] {cfg.active_provider.get('model', '?')}",
        f"[bold]Approval:[/] {cfg.get('approval', 'ask')}",
        f"[bold]Max шагов:[/] {cfg.get('max_steps', 8)}",
        f"[bold]Max токенов:[/] {cfg.get('max_new_tokens', 1024)}",
        f"[bold]Temperature:[/] {cfg.get('temperature', 0.2)}",
        "",
        "[bold]Провайдеры:[/]",
    ]
    for name in cfg.provider_names:
        pcfg = cfg.data.get("providers", {}).get(name, {})
        has_key = bool(pcfg.get("api_key", "")) and pcfg["api_key"] != "${" + name.upper() + "_API_KEY}"
        key_status = "[green]✔ ключ[/]" if has_key else "[red]✖ нет ключа[/]"
        lines.append(f"  {name}: {pcfg.get('model', '?')} ({pcfg.get('base_url', pcfg.get('host', '?'))}) {key_status}")

    skills = agent.skills.list_names()
    if skills:
        lines.append(f"\n[bold]Скиллы ({len(skills)}):[/] " + ", ".join(skills))
    else:
        lines.append("\n[bold]Скиллы:[/] [dim]не установлены[/]")

    return Panel("\n".join(lines), title="Конфигурация", border_style="cyan", box=box.ROUNDED)


def show_providers(agent, cfg):
    table = Table(box=box.SIMPLE, header_style="bold")
    table.add_column("Провайдер")
    table.add_column("Модель")
    table.add_column("Статус")
    active = cfg.get("provider", "ollama")
    for name in cfg.provider_names:
        pcfg = cfg.data.get("providers", {}).get(name, {})
        model = pcfg.get("model", "?")
        has_key = bool(pcfg.get("api_key", "")) and not pcfg["api_key"].startswith("${")
        status = "[green]активен[/]" if name == active else "[dim]доступен[/]"
        if name in ("openai", "anthropic", "google") and not has_key and name != active:
            status += " [red](ключ)[/]"
        elif name == "custom" and not pcfg.get("base_url"):
            status += " [red](URL не задан)[/]"
        table.add_row(name, model, status)
    return Panel(table, title="Провайдеры", border_style="yellow", box=box.ROUNDED)


def show_skills(agent):
    skills = agent.skills.list_names()
    if not skills:
        return Panel(Align.center("[dim]Скиллы не установлены.\nПоложите SKILL.md в .claude/skills/<name>/[/]"), border_style="green", box=box.ROUNDED)
    lines = [f"[bold]Установлено скиллов:[/] {len(skills)}\n"]
    for name in skills:
        skill = agent.skills.load(name)
        if skill:
            desc = ""
            for line in skill["content"].splitlines():
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip().strip('"')
                    break
            lines.append(f"  • [bold]{name}[/] — {desc}" if desc else f"  • [bold]{name}[/]")
    return Panel("\n".join(lines), title="Скиллы", border_style="green", box=box.ROUNDED)


def display_tool_result(name, args, result):
    color_map = {
        "read": "cyan", "write": "green", "edit": "green",
        "glob": "blue", "grep": "magenta", "bash": "yellow",
        "submit_blueprint": "bright_blue", "log_tech_debt": "bright_red",
        "agent": "bright_yellow", "web_fetch": "cyan", "web_search": "cyan",
        "skill": "bright_green",
        "task_create": "green", "task_update": "green", "task_done": "green",
        "remember": "bright_green", "recall": "bright_green",
    }
    icon_map = {
        "read": "📄", "write": "✏️", "edit": "🔧",
        "glob": "📂", "grep": "🔍", "bash": "⚡",
        "submit_blueprint": "📐", "log_tech_debt": "⚠️",
        "agent": "🤖", "web_fetch": "🌐", "web_search": "🔎",
        "skill": "🧠",
        "task_create": "📝", "task_update": "📋", "task_done": "✅",
        "remember": "💾", "recall": "🔎",
    }
    color = color_map.get(name, "white")
    icon = icon_map.get(name, "🔹")
    title = Text(f" {icon} {name}", style=f"bold {color}")
    style = {"title": title, "border_style": color, "box": box.ROUNDED}
    if name == "submit_blueprint" and "saved blueprint" in result:
        body = (f"[bold]Паттерн:[/] {args.get('pattern', '')}\n"
                f"[bold]Область:[/]  {args.get('scope', '')}\n"
                f"[bold]Зачем:[/]    {args.get('rationale', '')}\n"
                f"[bold]Альтернативы:[/] {args.get('alternatives', '')}\n"
                f"[bold]Риски:[/]    {args.get('risks', '')}\n[dim]{result}[/]")
    elif name == "log_tech_debt" and "tech debt logged" in result:
        body = (f"[bold]Файл:[/] {args.get('file', '')}\n"
                f"[bold]Долг:[/] {args.get('debt', '')}\n"
                f"[bold]Причина:[/] {args.get('reason', '')}\n[dim]{result}[/]")
    elif name == "agent":
        body = (f"[bold]Тип:[/] {args.get('subagent_type', 'general-purpose')}\n"
                f"[bold]Задача:[/] {args.get('task', '')}\n[dim]{result[:800]}[/]")
    else:
        body = result[:800] + ("..." if len(result) > 800 else "")
    console.print(Panel(body, **style))


def build_arg_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="NekoCode — агент кода с блюпринтами, техдолгом и русским интерфейсом.",
    )
    parser.add_argument("prompt", nargs="*", help="Одноразовый запрос.")
    parser.add_argument("--cwd", default=".", help="Рабочая директория.")
    parser.add_argument("--config", default=None, help="Путь к nekocode.json.")
    parser.add_argument("--model", default=None, help="Модель (переопределяет конфиг).")
    parser.add_argument("--provider", default=None, choices=["ollama", "openai", "anthropic", "google", "custom", "routerai"],
                        help="Провайдер LLM.")
    parser.add_argument("--host", default=None, help="URL провайдера (Ollama / OpenAI-compat).")
    parser.add_argument("--ollama-timeout", type=int, default=None, help="Таймаут к Ollama (сек).")
    parser.add_argument("--resume", default=None, help="ID сессии для возобновления или 'latest'.")
    parser.add_argument("--approval", choices=("ask", "auto", "never"), default=None,
                        help="Политика подтверждения.")
    parser.add_argument("--max-steps", type=int, default=None, help="Максимум итераций.")
    parser.add_argument("--max-new-tokens", type=int, default=None, help="Максимум токенов.")
    parser.add_argument("--temperature", type=float, default=None, help="Температура.")
    parser.add_argument("--top-p", type=float, default=None, help="Top-p.")
    return parser


def build_agent(args):
    cfg = Config.load(cwd=args.cwd, overrides={
        "provider": args.provider,
        "approval": args.approval,
        "max_steps": args.max_steps,
        "max_new_tokens": args.max_new_tokens,
        "temperature": args.temperature,
        "top_p": args.top_p,
    })
    # Override provider model/host from CLI
    if args.model:
        prov_name = cfg.get("provider", "ollama")
        if prov_name not in cfg.data.get("providers", {}):
            cfg.data.setdefault("providers", {})[prov_name] = {}
        cfg.data["providers"][prov_name]["model"] = args.model
    if args.host and cfg.get("providers", {}).get(cfg.get("provider", "ollama")):
        cfg.data["providers"][cfg["provider"]]["host"] = args.host
    if args.ollama_timeout and cfg.get("providers", {}).get("ollama"):
        cfg.data["providers"]["ollama"]["timeout"] = args.ollama_timeout

    provider = create_provider_from_config(cfg.data)
    workspace = WorkspaceContext.build(args.cwd)
    store = SessionStore(Path(workspace.repo_root))
    mem = MemoryStore(Path(workspace.repo_root)).init()

    session_id = args.resume
    if session_id == "latest":
        session_id = store.latest()
    if session_id:
        agent = MiniAgent.from_session(
            model_client=provider, workspace=workspace, session_store=store,
            memory_store=mem, session_id=session_id,
            config=cfg.data, approval_policy=cfg.get("approval", "ask"),
            max_steps=cfg.get("max_steps", 8), max_new_tokens=cfg.get("max_new_tokens", 1024))
    else:
        agent = MiniAgent(
            model_client=provider, workspace=workspace, session_store=store,
            memory_store=mem, config=cfg.data,
            approval_policy=cfg.get("approval", "ask"),
            max_steps=cfg.get("max_steps", 8), max_new_tokens=cfg.get("max_new_tokens", 1024))
    return agent, cfg


def main(argv=None):
    _setup_console()
    args = build_arg_parser().parse_args(argv)
    agent, cfg = build_agent(args)
    provider_name = cfg.get("provider", "ollama")
    model_name = cfg.active_provider.get("model", "?")

    if args.prompt:
        prompt = " ".join(args.prompt).strip()
        if prompt:
            response = agent.ask(prompt)
            print(response)
        return 0

    theme_name = cfg.get("theme", "mimocode")
    theme = load_theme(theme_name)

    console.clear()
    console.print(build_welcome(agent, model_name, provider_name, theme))
    input(Text.assemble(("\n  Нажмите Enter чтобы начать...  ", Style(color=theme.text_muted))))

    rendered_count = 0
    first_chat_layout = True

    while True:
        if first_chat_layout:
            console.clear()
            console.print(build_header(agent, provider_name, model_name, theme))
            first_chat_layout = False
            rendered_count = 0

        hist = agent.session.get("history", [])
        for m in hist[rendered_count:]:
            console.print(render_message(m, theme))
        rendered_count = len(hist)

        console.print(build_footer(agent, theme))
        print()

        try:
            user_input = input("\033[38;2;255;106;0m❯\033[0m ")
        except (EOFError, KeyboardInterrupt):
            print()
            console.print(Panel("[yellow]До свидания![/]", border_style=theme.warning, box=box.ROUNDED))
            return 0

        if not user_input:
            continue

        cmd = user_input.split()
        base = cmd[0] if cmd else ""

        def _show_screen(content, title=None):
            console.clear()
            console.print(build_header(agent, provider_name, model_name, theme))
            if title:
                console.print(Panel(content, title=title, border_style=theme.accent, box=box.ROUNDED))
            else:
                console.print(content)
            console.print(build_footer(agent, theme))
            input(Text.assemble(("\n  Нажмите Enter...  ", Style(color=theme.text_muted))))
            nonlocal first_chat_layout
            first_chat_layout = True

        if base in ("/exit", "/quit"):
            console.print(Panel("[yellow]До свидания![/]", border_style=theme.warning, box=box.ROUNDED))
            return 0
        if base == "/help":
            _show_screen(show_help())
            continue
        if base == "/memory":
            _show_screen(show_memory(agent))
            continue
        if base == "/session":
            _show_screen(Panel(f"[dim]Сессия:[/] {agent.session_path}", border_style=theme.border, box=box.ROUNDED))
            continue
        if base == "/blueprints":
            _show_screen(show_blueprints(agent))
            continue
        if base == "/audit":
            _show_screen(audit_tech_debt(agent))
            continue
        if base == "/recall":
            _show_screen(show_persistent_memory(agent))
            continue
        if base == "/task":
            _show_screen(show_tasks(agent))
            continue
        if base == "/skills":
            _show_screen(show_skills(agent))
            continue
        if base == "/config":
            _show_screen(show_config(agent, cfg))
            continue
        if base == "/providers":
            _show_screen(show_providers(agent, cfg))
            continue
        if base == "/tokens":
            _show_screen(agent.tokens_dashboard())
            continue
        if base == "/theme":
            available = list_themes()
            if len(cmd) >= 2:
                name = cmd[1]
                if name in available:
                    theme = load_theme(name)
                    theme_name = name
                    cfg.set("theme", name)
                    cfg.save()
                    _show_screen(Panel(f"Тема: {name}", border_style=theme.success, box=box.ROUNDED))
                else:
                    avail_str = ", ".join(available)
                    _show_screen(Panel(f"Тема '{name}' не найдена.\nДоступны: {avail_str}", border_style=theme.error, box=box.ROUNDED))
            else:
                avail_str = ", ".join(available)
                _show_screen(Panel(f"Текущая: {theme_name}\nДоступны: {avail_str}\n\n/theme <имя>", border_style=theme.accent, box=box.ROUNDED))
            continue
        if base == "/economy":
            if len(cmd) >= 2 and cmd[1] == "on":
                agent.economy_enabled = True
            elif len(cmd) >= 2 and cmd[1] == "off":
                agent.economy_enabled = False
            elif len(cmd) >= 2 and cmd[1] == "profile":
                budget = agent.token_budget
                lines = [
                    f"Профиль: {agent._provider_name()}",
                    f"Общий бюджет: {budget.total:,} токенов",
                    f"System: {budget.system:,}",
                    f"User msg: {budget.user_msg:,}",
                    f"History: {budget.history:,}",
                    f"Reserve: {budget.reserve:,}",
                    f"Статус: {'включена' if agent.economy_enabled else 'выключена'}",
                ]
                _show_screen(Panel("\n".join(lines), title="Token Economy", border_style=theme.accent, box=box.ROUNDED))
            else:
                status = "включена" if agent.economy_enabled else "выключена"
                _show_screen(Panel(f"Экономия: {status}. /economy on|off|profile", border_style=theme.border, box=box.ROUNDED))
            continue
        if base == "/undo":
            from nekocode.agent import tool_git_undo
            result = tool_git_undo(agent, {})
            _show_screen(Panel(result, border_style=theme.warning, box=box.ROUNDED))
            continue
        if base == "/architect":
            agent.architect_mode = not agent.architect_mode
            status = "включён" if agent.architect_mode else "выключен"
            _show_screen(Panel(f"Architect mode {status}", border_style=theme.accent, box=box.ROUNDED))
            continue
        if base == "/mcp":
            if agent.mcp_manager:
                _show_screen(Panel(agent.mcp_manager.summary(), title="MCP Servers", border_style=theme.accent, box=box.ROUNDED))
            else:
                _show_screen(Panel("MCP не настроен", border_style=theme.warning, box=box.ROUNDED))
            continue
        if base == "/commit":
            import subprocess
            r = subprocess.run(["git", "diff", "--cached"], cwd=agent.root, capture_output=True, text=True, timeout=5)
            if not r.stdout.strip():
                _show_screen(Panel("Нет застейдженных изменений. Добавьте файлы через git add.", border_style=theme.warning, box=box.ROUNDED))
            else:
                _show_screen(Panel("Застейдженные файлы готовы к коммиту. Используйте git_commit в диалоге с агентом.", border_style=theme.success, box=box.ROUNDED))
            continue
        if base == "/reset":
            agent.reset()
            continue
        if base == "/provider" and len(cmd) >= 2:
            new_provider = cmd[1]
            if new_provider in cfg.provider_names:
                old = cfg.get("provider", "ollama")
                cfg.set("provider", new_provider)
                pdata = cfg.data.get("providers", {}).get(new_provider, {})
                model_name2 = pdata.get("model", "?")
                from nekocode.providers import create_provider_from_config
                agent.model_client = create_provider_from_config(cfg.data)
                provider_name = new_provider
                model_name = model_name2
                _show_screen(Panel(f"Провайдер: {old} → {new_provider} (модель: {model_name2})", border_style=theme.success, box=box.ROUNDED))
            else:
                _show_screen(Panel(f"Неизвестный провайдер: {new_provider}", border_style=theme.error, box=box.ROUNDED))
            continue
        if base == "/model" and len(cmd) >= 2:
            new_model = cmd[1]
            pname = cfg.get("provider", "ollama")
            if pname in cfg.data.get("providers", {}):
                cfg.data["providers"][pname]["model"] = new_model
                from nekocode.providers import create_provider_from_config
                agent.model_client = create_provider_from_config(cfg.data)
                agent.max_new_tokens = int(cfg.get("max_new_tokens", 1024))
                model_name = new_model
                _show_screen(Panel(f"Модель: {new_model}", border_style=theme.success, box=box.ROUNDED))
            else:
                _show_screen(Panel(f"Не удалось сменить модель для {pname}", border_style=theme.error, box=box.ROUNDED))
            continue
        if base == "/resolve" and len(cmd) >= 2:
            try:
                idx = int(cmd[1])
                result = TechDebtLedger.resolve(agent.root, idx)
                _show_screen(Panel(result, border_style=theme.success, box=box.ROUNDED))
            except (ValueError, IndexError):
                _show_screen(Panel("Использование: /resolve <номер_записи>", border_style=theme.error, box=box.ROUNDED))
            continue

        # ── Chat message (streaming) ──
        buffer = ""
        stream_panel = Panel(
            Markdown(""),
            title=Text.assemble((" NekoCode ", Style(color=theme.accent, bold=True))),
            border_style=theme.accent, box=box.ROUNDED, padding=(0, 1),
        )
        try:
            with Live(stream_panel, console=console, refresh_per_second=12, vertical_overflow="visible") as live:
                for chunk in agent.ask_stream(user_input):
                    buffer += chunk
                    live.update(Panel(
                        Markdown(buffer),
                        title=Text.assemble((" NekoCode ", Style(color=theme.accent, bold=True))),
                        border_style=theme.accent, box=box.ROUNDED, padding=(0, 1),
                    ))
        except GeneratorExit:
            pass
