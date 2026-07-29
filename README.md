# NekoCode

> Открытый агент для написания кода с архитектурными блюпринтами, Git-интеграцией, MCP, RepoMap, техдолгом, файловой памятью и поддержкой любых LLM-провайдеров.

NekoCode — это CLI-агент в стиле MiMo, вдохновлённый Claude Code от Anthropic. Он не просто пишет код: документирует **почему** код написан именно так, отслеживает компромиссы, помнит контекст между сессиями и работает с любой LLM — от локальной Ollama до облачных OpenAI, Anthropic, Google и RouterAI.

## Возможности

**Мульти-провайдер** — Ollama, OpenAI, Anthropic Claude, Google Gemini, RouterAI, любые OpenAI-совместимые API (TogetherAI, Groq, DeepSeek) и кастомные эндпоинты. Переключение между провайдерами без перезапуска.

**Стриминг ответов** — токены отображаются в реальном времени через Rich `Live`. Markdown парсится и рендерится по мере поступления.

**Git интеграция** — `git_status`, `git_diff`, `git_commit` (с генерацией сообщения), `git_create_pr`, `git_undo`. Команды `/commit` и `/undo` в TUI.

**MCP (Model Context Protocol)** — подключение внешних серверов инструментов через `mcp.json`. Динамическое добавление/удаление серверов через `/mcp`.

**RepoMap** — AST-анализ репозитория: схлопывание несущественных нод, детальные сигнатуры для ключевых файлов. Автоматически включается в system prompt.

**Auto-context** — при старте сессии сканирует проект и подбирает релевантные файлы (по git diff, недавним изменениям, ключевым файлам).

**Architect mode** — режим планирования без кода. Включается `/architect` или `--architect-mode`. Агент только анализирует и предлагает решение.

**Система тем** — переключение стилей через `/theme`. Встроенные темы: `mimocode` (оранжевый MiMo), `catppuccin`, `nord`, `onedark`. Тема задаётся в `nekocode.json`.

**Архитектурные блюпринты** — `submit_blueprint` сохраняет ADR в `.agent/blueprints/` с паттерном, областью, обоснованием, альтернативами и рисками.

**Техдолг** — `log_tech_debt` пишет компромиссы в `.tech-debt-log.md`. Аудит и разрешение через `/audit` и `/resolve`.

**Файловая память** — `.agent/memory/` с типами `user`, `project`, `feedback`, `reference`. Сохраняется между сессиями.

**Token Economy** — приоритезация контекста, компрессия истории, бюджеты на system/user/history/reserve. Просмотр через `/economy profile` или `/tokens`.

**Под-агенты** — `explore` (только поиск), `plan` (архитектура), `general-purpose` (исследование), `worker` (автономное выполнение).

**Управление задачами** — `task_create/update/done` для декомпозиции работы.

**Веб-инструменты** — `web_fetch` (загрузка URL), `web_search` (поиск через DuckDuckGo).

**Скиллы** — загрузка SKILL.md из `.claude/skills/<name>/` через инструмент `skill`.

**18 инструментов** + 5 git-инструментов — `read`, `write`, `edit`, `glob`, `grep`, `bash`, `agent`, `web_fetch`, `web_search`, `skill`, `task_create/update/done`, `submit_blueprint`, `log_tech_debt`, `remember`, `recall`, `git_status`, `git_diff`, `git_commit`, `git_create_pr`, `git_undo`.

## Быстрый старт

```bash
# Установка
pip install rich

# Запуск с локальной Ollama
ollama serve
ollama pull qwen3.5:4b
nekocode

# Запуск с OpenAI
set OPENAI_API_KEY=sk-...
nekocode --provider openai --model gpt-4o

# Запуск с Anthropic Claude
set ANTHROPIC_API_KEY=sk-ant-...
nekocode --provider anthropic --model claude-sonnet-5

# Запуск с RouterAI
set ROUTERAI_API_KEY=...
nekocode --provider routerai

# Запуск с Google Gemini
set GOOGLE_API_KEY=...
nekocode --provider google --model gemini-2.0-flash
```

## Конфигурация

Создайте `nekocode.json` в корне проекта или в `~/.config/nekocode/config.json`:

