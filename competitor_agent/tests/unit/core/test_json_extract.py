"""core/json_extract.py 单测（设计文档 87 §3.1 基建下移 + §4 coerce_str_list）

extract_json_block/light_fix_json/parse_json_candidate 的行为覆盖由
tests/unit/facade/test_react_report_65.py（经 react_report 旧名别名）承担，
本文件聚焦新增的类型归一 helper 与别名一致性。
"""

from __future__ import annotations

from competitor_agent.core.json_extract import (
    coerce_str_list,
    extract_json_block,
    light_fix_json,
    parse_json_candidate,
)
from competitor_agent.facade import react_report


class TestCoerceStrList:
    """doc 87 §4：None→[]；str→[str]（整体一项）；list→非空 str 元素；其余→[]"""

    def test_none_to_empty(self) -> None:
        assert coerce_str_list(None) == []

    def test_str_single_item_not_char_iterated(self) -> None:
        """核心回归：字符串按整体一项，不被按字符迭代（task_parser competitors P0）。"""
        assert coerce_str_list("Claude Code") == ["Claude Code"]

    def test_blank_str_to_empty(self) -> None:
        assert coerce_str_list("   ") == []

    def test_list_keeps_nonempty_str_items(self) -> None:
        assert coerce_str_list(["cursor", "", "windsurf"]) == ["cursor", "windsurf"]

    def test_list_drops_non_str_items(self) -> None:
        assert coerce_str_list(["cursor", 30, None, {"name": "x"}]) == ["cursor"]

    def test_other_types_to_empty(self) -> None:
        assert coerce_str_list({"a": 1}) == []
        assert coerce_str_list(30) == []


class TestBackwardCompatAliases:
    """doc 87 §8：平移后 react_report 旧名别名指向同一函数（comparison_report/既有测试零改动）。"""

    def test_aliases_are_same_objects(self) -> None:
        assert react_report._extract_json_block is extract_json_block
        assert react_report._light_fix_json is light_fix_json
        assert react_report._parse_json_candidate is parse_json_candidate
