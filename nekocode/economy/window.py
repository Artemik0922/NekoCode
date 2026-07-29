"""ContextWindow — smart prompt assembly with priority-based packing."""

from nekocode.economy.counter import TokenCounter
from nekocode.economy.scorer import PriorityScorer, compute_hotness
from nekocode.economy.compressor import ContextCompressor
from nekocode.economy.budget import TokenBudget
from nekocode.economy.models import ProviderProfile


class ContextWindow:
    def __init__(self, budget=None, counter=None, scorer=None, compressor=None, provider=None):
        self.budget = budget or TokenBudget()
        self.counter = counter or TokenCounter(provider)
        self.scorer = scorer or PriorityScorer()
        self.compressor = compressor or ContextCompressor(provider)
        self.provider = provider

    def assemble(self, history, system_prompt, user_msg):
        if not self.budget or not self.budget.total:
            profile = ProviderProfile.profile_for(self.provider)
            self.budget = TokenBudget(**profile["budget"])
            self.counter = TokenCounter(self.provider)
            self.compressor = ContextCompressor(self.provider)

        parts = []
        hot_files = compute_hotness(history)

        # 1. System prompt — always full (expand budget if needed)
        sys_tokens = self.counter.estimate(system_prompt)
        budget_remaining = self.budget.available

        parts.append(("system", system_prompt))
        budget_remaining -= sys_tokens

        # 2. User message — always full
        user_tokens = self.counter.estimate(user_msg)
        parts.append(("user", user_msg))
        budget_remaining -= user_tokens

        # 3. History — score, sort, compress, pack
        scored = []
        for idx, item in enumerate(history):
            s = self.scorer.score(item, idx, len(history), hot_files)
            scored.append((s, idx, item))

        scored.sort(key=lambda x: -x[0])

        history_budget = self.budget.history
        packed = []
        for score_val, idx, item in scored:

            compressed = self.compressor.compress(item, history_budget)
            tokens = self.counter.estimate(compressed)

            if tokens > 0 and tokens <= history_budget:
                packed.append((score_val, idx, compressed))
                history_budget -= tokens
            elif score_val > 0.7 and history_budget > 50:
                extreme = self.compressor.compress_extreme(item, min(history_budget, 200))
                ext_tokens = self.counter.estimate(extreme)
                if ext_tokens <= history_budget:
                    packed.append((score_val, idx, extreme))
                    history_budget -= ext_tokens

        # 4. Sort back by original index for temporal coherence
        packed.sort(key=lambda x: x[1])

        omitted = len(history) - len(packed)
        history_texts = [content for _, _, content in packed]

        if omitted > 0:
            history_texts.append(f"... [{omitted} earlier messages omitted by token economy] ...")

        history_block = "\n".join(history_texts)
        parts.append(("history", history_block))

        # 5. Assemble
        return "\n\n".join(content for _, content in parts)

    @property
    def usage(self):
        return {
            "system": self.budget.system,
            "user_msg": self.budget.user_msg,
            "history": self.budget.history,
            "reserve": self.budget.reserve,
            "available": self.budget.available,
        }
