"""LLM provider implementations: Ollama, OpenAI-compatible, Anthropic, Google, Custom."""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class BaseProvider:
    name = "base"

    def __init__(self, config=None):
        self.config = config or {}

    def complete(self, prompt, max_new_tokens):
        raise NotImplementedError

    @property
    def model(self):
        return self.config.get("model", "")

    @property
    def timeout(self):
        return int(self.config.get("timeout", 60))


# ── Ollama ────────────────────────────────────────────────────────────
class OllamaProvider(BaseProvider):
    name = "ollama"

    def complete(self, prompt, max_new_tokens):
        host = self.config.get("host", "http://127.0.0.1:11434").rstrip("/")
        payload = {
            "model": self.model, "prompt": prompt, "stream": False, "raw": False, "think": False,
            "options": {"num_predict": max_new_tokens, "temperature": self.config.get("temperature", 0.2),
                        "top_p": self.config.get("top_p", 0.9)},
        }
        req = urllib.request.Request(
            host + "/api/generate", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Ollama HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Cannot reach Ollama. Is `ollama serve` running?\n"
                               f"Host: {host}\nModel: {self.model}") from exc
        if data.get("error"):
            raise RuntimeError(f"Ollama error: {data['error']}")
        return data.get("response", "")


# ── OpenAI-compatible ──────────────────────────────────────────────────
class OpenAIProvider(BaseProvider):
    name = "openai"

    def complete(self, prompt, max_new_tokens):
        base = self.config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        api_key = self.config.get("api_key", os.environ.get("OPENAI_API_KEY", ""))
        if not api_key:
            raise RuntimeError("OpenAI API key not set. Set OPENAI_API_KEY env var or configure nekocode.json.")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_new_tokens,
            "temperature": self.config.get("temperature", 0.2),
            "top_p": self.config.get("top_p", 0.9),
        }
        req = urllib.request.Request(
            f"{base}/chat/completions", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach OpenAI API at {base}: {exc}") from exc
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"OpenAI returned no choices: {json.dumps(data, indent=2)[:500]}")
        return choices[0].get("message", {}).get("content", "")


# ── Anthropic ──────────────────────────────────────────────────────────
class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def complete(self, prompt, max_new_tokens):
        base = self.config.get("base_url", "https://api.anthropic.com/v1").rstrip("/")
        api_key = self.config.get("api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
        if not api_key:
            raise RuntimeError("Anthropic API key not set. Set ANTHROPIC_API_KEY env var or configure nekocode.json.")
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_new_tokens,
            "temperature": self.config.get("temperature", 0.2),
        }
        req = urllib.request.Request(
            f"{base}/messages", data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach Anthropic API at {base}: {exc}") from exc
        content = data.get("content", [])
        if not content:
            raise RuntimeError(f"Anthropic returned no content: {json.dumps(data, indent=2)[:500]}")
        return "".join(block.get("text", "") for block in content if block.get("type") == "text")


# ── Google Gemini ──────────────────────────────────────────────────────
class GoogleProvider(BaseProvider):
    name = "google"

    def complete(self, prompt, max_new_tokens):
        base = self.config.get("base_url", "https://generativelanguage.googleapis.com").rstrip("/")
        api_key = self.config.get("api_key", os.environ.get("GOOGLE_API_KEY", ""))
        if not api_key:
            raise RuntimeError("Google API key not set. Set GOOGLE_API_KEY env var or configure nekocode.json.")
        model = self.model or "gemini-2.0-flash"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_new_tokens,
                "temperature": self.config.get("temperature", 0.2),
                "topP": self.config.get("top_p", 0.9),
            },
        }
        url = f"{base}/v1beta/models/{model}:generateContent?key={api_key}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Google HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach Google API at {url}: {exc}") from exc
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Google returned no candidates: {json.dumps(data, indent=2)[:500]}")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)


# ── Custom HTTP API ────────────────────────────────────────────────────
class CustomProvider(BaseProvider):
    name = "custom"

    def complete(self, prompt, max_new_tokens):
        base = self.config.get("base_url", "")
        if not base:
            raise RuntimeError("Custom provider: base_url is required")
        base = base.rstrip("/")
        api_key = self.config.get("api_key", "")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": self.model or "default",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_new_tokens,
            "temperature": self.config.get("temperature", 0.2),
        }
        req = urllib.request.Request(
            f"{base}/chat/completions", data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Custom API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach custom API at {base}: {exc}") from exc
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"Custom API returned no choices: {json.dumps(data, indent=2)[:500]}")
        return choices[0].get("message", {}).get("content", "")


# ── Registry ───────────────────────────────────────────────────────────
PROVIDERS = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "custom": CustomProvider,
}


def get_provider(name, config=None):
    cls = PROVIDERS.get(name)
    if cls is None:
        available = ", ".join(PROVIDERS)
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    return cls(config=config or {})


def create_provider_from_config(config):
    provider_name = config.get("provider", "ollama")
    provider_cfg = config.get("providers", {}).get(provider_name, {})
    merged = {**provider_cfg, "temperature": config.get("temperature", 0.2),
              "top_p": config.get("top_p", 0.9)}
    return get_provider(provider_name, merged)
