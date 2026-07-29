"""Tests for RepoMap codebase symbol map."""

import os
from nekocode.repo_map import build_repo_map, _parse_python_ast


class TestParsePythonAST:
    def test_class_and_methods(self, tmp_path):
        f = tmp_path / "example.py"
        f.write_text("class Foo:\n    def bar(self): pass\n    async def baz(self): pass\n")
        entries = _parse_python_ast(f)
        assert entries is not None
        names = [e[1] for e in entries]
        assert "class Foo" in names
        assert any("def bar" in n for n in names)
        assert any("async def baz" in n for n in names)

    def test_top_level_functions(self, tmp_path):
        f = tmp_path / "utils.py"
        f.write_text("def hello(): pass\nasync def world(): pass\n")
        entries = _parse_python_ast(f)
        assert entries is not None
        names = [e[1] for e in entries]
        assert "def hello" in names
        assert "async def world" in names

    def test_syntax_error_fallback(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("def foo( bar\nclass Bad:\n")
        entries = _parse_python_ast(f)
        # Should fallback to regex
        assert entries is not None
        assert any("def foo" in e[1] for e in entries)

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        entries = _parse_python_ast(f)
        assert entries == []


class TestBuildRepoMap:
    def test_nonexistent_dir(self):
        result = build_repo_map("/nonexistent/path/xyz")
        assert "(path not found)" in result

    def test_empty_dir(self, tmp_path):
        result = build_repo_map(str(tmp_path))
        assert result == "(empty)" or "(empty)" in result

    def test_single_python_file(self, tmp_path):
        f = tmp_path / "hello.py"
        f.write_text("def greet(): pass\nclass A:\n    def method(self): pass\n")
        result = build_repo_map(str(tmp_path))
        assert "hello.py" in result
        assert "def greet" in result
        assert "class A" in result

    def test_multiple_files(self, tmp_path):
        (tmp_path / "a.py").write_text("def func_a(): pass\n")
        (tmp_path / "b.py").write_text("class B: pass\n")
        result = build_repo_map(str(tmp_path))
        assert "a.py" in result
        assert "b.py" in result

    def test_ignored_dirs_skipped(self, tmp_path):
        os.makedirs(tmp_path / ".git" / "objects", exist_ok=True)
        (tmp_path / ".git" / "objects" / "pack").write_text("data")
        (tmp_path / "real.py").write_text("def work(): pass\n")
        result = build_repo_map(str(tmp_path))
        assert "real.py" in result
        assert ".git" not in result

    def test_max_lines_limit(self, tmp_path):
        for i in range(20):
            (tmp_path / f"f{i}.py").write_text(f"def func{i}(): pass\n")
        result = build_repo_map(str(tmp_path), max_lines=5)
        lines = result.strip().splitlines()
        # Should include at most 5 lines of content (plus header lines)
        # The repo map format: path then symbol lines
        lines_no_header = [l for l in lines if not l.startswith("#")]
        assert len(lines_no_header) <= 10  # some might be path lines
