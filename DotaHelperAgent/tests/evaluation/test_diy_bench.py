"""测试 DotaBench 工具"""

import json

import pytest

from DotaBench.utils.case_loader import CaseLoader
from DotaBench.utils.case_validator import CaseValidator, CaseValidationError


class TestCaseLoader:
    """测试用例加载器"""

    def test_load_cases(self):
        """测试加载用例"""
        loader = CaseLoader()
        cases = loader.load_cases("lineup_analyzer", "skill_bench")
        assert len(cases) >= 1
        assert "case_id" in cases[0]
        assert "input" in cases[0]
        assert "difficulty" in cases[0]

    def test_load_cases_with_difficulty(self):
        """测试按难度过滤"""
        loader = CaseLoader()
        easy_cases = loader.load_cases("lineup_analyzer", "skill_bench", "easy")
        assert all(c["difficulty"] == "easy" for c in easy_cases)

    def test_load_expected(self):
        """测试加载期望输出"""
        loader = CaseLoader()
        expected = loader.load_expected("lineup_analyzer", "skill_bench")
        assert len(expected) >= 1
        first_key = list(expected.keys())[0]
        assert "key_points" in expected[first_key]

    def test_load_nonexistent_module(self):
        """测试加载不存在的模块"""
        loader = CaseLoader()
        with pytest.raises(FileNotFoundError):
            loader.load_cases("nonexistent_module", "skill_bench")

    def test_list_modules(self):
        """测试列出模块"""
        loader = CaseLoader()
        modules = loader.list_modules("skill_bench")
        assert isinstance(modules, list)
        assert "lineup_analyzer" in modules


class TestCaseValidator:
    """测试用例校验器"""

    def test_valid_cases(self):
        """测试合法用例"""
        cases = [
            {"case_id": "c1", "input": {}, "difficulty": "easy"},
            {"case_id": "c2", "input": {}, "difficulty": "medium"},
        ]
        validator = CaseValidator()
        validator.validate_cases(cases)  # 不应抛出

    def test_missing_field(self):
        """测试缺少字段"""
        cases = [{"case_id": "c1", "input": {}}]  # 缺 difficulty
        validator = CaseValidator()
        with pytest.raises(CaseValidationError, match="missing field"):
            validator.validate_cases(cases)

    def test_invalid_difficulty(self):
        """测试非法难度"""
        cases = [{"case_id": "c1", "input": {}, "difficulty": "super_hard"}]
        validator = CaseValidator()
        with pytest.raises(CaseValidationError, match="invalid difficulty"):
            validator.validate_cases(cases)

    def test_duplicate_id(self):
        """测试重复 case_id"""
        cases = [
            {"case_id": "c1", "input": {}, "difficulty": "easy"},
            {"case_id": "c1", "input": {}, "difficulty": "easy"},
        ]
        validator = CaseValidator()
        with pytest.raises(CaseValidationError, match="Duplicate"):
            validator.validate_cases(cases)

    def test_empty_case_id(self):
        """测试空 case_id"""
        cases = [{"case_id": "", "input": {}, "difficulty": "easy"}]
        validator = CaseValidator()
        with pytest.raises(CaseValidationError, match="empty case_id"):
            validator.validate_cases(cases)

    def test_validate_files(self, tmp_path):
        """测试文件级校验"""
        cases_file = tmp_path / "cases.jsonl"
        expected_file = tmp_path / "expected.jsonl"

        cases_file.write_text(
            json.dumps({"case_id": "c1", "input": {}, "difficulty": "easy"})
            + "\n",
            encoding="utf-8",
        )
        expected_file.write_text(
            json.dumps({"case_id": "c1", "key_points": ["a"]}) + "\n",
            encoding="utf-8",
        )

        validator = CaseValidator()
        validator.validate_files(cases_file, expected_file)  # 不应抛出

    def test_validate_files_missing_expected(self, tmp_path):
        """测试期望文件缺失"""
        cases_file = tmp_path / "cases.jsonl"
        cases_file.write_text(
            json.dumps({"case_id": "c1", "input": {}, "difficulty": "easy"})
            + "\n",
            encoding="utf-8",
        )
        expected_file = tmp_path / "expected.jsonl"  # 不创建

        validator = CaseValidator()
        with pytest.raises(CaseValidationError, match="missing expected"):
            validator.validate_files(cases_file, expected_file)
