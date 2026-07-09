"""用例校验器

校验测试用例的格式、必填字段、ID 唯一性。
"""

import json
from pathlib import Path
from typing import Dict, List


class CaseValidationError(Exception):
    """用例校验错误"""

    pass


class CaseValidator:
    """用例校验器"""

    REQUIRED_FIELDS = ["case_id", "input", "difficulty"]
    VALID_DIFFICULTIES = ["easy", "medium", "hard"]

    def validate_cases(self, cases: List[Dict]) -> None:
        """校验用例列表"""
        seen_ids = set()
        for i, case in enumerate(cases):
            self._validate_case(case, i)
            if case["case_id"] in seen_ids:
                raise CaseValidationError(f"Duplicate case_id: {case['case_id']}")
            seen_ids.add(case["case_id"])

    def _validate_case(self, case: Dict, index: int) -> None:
        """校验单条用例"""
        for field in self.REQUIRED_FIELDS:
            if field not in case:
                raise CaseValidationError(
                    f"Case at index {index} missing field: {field}"
                )

        if case["difficulty"] not in self.VALID_DIFFICULTIES:
            raise CaseValidationError(
                f"Case {case['case_id']} invalid difficulty: {case['difficulty']}"
            )

        if not case["case_id"]:
            raise CaseValidationError(f"Case at index {index} has empty case_id")

    def validate_files(self, cases_path: Path, expected_path: Path) -> None:
        """校验用例文件和期望文件的一致性"""
        cases = []
        with open(cases_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    cases.append(json.loads(line))
        self.validate_cases(cases)

        expected_ids = set()
        if expected_path.exists():
            with open(expected_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        item = json.loads(line)
                        expected_ids.add(item["case_id"])

        case_ids = {c["case_id"] for c in cases}
        missing = case_ids - expected_ids
        if missing:
            raise CaseValidationError(f"Cases missing expected output: {missing}")
