"""NekoCode CLI — rich terminal UI with Russian locale, cat art, slash commands."""

import argparse
import os
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
    BlueprintStore, MiniAgent, SessionStore,
    TechDebtLedger, WorkspaceContext, MemoryStore,
)
from nekocode.config import Config
from nekocode.providers import create_provider_from_config

console = Console()

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


def build_welcome(agent, model, provider_name):
    debt_count = len(TechDebtLedger.entries(agent.root))
    bp_count = len(BlueprintStore.list_all(agent.root))
    mem_count = len(agent.memory_store.list_all())

    info = Table.grid(padding=(0, 2))
    info.add_column(style="bold")
    info.add_column()
    info.add_column(style="bold")
    info.add_column()
    info.add_row("Директория", f"[cyan]{middle(agent.workspace.cwd, 40)}[/]",
                 "Модель", f"[green]{model}[/]")
    info.add_row("Ветка", f"[magenta]{agent.workspace.branch}[/]",
                 "Провайдер", f"[yellow]{provider_name}[/]")
    info.add_row("Подтвержд.", f"[bold]{agent.approval_policy}[/]", "Шаги", f"[cyan]{agent.max_steps}[/]")

    stats = Table.grid(padding=(0, 2))
    stats.add_column()
    stats.add_column()
    stats.add_column()
    stats.add_row(f"[bold yellow]Долг:[/] {debt_count}",
                  f"[bold blue]Блюпринтов:[/] {bp_count}",
                  f"[bold green]Воспоминаний:[/] {mem_count}")

    cat = Text(CAT_ART, style="bright_yellow")
    title = Text(f"NEKOCODE v0.5", style="bold white on blue", no_wrap=True)
    layout = Panel(
        Align.center(Text.assemble(cat, "\n\n", title), vertical="middle"),
        box=box.DOUBLE_EDGE,
        border_style="bright_blue",
        padding=(1, 2),
    )
    return layout


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
  [bold]/reset[/]      Сбросить сессию
  [bold]/exit[/]       Выйти

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
    parser.add_argument("--provider", default=None, choices=["ollama", "openai", "anthropic", "google", "custom"],
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
    if args.model and cfg.get("providers", {}).get(cfg.get("provider", "ollama")):
        cfg.data["providers"][cfg["provider"]]["model"] = args.model
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
    args = build_arg_parser().parse_args(argv)
    agent, cfg = build_agent(args)
    provider_name = cfg.get("provider", "ollama")
    model_name = cfg.active_provider.get("model", "?")

    console.print()
    console.print(build_welcome(agent, model=model_name, provider_name=provider_name))
    console.print()

    if args.prompt:
        prompt = " ".join(args.prompt).strip()
        if prompt:
            response = agent.ask(prompt)
            console.print(Panel(Markdown(response), title="Ответ", border_style="green", box=box.ROUNDED))
        return 0

    while True:
        try:
            user_input = Prompt.ask("\n[bold bright_blue]❯[/] [bold]nekocode[/]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]До свидания![/]")
            return 0

        if not user_input:
            continue

        cmd = user_input.split()
        base = cmd[0] if cmd else ""

        if base in ("/exit", "/quit"):
            console.print("[yellow]До свидания![/]")
            return 0
        if base == "/help":
            console.print(show_help())
            continue
        if base == "/memory":
            console.print(show_memory(agent))
            continue
        if base == "/session":
            console.print(f"[dim]Сессия:[/] [cyan]{agent.session_path}[/]")
            continue
        if base == "/blueprints":
            console.print(show_blueprints(agent))
            continue
        if base == "/audit":
            console.print(audit_tech_debt(agent))
            continue
        if base == "/recall":
            console.print(show_persistent_memory(agent))
            continue
        if base == "/task":
            console.print(show_tasks(agent))
            continue
        if base == "/skills":
            console.print(show_skills(agent))
            continue
        if base == "/config":
            console.print(show_config(agent, cfg))
            continue
        if base == "/providers":
            console.print(show_providers(agent, cfg))
            continue
        if base == "/reset":
            agent.reset()
            console.print("[yellow]Сессия сброшена.[/]")
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
                console.print(f"[green]Провайдер: {old} → {new_provider} (модель: {model_name2})[/]")
            else:
                console.print(f"[red]Неизвестный провайдер: {new_provider}[/]")
            continue
        if base == "/model" and len(cmd) >= 2:
            new_model = cmd[1]
            pname = cfg.get("provider", "ollama")
            if pname in cfg.data.get("providers", {}):
                cfg.data["providers"][pname]["model"] = new_model
                from nekocode.providers import create_provider_from_config
                agent.model_client = create_provider_from_config(cfg.data)
                agent.max_new_tokens = int(cfg.get("max_new_tokens", 1024))
                console.print(f"[green]Модель: {new_model}[/]")
            else:
                console.print(f"[red]Не удалось сменить модель для {pname}[/]")
            continue
        if base == "/resolve" and len(cmd) >= 2:
            try:
                idx = int(cmd[1])
                result = TechDebtLedger.resolve(agent.root, idx)
                console.print(Panel(f"[green]{result}[/]", border_style="green", box=box.ROUNDED))
            except (ValueError, IndexError):
                console.print("[red]Использование: /resolve <номер_записи>[/]")
            continue

        response = agent.ask(user_input)
        console.print(Panel(Markdown(response), title="Ответ", border_style="green", box=box.ROUNDED))
