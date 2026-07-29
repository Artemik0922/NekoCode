"""Token budget allocation per provider."""

from nekocode.economy.models import ProviderProfile


class TokenBudget:
    def __init__(self, total=None, system=2000, user_msg=1000, history=3000, reserve=2000):
        self.system = system
        self.user_msg = user_msg
        self.history = history
        self.reserve = reserve
        self.total = total or (system + user_msg + history + reserve)

    @classmethod
    def from_provider(cls, provider, model=None, overrides=None):
        profile = ProviderProfile.profile_for(provider, model)
        budget = profile["budget"]
        b = cls(
            total=budget.get("total", profile["context_window"]),
            system=budget.get("system", 2000),
            user_msg=budget.get("user_msg", 1000),
            history=budget.get("history", 3000),
            reserve=budget.get("reserve", 2000),
        )
        if overrides:
            for k, v in overrides.items():
                if hasattr(b, k):
                    setattr(b, k, v)
        return b

    @staticmethod
    def from_config(config):
        econ = config.get("economy", {}) if config else {}
        budget_cfg = econ.get("budget", {})
        if not budget_cfg:
            return None
        return TokenBudget(
            total=budget_cfg.get("total"),
            system=budget_cfg.get("system", 2000),
            user_msg=budget_cfg.get("user_request", 1000),
            history=budget_cfg.get("history", 3000),
            reserve=budget_cfg.get("reserve", 2000),
        )

    @property
    def available(self):
        return self.total - self.reserve

    def __repr__(self):
        return (f"TokenBudget(system={self.system}, user_msg={self.user_msg}, "
                f"history={self.history}, reserve={self.reserve}, total={self.total})")
