"""RepoMap — lightweight codebase symbol map using Python AST and regex."""

import ast
import os
import re
from pathlib import Path

IGNORED = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".egg-info", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".claude", ".opencode",
})

EXT_PATTERNS = {
    ".py": ("python", r"^(class|def|async def)\s+(\w+)"),
    ".js": ("javascript", r"^(function\s+|async\s+function\s+|const\s+\w+\s*=\s*(?:async\s*)?\(|class\s+)"),
    ".ts": ("typescript", r"^(export\s+)?(function|class|interface|type|enum|const)\s+(\w+)"),
    ".tsx": ("typescriptreact", r"^(export\s+)?(function|class|interface|type|const)\s+(\w+)"),
    ".jsx": ("javascriptreact", r"^(export\s+)?(function|class|const)\s+(\w+)"),
    ".go": ("go", r"^(func\s+\w+|type\s+\w+\s+struct|type\s+\w+\s+interface)"),
    ".rs": ("rust", r"^(pub\s+)?(fn|struct|enum|trait|impl|mod|type|const|use)\s+(\w+)"),
    ".java": ("java", r"^(public|private|protected)?\s*(class|interface|enum)\s+(\w+)"),
    ".rb": ("ruby", r"^(def\s+\w+|class\s+\w+|module\s+\w+)"),
    ".c": ("c", r"^(int|void|char|float|double|struct|static|unsigned|size_t)\s+\*?\s*\w+\s*\("),
    ".h": ("c_header", r"^(int|void|char|float|double|struct|#define|typedef)\s+"),
    ".cpp": ("cpp", r"^(int|void|char|float|double|struct|class|template|namespace|auto|const)\s+"),
    ".hpp": ("cpp_header", r"^(int|void|char|float|double|struct|class|template|namespace|#define|typedef)\s+"),
    ".cs": ("csharp", r"^(public|private|protected|internal)?\s*(class|struct|interface|enum|namespace|record)\s+(\w+)"),
    ".swift": ("swift", r"^(func|class|struct|enum|protocol|extension|actor)\s+(\w+)"),
    ".kt": ("kotlin", r"^(fun\s+\w+|class\s+\w+|interface\s+\w+|object\s+\w+)"),
    ".lua": ("lua", r"^(function\s+\w+|local\s+function\s+\w+)"),
    ".php": ("php", r"^(function\s+\w+|class\s+\w+|interface\s+\w+)"),
    ".r": ("r", r"^(\w+)\s*<-\s*(function|new)"),
}


def _parse_python_ast(path):
    """Extract class/function/method names from Python files using AST."""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # Fallback to regex
        entries = []
        for m in re.finditer(r"^(class|def|async def)\s+(\w+)", text, re.MULTILINE):
            line = m.group()
            entries.append((m.start(), line))
        return entries
    entries = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            entries.append((node.lineno, f"class {node.name}"))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decor = "@" if any(isinstance(d, (ast.Property, ast.ClassDef)) or
                                       (isinstance(d, ast.Name) and d.id in ("property", "staticmethod", "classmethod"))
                                       or (isinstance(d, ast.Attribute) and d.attr in ("setter", "deleter", "getter"))
                                       for d in item.decorator_list) else ""
                    entries.append((item.lineno, f"  {decor}{'async ' if isinstance(item, ast.AsyncFunctionDef) else ''}def {item.name}"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not any(isinstance(parent, (ast.ClassDef,)) and node in ast.walk(parent) for parent in ast.walk(tree)
                       if parent is not node and isinstance(parent, ast.ClassDef)):
                decor = "@" if node.decorator_list else ""
                entries.append((node.lineno, f"{decor}{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {node.name}"))
    if not entries:
        for m in re.finditer(r"^(class|def|async def)\s+(\w+)", text, re.MULTILINE):
            entries.append((m.start(), m.group() if m.group(1) != "async def" else f"async def {m.group(2)}"))
    return entries


def build_repo_map(root, max_lines=100, max_size_kb=500):
    """Build a compact symbol map of the codebase."""
    root = Path(root)
    if not root.is_dir():
        return "(path not found)"
    lines = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        parts = rel.parts
        # Skip ignored dirs at any depth
        dirnames[:] = [d for d in dirnames if d not in IGNORED]
        if any(part in IGNORED for part in parts):
            continue
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in EXT_PATTERNS:
                continue
            fp = Path(dirpath) / fn
            try:
                size_kb = fp.stat().st_size / 1024
            except OSError:
                continue
            if size_kb > max_size_kb:
                continue
            rel_path = (rel / fn).as_posix() if str(rel) != "." else fn
            if ext == ".py":
                entries = _parse_python_ast(fp)
                if entries is None:
                    continue
                if entries:
                    lines.append(f"{rel_path}:")
                    for lineno, entry in entries:
                        if len(lines) >= max_lines + 50:
                            break
                        lines.append(f"  {entry}")
                        scanned += 1
                else:
                    lines.append(f"{rel_path}")
            else:
                # Regex-based scanning
                text = fp.read_text(encoding="utf-8", errors="replace")
                lang, pattern = EXT_PATTERNS[ext]
                matches = []
                for m in re.finditer(pattern, text, re.MULTILINE):
                    matches.append(m.group().strip())
                if matches:
                    lines.append(f"{rel_path}:")
                    for m in matches[:5]:
                        if len(lines) >= max_lines + 50:
                            break
                        lines.append(f"  {m}")
                        scanned += 1
                    if len(matches) > 5:
                        lines.append(f"  ... +{len(matches) - 5} more")
                else:
                    lines.append(f"{rel_path}")
            if len(lines) >= max_lines:
                break
        if len(lines) >= max_lines:
            break
    return "\n".join(lines[:max_lines]) if lines else "(empty)"
