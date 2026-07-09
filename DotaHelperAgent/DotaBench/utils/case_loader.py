"""用例加载器

从 JSONL 文件加载测试用例。
"""

import json
from pathlib import Path
from typing import Dict, Iterator, List, Optional


class CaseLoader:
    """用例加载器"""

    def __init__(self, base_path: str = "DotaBench"):
        # 如果是相对路径，尝试多个候选位置
        p = Path(base_path)
        if p.is_absolute() and p.exists():
            self.base_path = p
        else:
            # 尝试相对项目根目录
            candidates = [
                Path.cwd() / base_path,
                Path.cwd() / "DotaHelperAgent" / base_path,
                Path(__file__).resolve().parents[2] / base_path,
            ]
            self.base_path = next((c for c in candidates if c.exists()), p)

    def load_cases(
        self,
        module: str,
        bench_type: str = "skill_bench",
        difficulty: Optional[str] = None,
    ) -> List[Dict]:
        """加载测试用例

        Args:
            module: 模块名（如 lineup_analyzer）
            bench_type: 评测类型（skill_bench / subagent_bench / e2e_bench）
            difficulty: 难度过滤（easy / medium / hard）

        Returns:
            用例列表
        """
        cases_path = self.base_path / bench_type / module / "cases.jsonl"
        if not cases_path.exists():
            raise FileNotFoundError(f"Cases file not found: {cases_path}")

        cases = []
        with open(cases_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                if difficulty and case.get("difficulty") != difficulty:
                    continue
                cases.append(case)
        return cases

    def load_expected(
        self, module: str, bench_type: str = "skill_bench"
    ) -> Dict[str, Dict]:
        """加载期望输出（按 case_id 索引）"""
        expected_path = self.base_path / bench_type / module / "expected.jsonl"
        if not expected_path.exists():
            return {}

        expected_map = {}
        with open(expected_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                expected_map[item["case_id"]] = item
        return expected_map

    def load_judge_prompts(
        self,
        module: str,
        bench_type: str = "skill_bench",
    ) -> Dict:
        """加载 Judge Prompt 模板"""
        import yaml
        prompts_path = self.base_path / bench_type / module / "judge_prompts.yaml"
        if not prompts_path.exists():
            return {}
        with open(prompts_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def list_modules(self, bench_type: str = "skill_bench") -> List[str]:
        """列出某类型下的所有模块"""
        bench_path = self.base_path / bench_type
        if not bench_path.exists():
            return []
        return [d.name for d in bench_path.iterdir() if d.is_dir()]
