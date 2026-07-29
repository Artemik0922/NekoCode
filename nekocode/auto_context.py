"""Auto-context — automatically detect relevant files for the current task."""

import os
import re
import subprocess
from pathlib import Path

IGNORED = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".egg-info", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".claude", ".opencode",
})


def extract_keywords(text, max_words=8):
    """Extract meaningful keywords from user query."""
    stopwords = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "has", "have", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "shall", "to", "of",
        "in", "for", "on", "with", "at", "by", "from", "as", "into",
        "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further",
        "then", "once", "here", "there", "when", "where", "why",
        "how", "all", "each", "every", "both", "few", "more", "most",
        "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "because",
        "and", "but", "or", "if", "while", "that", "this", "these",
        "those", "it", "its", "we", "you", "they", "them", "their",
        "what", "which", "who", "whom",
    })
    tokens = re.findall(r'[a-zA-Z_]\w{2,}', text)
    keywords = [t.lower() for t in tokens if t.lower() not in stopwords and not t.isdigit()]
    return keywords[:max_words]


def _git_ls(root):
    """List tracked files via git."""
    try:
        r = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, timeout=5)
        return [l for l in r.stdout.strip().splitlines() if l] if r.returncode == 0 else []
    except Exception:
        return []


def find_related_files(query, root, max_files=5):
    """Find files related to the user's query using keyword matching."""
    root = Path(root)
    keywords = extract_keywords(query)
    if not keywords:
        return []

    tracked = _git_ls(root)
    if tracked:
        candidates = [root / p for p in tracked]
    else:
        candidates = []
        for dp, dirs, fns in os.walk(root):
            dirs[:] = [d for d in dirs if d not in IGNORED]
            rel = Path(dp).relative_to(root)
            if any(part in IGNORED for part in rel.parts):
                continue
            for fn in fns:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in (".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt", ".rb", ".php", ".lua", ".md", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".txt", ".html", ".css", ".scss", ".sql"):
                    continue
                candidates.append(Path(dp) / fn)

    scored = []
    for fp in candidates:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        text_lower = text.lower()
        score = 0
        for kw in keywords:
            if kw in fp.stem.lower():
                score += 3
            if kw in text_lower:
                score += 1
        # Boost files with exact filename match
        for kw in keywords:
            if kw == fp.stem.lower():
                score += 5
        if score > 0:
            scored.append((score, fp))

    scored.sort(key=lambda x: -x[0])
    return [str(p.relative_to(root)) for _, p in scored[:max_files]]


def build_auto_context(query, root, max_files=5, max_chars=3000):
    """Build an auto-context block for the given query."""
    files = find_related_files(query, root, max_files=max_files)
    if not files:
        return ""
    root = Path(root)
    parts = []
    chars = 0
    for rel_path in files:
        fp = root / rel_path
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if len(text) > 2000:
            text = text[:2000] + "\n... (truncated)"
        snippet = f"# {rel_path}\n{text}"
        if chars + len(snippet) > max_chars:
            break
        parts.append(snippet)
        chars += len(snippet)
    if not parts:
        return ""
    return f"## Relevant files\n\n" + "\n\n".join(parts)
