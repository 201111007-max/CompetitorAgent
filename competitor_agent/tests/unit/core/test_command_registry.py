"""core/command_registry.py 单测（M5.2）"""
from competitor_agent.core.command_registry import (
    COMMAND_REGISTRY,
    CommandDef,
    _looks_like_slash_command,
    command_dispatch,
    resolve_command,
)


class TestLooksLikeSlashCommand:
    def test_slash_prefix(self):
        assert _looks_like_slash_command("/analyze Cursor")

    def test_leading_whitespace_tolerated(self):
        assert _looks_like_slash_command("  /history")

    def test_plain_text_not_command(self):
        assert not _looks_like_slash_command("分析 Cursor")

    def test_file_path_excluded(self):
        # 首词含第二个 /，是路径而非命令
        assert not _looks_like_slash_command("/Users/foo/notes.md 分析 Cursor")

    def test_url_excluded(self):
        assert not _looks_like_slash_command("/https://example.com 分析")

    def test_empty(self):
        assert not _looks_like_slash_command("")
        assert not _looks_like_slash_command("   ")


class TestResolveCommand:
    def test_resolve_by_name(self):
        cmd = resolve_command("/analyze")
        assert cmd is not None
        assert cmd.name == "analyze"
        assert cmd.handler == "analyze"

    def test_resolve_by_alias(self):
        assert resolve_command("/c").name == "compare"

    def test_resolve_help_question_mark(self):
        assert resolve_command("/?").name == "help"

    def test_resolve_unknown(self):
        assert resolve_command("/foobar") is None

    def test_resolve_empty(self):
        assert resolve_command("/") is None

    def test_registry_unique_names(self):
        names = [c.name for c in COMMAND_REGISTRY]
        assert len(names) == len(set(names))
        assert all(isinstance(c, CommandDef) for c in COMMAND_REGISTRY)


class TestCommandDispatch:
    def test_dispatches_known_command(self):
        called = []
        handlers = {"analyze": lambda a: called.append(a)}
        assert command_dispatch("/analyze Cursor", handlers) is True
        assert called == ["Cursor"]

    def test_non_command_returns_false(self):
        assert command_dispatch("分析 Cursor", {}) is False

    def test_unknown_command_falls_back_help(self):
        called = []
        handlers = {"help": lambda a: called.append(a)}
        assert command_dispatch("/wat", handlers) is True
        assert called

    def test_missing_handler_returns_false(self):
        assert command_dispatch("/analyze Cursor", {}) is False