```json
{
  "provider": "openai",
  "theme": "mimocode",
  "architect_mode": false,
  "skip_custom_prompt": false,
  "custom_instructions": "",
  "providers": {
    "ollama": {
      "model": "qwen3.5:4b",
      "host": "http://127.0.0.1:11434"
    },
    "openai": {
      "api_key": "${OPENAI_API_KEY}",
      "model": "gpt-4o",
      "base_url": "https://api.openai.com/v1"
    },
    "anthropic": {
      "api_key": "${ANTHROPIC_API_KEY}",
      "model": "claude-sonnet-5",
      "base_url": "https://api.anthropic.com/v1"
    },
    "google": {
      "api_key": "${GOOGLE_API_KEY}",
      "model": "gemini-2.0-flash",
      "base_url": "https://generativelanguage.googleapis.com"
    },
    "routerai": {
      "api_key": "${ROUTERAI_API_KEY}",
      "model": "",
      "base_url": "https://llm-router.askthem.net/api/v1"
    },
    "custom": {
      "api_key": "${CUSTOM_API_KEY}",
      "model": "",
      "base_url": ""
    }
  },
  "mcp": {
    "enabled": true,
    "auto_connect": true,
    "servers": {}
  },
  "auto_context": {
    "enabled": true,
    "max_files": 5,
    "max_chars": 3000
  },
  "approval": "ask",
  "max_steps": 8,
  "max_new_tokens": 1024,
  "temperature": 0.2,
  "top_p": 0.9,
  "ollama_timeout": 300,
  "skills_dirs": [".claude/skills"]
}
```

Переменные `${VAR}` подставляются из окружения. Приоритет: CLI-флаги → `nekocode.json` в проекте → `~/.config/nekocode/config.json` → дефолты.

## CLI

```bash
nekocode [prompt...] [--flags]
```

| Флаг | По умолч. | Описание |
|------|-----------|----------|
| `--provider` | `ollama` | `ollama`, `openai`, `anthropic`, `google`, `routerai`, `custom` |
| `--model` | из конфига | Модель провайдера |
| `--host` | из конфига | URL провайдера |
| `--cwd` | `.` | Рабочая директория |
| `--approval` | `ask` | `ask`, `auto`, `never` |
| `--max-steps` | `8` | Макс. итераций на запрос |
| `--max-new-tokens` | `1024` | Макс. токенов в ответе |
| `--temperature` | `0.2` | Температура семплирования |
| `--top-p` | `0.9` | Top-p семплирования |
| `--resume` | — | ID сессии или `latest` |
| `--config` | — | Путь к конфигу |
| `--ollama-timeout` | `300` | Таймаут запроса к Ollama (сек) |
| `--architect-mode` | `false` | Режим архитектора |
| `--skip-custom-prompt` | `false` | Пропустить `.claude/system-prompt.md` |
| `prompt` | — | Одноразовый запрос (без интерактива) |

## Команды

| Команда | Описание |
|---------|----------|
| `/help` | Справка |
| `/memory` | Память текущей сессии |
| `/blueprints` | Список архитектурных блюпринтов |
| `/audit` | Аудит техдолга |
| `/resolve <n>` | Закрыть запись техдолга |
| `/recall` | Постоянная файловая память |
| `/task` | Список активных задач |
| `/skills` | Установленные скиллы |
| `/config` | Текущая конфигурация |
| `/providers` | Доступные провайдеры |
| `/provider <name>` | Переключить провайдера |
| `/model <name>` | Сменить модель |
| `/theme [name]` | Просмотр/смена темы |
| `/architect [on\|off]` | Переключить режим архитектора |
| `/commit` | Git commit с авто-сообщением |
| `/undo` | Откатить последний git commit (soft) |
| `/mcp [on\|off\|list]` | Управление MCP серверами |
| `/tokens` | Статистика токенов сессии |
| `/economy [on\|off\|profile]` | Управление Token Economy |
| `/session` | Путь к файлу сессии |
| `/reset` | Сбросить сессию |
| `/exit` | Выход |

## Инструменты агента

