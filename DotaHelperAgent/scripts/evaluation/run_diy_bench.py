"""运行 DotaBench 评测集

执行所有 Skill/SubAgent 模块的评测用例，使用 LLM-as-a-Judge 评分。

使用方法:
    # Mock 模式（无需 LLM 客户端）
    python scripts/evaluation/run_diy_bench.py --bench-type skill_bench --difficulty easy

    # 真实 LLM 模式
    python scripts/evaluation/run_diy_bench.py --bench-type skill_bench --module lineup_analyzer

    # 完整运行
    python scripts/evaluation/run_diy_bench.py --all
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

# 添加项目根目录到 Python 路径
# 这样在 DotaHelperAgent 根目录下执行: python scripts/evaluation/run_diy_bench.py 也能工作
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from DotaBench.utils.case_loader import CaseLoader
from DotaBench.utils.case_validator import CaseValidator, CaseValidationError
from evaluation.base import EvaluationContext, EvaluationStatus
from evaluation.judges import build_judge_adapter, MultiDimensionalJudge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_llm_client_from_config():
    """从项目配置构建 LLM 客户端（可选）"""
    try:
        from utils.llm_client import LLMClient
        from core.config import LLMConfig

        config = LLMConfig()
        if not config.api_key and not config.base_url:
            logger.info("LLM config incomplete, using Mock mode")
            return None
        logger.info(f"Using LLM: {config.model} @ {config.base_url}")
        return LLMClient(config)
    except Exception as e:
        logger.warning(f"Failed to load LLM config: {e}, using Mock mode")
        return None


def execute_skill(
    module: str,
    case_input: dict,
    case_id: str,
) -> str:
    """执行 Skill 并返回实际输出

    实际集成时，这里应该调用真正的 Skill 模块。
    当前为占位实现，返回 Mock 输出用于跑通流程。

    Args:
        module: 模块名
        case_input: 输入数据
        case_id: 用例 ID

    Returns:
        实际输出文本
    """
    # TODO: 集成实际的 Skill 调用
    # 例如:
    # from skills.registry import get_skill
    # skill = get_skill(module)
    # return skill.run(case_input)

    return f"[Mock Output] module={module}, case_id={case_id}, input_keys={list(case_input.keys()) if isinstance(case_input, dict) else 'N/A'}"


def run_module(
    module: str,
    bench_type: str,
    judge: MultiDimensionalJudge,
    loader: CaseLoader,
    difficulty: Optional[str] = None,
) -> List[dict]:
    """运行单个模块的评测"""
    cases = loader.load_cases(module, bench_type, difficulty)
    expected_map = loader.load_expected(module, bench_type)

    logger.info(
        f"Running {bench_type}/{module}: {len(cases)} cases"
        + (f" (difficulty={difficulty})" if difficulty else "")
    )

    results = []
    for case in cases:
        # 实际执行 Skill
        actual_output = execute_skill(module, case["input"], case["case_id"])

        context = EvaluationContext(
            case_id=case["case_id"],
            input_data=case["input"],
            expected_output=expected_map.get(case["case_id"]),
            actual_output=actual_output,
            metadata={
                "difficulty": case.get("difficulty"),
                "tags": case.get("tags", []),
                "module": module,
            },
        )

        result = judge.run(context)
        results.append(result.to_dict())
        logger.info(
            f"  {case['case_id']}: score={result.total_score:.2f}, "
            f"status={result.status.value}"
        )

    return results


def save_results(results: List[dict], output_path: Path) -> None:
    """保存结果到 JSONL"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info(f"Results saved to: {output_path}")


def print_summary(results: List[dict]) -> None:
    """打印汇总信息"""
    if not results:
        logger.info("No results to summarize")
        return

    completed = [r for r in results if r.get("status") == "completed"]
    failed = [r for r in results if r.get("status") == "failed"]
    avg_score = (
        sum(r.get("total_score", 0) for r in completed) / len(completed)
        if completed
        else 0
    )

    logger.info("")
    logger.info("=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)
    logger.info(f"Total cases:     {len(results)}")
    logger.info(f"Completed:       {len(completed)}")
    logger.info(f"Failed:          {len(failed)}")
    logger.info(f"Average score:   {avg_score:.2f} / 5.00")
    if failed:
        logger.info(f"Failed cases:    {[r['case_id'] for r in failed[:5]]}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Run DotaBench evaluation suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--bench-type",
        default="skill_bench",
        choices=["skill_bench", "subagent_bench", "e2e_bench"],
        help="评测类型",
    )
    parser.add_argument(
        "--module",
        help="指定模块（不指定则运行该 bench_type 下的所有模块）",
    )
    parser.add_argument(
        "--difficulty",
        choices=["easy", "medium", "hard"],
        help="难度过滤",
    )
    parser.add_argument(
        "--output",
        default="data/evaluation/results/latest.jsonl",
        help="结果输出路径",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="运行所有 bench_type（skill_bench + subagent_bench）",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="强制使用 Mock 模式（不连接真实 LLM）",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="运行前校验所有用例格式",
    )
    args = parser.parse_args()

    # 构建 LLM 客户端和 Judge
    llm_client = None if args.no_llm else build_llm_client_from_config()
    adapter = build_judge_adapter(llm_client=llm_client, temperature=0.0)
    judge = MultiDimensionalJudge(
        llm_adapter=adapter,
        module_name=args.module,
        n_samples=1,
    )

    # 准备 loader
    loader = CaseLoader()

    # 确定要运行的 bench 类型
    bench_types = ["skill_bench", "subagent_bench"] if args.all else [args.bench_type]

    all_results = []

    for bench_type in bench_types:
        # 列出模块
        if args.module:
            modules = [args.module]
        else:
            modules = loader.list_modules(bench_type)
            if not modules:
                logger.warning(
                    f"No modules found in {bench_type}/. "
                    f"Run from project root or check DotaBench directory."
                )
                continue

        # 校验（可选）
        if args.validate:
            validator = CaseValidator()
            from pathlib import Path as P
            for module in modules:
                cases_path = loader.base_path / bench_type / module / "cases.jsonl"
                expected_path = (
                    loader.base_path / bench_type / module / "expected.jsonl"
                )
                if cases_path.exists():
                    try:
                        validator.validate_files(cases_path, expected_path)
                        logger.info(f"[OK] {bench_type}/{module} validated")
                    except CaseValidationError as e:
                        logger.error(f"[FAIL] {bench_type}/{module}: {e}")

        # 运行
        for module in modules:
            try:
                results = run_module(
                    module, bench_type, judge, loader, args.difficulty
                )
                all_results.extend(results)
            except FileNotFoundError as e:
                logger.warning(f"Skipping {module}: {e}")

    # 输出
    if all_results:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path
        save_results(all_results, output_path)
        print_summary(all_results)
    else:
        logger.warning(
            "No results generated. Make sure DotaBench has valid case files."
        )

    # 提示 Mock 模式
    if llm_client is None:
        logger.info("")
        logger.info("💡 当前为 Mock 模式（未连接真实 LLM）。")
        logger.info("   配置 utils/llm_client.py 的 LLMConfig 后将自动启用真实评估。")


if __name__ == "__main__":
    main()
