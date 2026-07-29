# NekoCode

> Открытый агент для написания кода с архитектурными блюпринтами, учётом техдолга, файловой памятью и поддержкой любых LLM-провайдеров.

NekoCode — это CLI-агент, вдохновлённый Claude Code от Anthropic. Он не просто пишет код: документирует **почему** код написан именно так, отслеживает компромиссы, помнит контекст между сессиями и работает с любой LLM — от локальной Ollama до облачных OpenAI, Anthropic и Google.

## Возможности

**Мульти-провайдер** — Ollama, OpenAI, Anthropic Claude, Google Gemini, любые OpenAI-совместимые API (TogetherAI, Groq, DeepSeek) и кастомные эндпоинты. Переключение между провайдерами без перезапуска.

**Архитектурные блюпринты** — `submit_blueprint` сохраняет ADR в `.agent/blueprints/` с паттерном, областью, обоснованием, альтернативами и рисками.

**Техдолг** — `log_tech_debt` пишет компромиссы в `.tech-debt-log.md`. Аудит и разрешение через `/audit` и `/resolve`.

**Файловая память** — `.agent/memory/` с типами `user`, `project`, `feedback`, `reference`. Сохраняется между сессиями. Аналог MEMORY.md из Claude Code.

**Под-агенты** — `explore` (только поиск), `plan` (архитектура), `general-purpose` (исследование), `worker` (автономное выполнение).

**Управление задачами** — `task_create/update/done` для декомпозиции работы.

**Веб-инструменты** — `web_fetch` (загрузка URL), `web_search` (поиск через DuckDuckGo).

**Скиллы** — загрузка SKILL.md из `.claude/skills/<name>/` через инструмент `skill`.

**Контекст** — дедупликация read-запросов, авто-ограничение истории, защита от повторов.

**18 инструментов** — `read`, `write`, `edit`, `glob`, `grep`, `bash`, `agent`, `web_fetch`, `web_search`, `skill`, `task_create/update/done`, `submit_blueprint`, `log_tech_debt`, `remember`, `recall`.

## Быстрый старт

```bash
# Установка
pip install rich

# Запуск с локальной Ollama
ollama serve
ollama pull qwen3.5:4b
nekocode

# Запуск с OpenAI
export OPENAI_API_KEY=sk-...
nekocode --provider openai --model gpt-4o

# Запуск с Anthropic Claude
export ANTHROPIC_API_KEY=sk-ant-...
nekocode --provider anthropic --model claude-sonnet-5
```

## Конфигурация

Создайте `nekocode.json` в корне проекта или в `~/.config/nekocode/config.json`:

```json
{
  "provider": "openai",
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
    "custom": {
      "api_key": "${CUSTOM_API_KEY}",
      "model": "",
      "base_url": ""
    }
  },
  "approval": "ask",
  "max_steps": 8,
  "max_new_tokens": 1024,
  "temperature": 0.2,
  "top_p": 0.9,
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
| `--provider` | `ollama` | `ollama`, `openai`, `anthropic`, `google`, `custom` |
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

## Архитектура проекта

```
nekocode/
├── __init__.py          # Версия, экспорт
├── __main__.py          # python -m nekocode
├── agent.py             # Ядро агента: цикл вызовов, инструменты, парсинг
├── cli.py               # Rich CLI, русская локализация, slash-команды
├── prompts.py           # Генерация system prompt (адаптация Claude Code)
├── memory.py            # Файловая система памяти (MEMORY.md + .agent/memory/)
├── config.py            # Конфиг (nekocode.json, env-подстановка, провайдеры)
└── providers.py         # Провайдеры LLM: Ollama, OpenAI, Anthropic, Google, Custom
```

## Сравнение с Claude Code

| Фича | Claude Code | NekoCode |
|------|-------------|----------|
| Цена | Проприетарный, платный | Открытый, бесплатный |
| Модели | Только Claude | Любые (Ollama, OpenAI, Anthropic, Google...) |
| Локальность | Нет (облачный Claude) | Да (Ollama — полностью локально) |
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