| Инструмент | Риск | Описание |
|-----------|------|----------|
| `read` | нет | Чтение файла |
| `write` | да | Запись файла |
| `edit` | да | Замена текста по точному совпадению |
| `list_files` | нет | Список файлов в директории |
| `glob` | нет | Поиск файлов по glob-паттерну |
| `grep` | нет | Поиск по содержимому (rg) |
| `bash` | да | Запуск shell-команды |
| `agent` | нет | Делегирование под-агенту |
| `web_fetch` | нет | Загрузка URL |
| `web_search` | нет | Поиск в DuckDuckGo |
| `skill` | нет | Загрузка скилла |
| `task_create` | нет | Создать задачу |
| `task_update` | нет | Обновить статус задачи |
| `task_done` | нет | Завершить задачу |
| `submit_blueprint` | нет | Записать архитектурное решение |
| `log_tech_debt` | нет | Записать техдолг |
| `remember` | нет | Сохранить в постоянную память |
| `recall` | нет | Загрузить из постоянной памяти |
| `git_status` | нет | Статус git репозитория |
| `git_diff` | нет | Просмотр незакоммиченных изменений |
| `git_commit` | да | Создать commit с авто-сообщением |
| `git_create_pr` | да | Создать Pull Request |
| `git_undo` | да | Soft undo последнего коммита |

## Архитектура проекта

```
nekocode/
├── __init__.py          # Версия, экспорт
├── __main__.py          # python -m nekocode
├── agent.py             # Ядро агента: цикл вызовов, инструменты, парсинг
├── cli.py               # Rich CLI, русская локализация, темы, slash-команды
├── prompts.py           # Генерация system prompt (адаптация Claude Code)
├── providers.py         # Провайдеры LLM: Ollama, OpenAI, Anthropic, Google, RouterAI, Custom
├── config.py            # Конфиг (nekocode.json, env-подстановка, провайдеры)
├── theme.py             # Система тем (Theme dataclass, load/save, встроенные темы)
├── mcp.py               # MCP клиент (Model Context Protocol серверы)
├── auto_context.py      # Авто-контекст: сканирование проекта, подбор файлов
├── repo_map.py          # RepoMap: AST-анализ репозитория
├── memory.py            # Файловая система памяти (MEMORY.md + .agent/memory/)
├── economy/             # Token Economy (приоритезация, компрессия, бюджеты)
│   ├── __init__.py
│   ├── window.py        # ContextWindow, assemble, budget
│   ├── compress.py      # История: дедупликация, схлопывание повторений
│   └── priority.py      # Приоритезация записей в истории
├── themes/              # JSON-темы оформления
│   ├── mimocode.json
│   ├── catppuccin.json
│   ├── nord.json
│   └── onedark.json
```

## Сравнение с Claude Code

| Фича | Claude Code | NekoCode |
|------|-------------|----------|
| Цена | Проприетарный, платный | Открытый, бесплатный |
| Модели | Только Claude | Любые (Ollama, OpenAI, Anthropic, Google, RouterAI...) |
| Локальность | Нет (облачный Claude) | Да (Ollama — полностью локально) |
| Стриминг | Да | Да (Rich Live + Markdown) |
| Git интеграция | Базовая | git_status, git_diff, git_commit (авто-сообщение), git_undo, git_create_pr |
| MCP | Да | Да (подключение серверов, /mcp) |
| RepoMap | Да | Да (AST-анализ, схлопывание нод) |
| Auto-context | Да | Да (git diff + ключевые файлы) |
| Architect mode | Да | Да (/architect) |
| Темы оформления | Нет | 4 темы (mimocode, catppuccin, nord, onedark) + /theme |
| Token Economy | Нет | Бюджеты, компрессия, приоритезация |
| Архитектурные ADR | Нет | `submit_blueprint` |
| Техдолг | Нет | `log_tech_debt`, `/audit`, `/resolve` |
| Файловая память | MEMORY.md + типы user/project/feedback/reference | Аналог |
| Под-агенты | Explore, Plan, general-purpose | Аналог |
| Задачи | TaskCreate/Update/Done | Аналог |
| Инструменты | Read, Edit, Write, Bash, Glob, Grep, Agent | Аналог + web_fetch, web_search |
| Скиллы | Skill tool | Аналог |
| Язык интерфейса | Английский | Русский |
| Подтверждение операций | Permission modes | `ask`, `auto`, `never` |

## Лицензия

Apache-2.0
