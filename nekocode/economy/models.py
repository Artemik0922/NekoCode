ECONOMY_DEFAULTS = {
    "enabled": True,
    "tracking": True,
}


PROVIDER_PROFILES = {
    "ollama": {
        "context_window": 8192,
        "output_limit": 2048,
        "ratio_chars_per_token": 3.0,
        "budget": {
            "system": 2000,
            "user_msg": 1000,
            "history": 3192,
            "reserve": 2000,
        },
    },
    "openai": {
        "context_window": 128000,
        "output_limit": 16384,
        "ratio_chars_per_token": 4.0,
        "budget": {
            "system": 6000,
            "user_msg": 3000,
            "history": 100000,
            "reserve": 19000,
        },
    },
    "anthropic": {
        "context_window": 200000,
        "output_limit": 8192,
        "ratio_chars_per_token": 3.5,
        "budget": {
            "system": 8000,
            "user_msg": 4000,
            "history": 180000,
            "reserve": 8000,
        },
    },
    "google": {
        "context_window": 1048576,
        "output_limit": 8192,
        "ratio_chars_per_token": 4.0,
        "budget": {
            "system": 8000,
            "user_msg": 4000,
            "history": 1000000,
            "reserve": 32000,
        },
    },
    "custom": {
        "context_window": 128000,
        "output_limit": 4096,
        "ratio_chars_per_token": 4.0,
        "budget": {
            "system": 4000,
            "user_msg": 2000,
            "history": 100000,
            "reserve": 22000,
        },
    },
}

FALLBACK_PROFILE = {
    "context_window": 32000,
    "output_limit": 4096,
    "ratio_chars_per_token": 3.5,
    "budget": {
        "system": 4000,
        "user_msg": 2000,
        "history": 20000,
        "reserve": 6000,
    },
}

COMPRESSION_STRATEGIES = {
    "bash": "summary",
    "grep": "counts",
    "read": "trim",
    "web_fetch": "trim",
    "web_search": "trim",
    "glob": "counts",
    "list_files": "counts",
    "recall": "trim",
    "task_list": "counts",
    "agent": "none",
    "write": "none",
    "edit": "none",
    "submit_blueprint": "none",
    "log_tech_debt": "none",
    "remember": "none",
    "task_create": "none",
    "task_update": "none",
    "task_done": "none",
    "skill": "none",
}

DEFAULT_COMPRESSION_STRATEGY = "trim"


class ProviderProfile:
    @staticmethod
    def profile_for(provider, model=None):
        key = provider.lower() if provider else "custom"
        profile = PROVIDER_PROFILES.get(key, FALLBACK_PROFILE).copy()
        profile["budget"] = dict(profile["budget"])
        return profile

    @staticmethod
    def chars_per_token(provider):
        key = provider.lower() if provider else "custom"
        return PROVIDER_PROFILES.get(key, FALLBACK_PROFILE).get("ratio_chars_per_token", 3.5)

    @staticmethod
    def compression_strategy(tool_name):
        return COMPRESSION_STRATEGIES.get(tool_name, DEFAULT_COMPRESSION_STRATEGY)
