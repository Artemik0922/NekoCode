"""Config system for NekoCode — JSON-based with env var substitution."""

import json
import os
from pathlib import Path


def _resolve_env(text):
    if not isinstance(text, str):
        return text
    return os.path.expandvars(text)


def _resolve_env_recursive(obj):
    if isinstance(obj, str):
        return _resolve_env(obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_recursive(i) for i in obj]
    return obj


DEFAULT_CONFIG = {
    "provider": "ollama",
    "providers": {
        "ollama": {
            "model": "qwen3.5:4b",
            "host": "http://127.0.0.1:11434",
            "timeout": 300,
        },
        "openai": {
            "api_key": "${OPENAI_API_KEY}",
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
            "timeout": 60,
        },
        "anthropic": {
            "api_key": "${ANTHROPIC_API_KEY}",
            "model": "claude-sonnet-5",
            "base_url": "https://api.anthropic.com/v1",
            "timeout": 60,
        },
        "google": {
            "api_key": "${GOOGLE_API_KEY}",
            "model": "gemini-2.0-flash",
            "base_url": "https://generativelanguage.googleapis.com",
            "timeout": 60,
        },
        "custom": {
            "api_key": "${CUSTOM_API_KEY}",
            "model": "",
            "base_url": "",
            "timeout": 60,
        },
    },
    "approval": "ask",
    "max_steps": 8,
    "max_new_tokens": 1024,
    "temperature": 0.2,
    "top_p": 0.9,
    "theme": "mimocode",
    "skills_dirs": [".claude/skills"],
    "hooks": {
        "before_tool": [],
        "after_tool": [],
        "before_message": [],
        "after_message": [],
    },
}

CONFIG_FILENAME = "nekocode.json"


def find_config(cwd=None):
    cwd = Path(cwd or os.getcwd()).resolve()
    candidates = [
        cwd / CONFIG_FILENAME,
        Path.home() / ".config" / "nekocode" / "config.json",
        Path.home() / ".nekocoderc",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


class Config:
    def __init__(self, path=None, overrides=None):
        self.path = path
        self.data = dict(DEFAULT_CONFIG)
        if path:
            self._load(path)
        if overrides:
            self._apply_overrides(overrides)

    @classmethod
    def load(cls, cwd=None, overrides=None):
        path = find_config(cwd)
        cfg = cls(path=path, overrides=overrides)
        cfg._resolve()
        return cfg

    def _load(self, path):
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            self._deep_merge(raw)
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"config error in {path}: {exc}") from exc

    def _deep_merge(self, source):
        for key, val in source.items():
            if key in self.data and isinstance(self.data[key], dict) and isinstance(val, dict):
                self.data[key].update(val)
            else:
                self.data[key] = val

    def _apply_overrides(self, overrides):
        for key, val in overrides.items():
            if val is not None:
                self.data[key] = val

    def _resolve(self):
        self.data = _resolve_env_recursive(self.data)

    def save(self, path=None):
        path = Path(path or self.path or CONFIG_FILENAME)
        path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        self.path = path
        return path

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __getitem__(self, key):
        return self.data[key]

    def __contains__(self, key):
        return key in self.data

    @property
    def active_provider(self):
        name = self.data.get("provider", "ollama")
        providers = self.data.get("providers", {})
        base = providers.get(name, {})
        return {"name": name, **base}

    @property
    def provider_names(self):
        return list(self.data.get("providers", {}).keys())

    @property
    def provider_config(self, name=None):
        name = name or self.data.get("provider", "ollama")
        return self.data.get("providers", {}).get(name, {})

    def set_provider(self, name, **kwargs):
        if name not in self.data.get("providers", {}):
            self.data.setdefault("providers", {})[name] = {}
        self.data["providers"][name].update(kwargs)
        self.data["provider"] = name

    def set(self, key, value):
        self.data[key] = value

    def to_cli_args(self):
        p = self.active_provider
        return {
            "model": p.get("model", ""),
            "host": p.get("host", ""),
            "approval": self.data.get("approval", "ask"),
            "max_steps": self.data.get("max_steps", 8),
            "max_new_tokens": self.data.get("max_new_tokens", 1024),
            "temperature": self.data.get("temperature", 0.2),
            "top_p": self.data.get("top_p", 0.9),
        }
