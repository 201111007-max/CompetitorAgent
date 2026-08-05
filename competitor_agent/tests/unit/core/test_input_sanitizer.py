"""core/input_sanitizer.py 单测（M5.3）"""
from pathlib import Path

from competitor_agent.core.input_sanitizer import (
    expand_references,
    sanitize_surrogates,
    sanitize_task,
    strip_paste_wrappers,
    strip_terminal_leaks,
)


class TestSanitizeSurrogates:
    def test_lone_surrogate_replaced(self):
        text = "分析 Cursor \udc80 定价"
        cleaned = sanitize_surrogates(text)
        assert "\udc80" not in cleaned
        assert "分析 Cursor" in cleaned
        # 可安全 json 序列化
        import json

        json.dumps(cleaned, ensure_ascii=False)

    def test_control_chars_replaced(self):
        cleaned = sanitize_surrogates("a\x00b\x07c")
        assert "\x00" not in cleaned
        assert "a b c" == cleaned

    def test_normal_text_unchanged(self):
        assert sanitize_surrogates("分析 Cursor 定价") == "分析 Cursor 定价"

    def test_empty(self):
        assert sanitize_surrogates("") == ""


class TestStripPasteWrappers:
    def test_pasted_text_marker(self):
        assert "[Pasted text]" not in strip_paste_wrappers("[Pasted text] 分析 Cursor")

    def test_pasted_text_with_number(self):
        assert "[Pasted text #3]" not in strip_paste_wrappers("[Pasted text #3] 分析 Cursor")

    def test_case_insensitive(self):
        assert "[Pasted TEXT]" not in strip_paste_wrappers("[Pasted TEXT] 分析")

    def test_normal_text_kept(self):
        assert strip_paste_wrappers("分析 Cursor 定价") == "分析 Cursor 定价"


class TestStripTerminalLeaks:
    def test_ansi_csi_removed(self):
        assert "\x1b[0m" not in strip_terminal_leaks("分析\x1b[0m Cursor")

    def test_osc_removed(self):
        assert "\x1b]0;title\x07" not in strip_terminal_leaks("分析\x1b]0;title\x07Cursor")

    def test_normal_text_kept(self):
        assert strip_terminal_leaks("分析 Cursor 定价") == "分析 Cursor 定价"


class TestExpandReferences:
    def test_expands_file_content(self, tmp_path: Path):
        target = tmp_path / "notes.md"
        target.write_text("Cursor 订阅制 $20/月", encoding="utf-8")
        base = tmp_path / "reports"
        base.mkdir()
        note = base / "note.md"
        note.write_text("性能评测 swe-bench 通过率 42%", encoding="utf-8")

        out = expand_references("分析 @file:reports/note.md", base_dir=str(base.parent))
        assert "性能评测" in out
        assert "swe-bench" in out

    def test_missing_file_keeps_original(self, tmp_path: Path):
        out = expand_references("分析 @file:reports/nope.md", base_dir=str(tmp_path))
        assert out == "分析 @file:reports/nope.md"

    def test_path_traversal_blocked(self, tmp_path: Path):
        # reports 白名单外（如直接引用项目根下文件）不展开，防路径穿越
        outside = tmp_path / "secret.txt"
        outside.write_text("机密", encoding="utf-8")
        base = tmp_path / "reports"
        base.mkdir(exist_ok=True)
        out = expand_references("分析 @file:../secret.txt", base_dir=str(base))
        assert "机密" not in out

    def test_no_reference_unchanged(self):
        assert expand_references("分析 Cursor") == "分析 Cursor"


class TestSanitizeTask:
    def test_combined(self, tmp_path: Path):
        base = tmp_path / "reports"
        base.mkdir()
        note = base / "a.md"
        note.write_text("定价 数据", encoding="utf-8")
        raw = "[Pasted text #1] 分析\x1b[0m @file:reports/a.md"
        out = sanitize_task(raw, base_dir=str(tmp_path))
        assert "[Pasted text" not in out
        assert "\x1b" not in out
        assert "定价 数据" in out

    def test_surrogate_first(self):
        raw = "分析 \udcff Cursor"
        assert "\udcff" not in sanitize_task(raw)
