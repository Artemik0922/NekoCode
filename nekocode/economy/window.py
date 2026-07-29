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
        self._cache_key = None
        self._cache_result = None

    def assemble(self, history, system_prompt, user_msg, memory_block=None, auto_context=None):
        # Fast path: cached result for unchanged history
        current_key = (len(history), system_prompt, user_msg, memory_block, auto_context)
        if current_key == self._cache_key and self._cache_result is not None:
            return self._cache_result
        if not self.budget or not self.budget.total:
            profile = ProviderProfile.profile_for(self.provider)
            self.budget = TokenBudget(**profile["budget"])
            self.counter = TokenCounter(self.provider)
            self.compressor = ContextCompressor(self.provider)

        parts = []
        hot_files = compute_hotness(history)

        # 1. System prompt — always full
        parts.append(("system", system_prompt))

        # 2. Memory block — included with own budget, compressed if too large
        if memory_block:
            mem_tokens = self.counter.estimate(memory_block)
            mem_budget = max(200, self.budget.system // 4)
            if mem_tokens > mem_budget:
                mem_compressed = self.compressor._trim(memory_block, int(mem_budget * self.counter.ratio))
                parts.append(("memory", mem_compressed))
            else:
                parts.append(("memory", memory_block))

        # 3. User message — always full (with optional auto-context)
        user_content = user_msg
        if auto_context:
            user_content = user_msg + "\n\n" + auto_context
        parts.append(("user", user_content))

        # 4. History — score, sort, compress, pack
        history_budget = self.budget.history
        scored = []
        for idx, item in enumerate(history):
            s = self.scorer.score(item, idx, len(history), hot_files)
            scored.append((s, idx, item))

        scored.sort(key=lambda x: -x[0])

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

        # Sort back by original index for temporal coherence
        packed.sort(key=lambda x: x[1])

        omitted = len(history) - len(packed)
        history_texts = [content for _, _, content in packed]

        if omitted > 0:
            history_texts.append(f"... [{omitted} earlier messages omitted by token economy] ...")

        history_block = "\n".join(history_texts)
        parts.append(("history", history_block))

        result = "\n\n".join(content for _, content in parts)
        self._cache_key = current_key
        self._cache_result = result
        return result

    @property
    def usage(self):
        return {
            "system": self.budget.system,
            "user_msg": self.budget.user_msg,
            "history": self.budget.history,
            "reserve": self.budget.reserve,
            "available": self.budget.available,
        }
