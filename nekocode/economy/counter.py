"""Token counting — estimate-based, no external deps."""

from nekocode.economy.models import ProviderProfile


class TokenCounter:
    def __init__(self, provider=None):
        self.provider = provider or "ollama"
        self.ratio = ProviderProfile.chars_per_token(self.provider)

    def estimate(self, text):
        if not text:
            return 0
        chars = len(str(text))
        return max(1, int(chars / self.ratio) + 1)

    def count_messages(self, messages):
        total = 0
        for msg in messages:
            total += self.estimate(msg.get("content", ""))
            for k, v in msg.get("args", {}).items():
                total += self.estimate(str(v))
        return total

    def count_prompt(self, system_prompt, user_msg, history_text):
        return self.estimate(system_prompt) + self.estimate(user_msg) + self.estimate(history_text)
