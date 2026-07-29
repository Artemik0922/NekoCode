"""PriorityScorer — 6-factor message importance ranking."""

RISK_MAP = {
    "write": 1.0, "edit": 1.0, "bash": 1.0, "agent": 0.8,
    "delegate": 0.8, "task_create": 0.6, "task_update": 0.4, "task_done": 0.3,
    "read": 0.3, "glob": 0.3, "grep": 0.3, "list_files": 0.2,
    "web_fetch": 0.5, "web_search": 0.5, "skill": 0.4,
    "submit_blueprint": 0.7, "log_tech_debt": 0.6,
    "remember": 0.5, "recall": 0.3,
}

WEIGHTS = {
    "recency": 0.35,
    "tool_risk": 0.20,
    "result_content": 0.15,
    "is_user": 0.15,
    "success": 0.10,
    "file_hotness": 0.05,
}


def compute_hotness(history):
    hot = {}
    for item in history:
        path = item.get("args", {}).get("path", "")
        if path:
            hot[path] = hot.get(path, 0) + 1
    return hot


def score_message(item, idx, history_len, hot_files):
    recency = 1.0 / (1.0 + 0.3 * (history_len - 1 - idx))

    name = item.get("name", "")
    risk = RISK_MAP.get(name, 0.5)

    content = str(item.get("content", ""))
    result_val = min(1.0, len(content) / 500) if content.strip() else 0.2

    role = item.get("role", "")
    is_user = 0.9 if role == "user" else 0.3
    if role == "user" and idx == history_len - 1:
        is_user = 1.0

    is_error = 1.0 if content.lower().startswith("error") else 0.0
    success = 1.0 if is_error == 0.0 else 0.3

    fname = item.get("args", {}).get("path", "")
    fhot = min(1.0, hot_files.get(fname, 0) / 3)

    return (WEIGHTS["recency"] * recency +
            WEIGHTS["tool_risk"] * risk +
            WEIGHTS["result_content"] * result_val +
            WEIGHTS["is_user"] * is_user +
            WEIGHTS["success"] * success +
            WEIGHTS["file_hotness"] * fhot)


class PriorityScorer:
    @staticmethod
    def score(item, idx, history_len, hot_files):
        return score_message(item, idx, history_len, hot_files)

    @staticmethod
    def hotness(history):
        return compute_hotness(history)
