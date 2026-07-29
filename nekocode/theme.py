"""NekoCode color theme — inspired by MiMo-Code mimocode theme."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


THEMES_DIR = Path(__file__).parent / "themes"


@dataclass(frozen=True)
class Theme:
    primary: str = "#FF6A00"
    secondary: str = "#FF8A3C"
    accent: str = "#818CF8"
    background: str = "#0a0a0a"
    panel_bg: str = "#141414"
    element_bg: str = "#1e1e1e"
    border: str = "#484848"
    border_active: str = "#606060"
    border_subtle: str = "#3c3c3c"
    text: str = "#eeeeee"
    text_muted: str = "#808080"
    success: str = "#FF6A00"
    error: str = "#FB7185"
    warning: str = "#FBBF24"

    @classmethod
    def load(cls, path: Path) -> Theme:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        valid = {k: data[k] for k in data if k in cls.__dataclass_fields__}
        return cls(**valid)


MIMO_THEME = Theme()


def list_themes() -> List[str]:
    """Return sorted list of available theme names (without .json)."""
    if not THEMES_DIR.exists():
        return []
    return sorted(p.stem for p in THEMES_DIR.iterdir() if p.suffix == ".json")


def load_theme(name: str) -> Theme:
    """Load a theme by name from the themes directory."""
    path = THEMES_DIR / f"{name}.json"
    if path.exists():
        try:
            return Theme.load(path)
        except Exception:
            pass
    return Theme()
