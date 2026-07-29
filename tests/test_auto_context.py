"""Tests for auto-context feature."""

from nekocode.auto_context import extract_keywords, find_related_files, build_auto_context


class TestExtractKeywords:
    def test_basic(self):
        kws = extract_keywords("fix the login bug in auth.py")
        assert "fix" in kws
        assert "login" in kws
        assert "bug" in kws
        assert "auth" in kws

    def test_stopwords_removed(self):
        kws = extract_keywords("the and for is it")
        assert kws == []

    def test_max_words(self):
        kws = extract_keywords("one two three four five six seven eight nine ten", max_words=3)
        assert len(kws) <= 3

    def test_short_tokens_ignored(self):
        kws = extract_keywords("a an of to")
        assert kws == []


class TestFindRelatedFiles:
    def test_empty_query(self):
        result = find_related_files("", "/tmp")
        assert result == []

    def test_no_keywords(self):
        result = find_related_files("the and for it", "/tmp")
        assert result == []

    def test_finds_matching_file(self, tmp_path):
        (tmp_path / "auth.py").write_text("def login(): pass\n")
        result = find_related_files("login auth", str(tmp_path), max_files=5)
        assert "auth.py" in result

    def test_respects_max_files(self, tmp_path):
        for i in range(10):
            (tmp_path / f"mod{i}.py").write_text(f"def func{i}(): pass\n")
        result = find_related_files("mod func", str(tmp_path), max_files=3)
        assert len(result) <= 3


class TestBuildAutoContext:
    def test_empty_for_no_query(self, tmp_path):
        result = build_auto_context("", str(tmp_path))
        assert result == ""

    def test_returns_content_block(self, tmp_path):
        (tmp_path / "hello.py").write_text("def greet(): pass\n")
        result = build_auto_context("greet hello", str(tmp_path))
        assert "## Relevant files" in result
        assert "hello.py" in result
        assert "def greet" in result

    def test_respects_max_chars(self, tmp_path):
        (tmp_path / "big.py").write_text("x = 1\n" * 10000)
        result = build_auto_context("big file", str(tmp_path), max_chars=200)
        assert len(result) <= 600  # header + content within ~3x budget

    def test_no_files_empty_result(self, tmp_path):
        result = build_auto_context("nothing matches here", str(tmp_path))
        assert result == ""
