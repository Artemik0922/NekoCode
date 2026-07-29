"""File-based persistent memory system (Claude Code analog)."""

import re
from datetime import datetime, timezone
from pathlib import Path


MEMORY_DIR = ".agent/memory"
MEMORY_INDEX = "MEMORY.md"

MEMORY_TYPES = {
    "user": "О пользователе: роль, цели, знания, предпочтения",
    "project": "О проекте: цели, инициативы, контекст задач",
    "feedback": "Обратная связь: что сохранить/изменить в поведении",
    "reference": "Ссылки: где искать информацию во внешних системах",
}


def now():
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, root):
        self.root = Path(root)
        self.memory_root = self.root / MEMORY_DIR
        self.index_path = self.root / MEMORY_INDEX

    def init(self):
        self.memory_root.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.index_path.write_text("# MEMORY INDEX\n\n", encoding="utf-8")
        return self

    def _slug(self, text):
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip()).strip("-")
        return slug[:48] or "memory"

    def save(self, mem_type, name, description, body):
        assert mem_type in MEMORY_TYPES, f"unknown memory type: {mem_type}"
        slug = self._slug(name)
        path = self.memory_root / f"{slug}.md"
        content = [
            "---",
            f"name: {slug}",
            f"description: {description}",
            "metadata:",
            f"  type: {mem_type}",
            f"  updated: {now()}",
            "---",
            "",
            body.strip(),
            "",
        ]
        path.write_text("\n".join(content), encoding="utf-8")
        self._add_to_index(slug, description)
        return path

    def _add_to_index(self, slug, description):
        lines = self.index_path.read_text(encoding="utf-8").splitlines()
        line = f"- [{slug}]({MEMORY_DIR}/{slug}.md) — {description}"
        existing = [l for l in lines if l.startswith(f"- [{slug}]")]
        if existing:
            idx = lines.index(existing[0])
            lines[idx] = line
        else:
            lines.append(line)
        self.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def load(self, slug):
        path = self.memory_root / f"{slug}.md"
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        front = {}
        body_start = 0
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                for line in text[3:end].strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        front[k.strip()] = v.strip()
                body_start = end + 3
        return {"frontmatter": front, "body": text[body_start:].strip()}

    def delete(self, slug):
        path = self.memory_root / f"{slug}.md"
        if path.exists():
            path.unlink()
        self._remove_from_index(slug)

    def _remove_from_index(self, slug):
        if not self.index_path.exists():
            return
        lines = [l for l in self.index_path.read_text(encoding="utf-8").splitlines()
                 if not l.startswith(f"- [{slug}]")]
        self.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def exists(self, slug):
        return (self.memory_root / f"{slug}.md").exists()

    def list_all(self):
        if not self.index_path.exists():
            return []
        return [l.strip() for l in self.index_path.read_text(encoding="utf-8").splitlines()
                if l.startswith("- [")]

    def update(self, slug, mem_type, name, description, body):
        if not self.exists(slug):
            return self.save(mem_type, name, description, body)
        return self.save(mem_type, name, description, body)

    def index_text(self, limit=100):
        if not self.index_path.exists():
            return ""
        lines = self.index_path.read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[:limit])
