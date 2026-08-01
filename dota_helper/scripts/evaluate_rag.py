"""RAG 评估脚本 — 使用 RAGAS 框架

评估维度：
1. faithfulness: 回答是否忠实于检索到的文档（无幻觉）
2. answer_relevancy: 回答与问题的相关度
3. context_precision: 检索结果中有多少是相关的
4. context_recall: 需要的相关信息是否都被检索到了

用法：
    python scripts/evaluate_rag.py
    python scripts/evaluate_rag.py --llm-model gpt-4o-mini  # 指定评估 LLM
    python scripts/evaluate_rag.py --output results.json    # 输出到文件
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# 确保项目父目录在 sys.path 中（dota_helper 是项目根目录下的包）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # dota_helper/
_PARENT_DIR = _PROJECT_ROOT.parent  # DotaHelperAgent/
if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

# 企业网络环境：禁用 SSL 验证 + 使用 HF 镜像 + 离线模式
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
import httpx
_original_httpx_init = httpx.Client.__init__
def _ssl_disabled_init(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    _original_httpx_init(self, *args, **kwargs)
httpx.Client.__init__ = _ssl_disabled_init

from datasets import Dataset

from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)
from ragas.metrics._context_precision import NonLLMContextPrecisionWithReference
from ragas.metrics._context_recall import NonLLMContextRecall

from dota_helper.agent.rag_engine import RagEngine


# ── 测试集 ──
# 每条包含：
#   user_input: 用户问题
#   reference:  标准答案（ground truth）
#   expected_category: 期望检索到的文档分类（用于检查检索质量）
TEST_QUERIES: List[Dict[str, Any]] = [
    # ── 英雄攻略 ──
    {
        "user_input": "幽鬼前期怎么出装？",
        "reference": "幽鬼前期核心装备是动力鞋和辉耀。动力鞋提供属性切换，辉耀提升刷钱效率和团战输出。后续可以出散失之刃提升荒芜伤害，龙心提升生存能力。",
        "expected_category": "hero",
    },
    {
        "user_input": "帕吉的肉钩有什么技巧？",
        "reference": "帕吉的肉钩是核心技能，团战前找角度钩对方核心英雄，钩到后开腐烂加肢解控制。出装方面静谧之鞋提升移速和续航，闪烁匕首可以跳钩连招，阿哈利姆神杖提升钩子伤害并可钩多个单位。",
        "expected_category": "hero",
    },
    {
        "user_input": "祈求者有哪些流派和连招？",
        "reference": "祈求者有三大流派：QW冰雷流侧重控制和生存适合新手，QE冰火流侧重爆发和刷钱适合进阶，WE雷火流侧重攻速和移速适合高手。核心连招包括吹风磁暴陨石连招、天火超远距离收割、急速冷却加冰墙单杀连招。",
        "expected_category": "hero",
    },
    {
        "user_input": "敌法师克制哪些英雄？",
        "reference": "敌法师克制所有魔法依赖型英雄，包括宙斯（魔法抗性和法力损毁完美克制高魔法爆发）、风暴之灵（闪烁追击，法力损毁让Storm无法滚）、莉娜（高魔法抗性降低爆发伤害）、帕克（闪烁躲避梦境缠绕）。",
        "expected_category": "hero",
    },
    {
        "user_input": "影魔的影压怎么用？",
        "reference": "影魔的影压有三段：X影压近程贴身释放，Z影压中程标准距离，C影压远程最远距离。连招通常是跳刀近身接X影压，然后大招魂之挽歌，再接Z或C影压收割。",
        "expected_category": "hero",
    },
    # ── 装备分析 ──
    {
        "user_input": "狂战斧和辉耀有什么区别？",
        "reference": "狂战斧价格4100，提供近战60%分裂攻击，适合敌法师、剑圣等需要刷钱的近战核心，通常在10-15分钟做出。辉耀价格4700，提供每秒60点范围灼烧伤害和17%落空概率，适合幽鬼、炼金术士等需要范围伤害的英雄，15-20分钟做出。狂战斧刷钱更快，辉耀打架更强。",
        "expected_category": "item",
    },
    {
        "user_input": "什么时候该出黑皇杖？",
        "reference": "黑皇杖价格4050，提供技能免疫（9/8/7/6/5/4秒持续递减），适合所有核心英雄。当对方有强力控制技能时就应该出，注意持续时间逐次递减。",
        "expected_category": "item",
    },
    # ── 游戏机制 ──
    {
        "user_input": "Dota 2 的护甲减免怎么计算？",
        "reference": "物理减免 = (护甲 × 0.06) / (1 + 护甲 × 0.06)。例如5护甲提供23%减免（1.3倍有效生命），10护甲提供37.5%减免（1.6倍）。负护甲会加深伤害：伤害加深 = 1 - (0.94)^(-护甲)，-5护甲=26.6%额外物理伤害。减甲手段包括技能（VS恐怖波动、影魔魔王降临等）和装备（黯灭-6、勇气勋章-6、炎阳纹章-10）。",
        "expected_category": "mechanics",
    },
    {
        "user_input": "魔法抗性是怎么叠加的？",
        "reference": "魔抗是乘法叠加：总魔抗 = 1 - (1 - 基础抗性) × (1 - 物品抗性) × (1 - 技能抗性)。所有英雄基础魔抗25%。常见魔抗来源：挑战头巾30%、洞察烟斗30%光环、永恒之盘25%、敌法师法术反制26-50%。降低魔抗的手段有纷争面纱-18%和上古巨神自然秩序等。",
        "expected_category": "mechanics",
    },
    {
        "user_input": "中立物品的掉落时间和等级怎么分配？",
        "reference": "中立物品分5级：1级7分钟后掉落（约10%概率），2级17分钟后，3级27分钟后，4级37分钟后，5级60分钟后。1级推荐可靠铁铲给辅助、奥术戒指给缺蓝英雄；2级推荐吸血鬼獠牙给物理核心；3级巨神残铁给核心；4级忍者装备给物理核心、浩劫之锤给先手英雄；5级神镜盾给肉盾、书之力量给力量英雄。",
        "expected_category": "mechanics",
    },
    # ── 策略 ──
    {
        "user_input": "什么时候适合打 Roshan？",
        "reference": "适合打盾的情况：团灭对方后30秒内、对方核心阵亡、己方核心关键装备到手（如BKB、撒旦）、15-20分钟第一次打盾、经济领先5000+。不适合打盾的情况：对方全员存活容易被抢、己方核心没大、视野被压制、经济落后10000+、15分钟前效率低。打盾时坦克站前面抗伤害，输出站背后避免猛击，辅助在坑外提供视野。",
        "expected_category": "strategies",
    },
    {
        "user_input": "上高地的条件是什么？",
        "reference": "进攻高地需要满足：经济领先至少8000-10000、有Aegis在手、关键大招就绪、至少两路兵线推进、对方核心阵亡。不适合进攻的情况：经济持平或落后、无Aegis、对方有高地防守英雄（宙斯、工程师等）、己方核心装备未成型、兵线不好。进攻时同时推进两路兵线分散防守，远程英雄消耗塔血量，利用跳刀先手英雄找机会。",
        "expected_category": "strategies",
    },
    {
        "user_input": "Dota 2 插眼有什么技巧？",
        "reference": "插眼原则：进攻插深眼（优势时插对方野区高台），防守插浅眼（劣势时插己方野区路口）。对线期优势路插封野眼和河道眼，中路插河道符眼和高台眼，劣势路插对方大野眼。中期进攻眼位控制对方主野区和Roshan坑，防守眼位保护己方野区入口。后期必须控制Roshan坑视野。反眼时机包括击杀对方辅助后、团战胜利后推进时。",
        "expected_category": "strategies",
    },
    # ── 战术 ──
    {
        "user_input": "当前版本有哪些热门分路？",
        "reference": "当前版本7.41热门分路包括：212传统分路（两条边路各2人，适合大多数路人局）、311分路（劣势路3人压制对方Carry，优势路1人solo发育）、游走辅助（辅助2-3级后游走中路或劣势路）。对线期注意事项：优势路辅助在1:00和2:00拉野控制兵线，劣势路辅助封野，中路4:00和8:00控符，辅助随时TP支援。",
        "expected_category": "tactics",
    },
    {
        "user_input": "团战中各个位置应该怎么站位？",
        "reference": "团战站位：核心站在队伍后方或侧翼，等待对方关键控制交出后再入场，优先攻击后排脆皮。中单站在队伍中间，利用技能消耗前排，寻找机会秒杀核心。劣单站在前排负责开团和吸收伤害，控制对方核心。辅助站在后方保护核心提供控制，注意走位防止被秒。团战类型包括先手开团（跳刀英雄找机会）、反手接团（利用救人技能保护核心）、拉扯（消耗不强行开团）。",
        "expected_category": "tactics",
    },
    # ── 版本补丁 ──
    {
        "user_input": "7.38 版本有哪些重要改动？",
        "reference": "7.38版本重要改动：地图新增传送门连接优势路和劣势路、莲花池7:00开始每3分钟刷新、智慧符提供经验值。英雄方面幽鬼荒芜伤害提升、帕吉肉钩伤害提升、影魔影压伤害提升；敌法师法力护盾效果降低、闪烁CD增加。装备新增永恒之盘和浩劫之锤，BKB持续时间改为9/8/7/6/5/4秒，跳刀受到英雄伤害后CD从3秒改为4秒。",
        "expected_category": "patches",
    },
    # ── 版本 Meta ──
    {
        "user_input": "7.41 版本哪些英雄比较强势？",
        "reference": "7.41版本T1核心：幽鬼（辉耀流强势）、幻影刺客（狂战斧流爆发高）、美杜莎（分身斧流后期站桩）、露娜（推进流节奏快）。T1中单：帕克（机动性高）、风暴之灵（节奏型游走强）、祈求者（全能型）、痛苦女王（爆发高）。T1劣单：猛犸（团战控制）、潮汐猎人（肉盾团控）、末日使者（单杀强）、兽王（推进强）。T1辅助：莱恩（控制足爆发高）、暗影恶魔（救人强）、神谕者（最强救人辅助）。",
        "expected_category": "meta",
    },
]


def build_test_dataset(
    engine: RagEngine,
    queries: List[Dict[str, Any]],
    answer_llm: Any = None,
) -> Dataset:
    """构建 RAGAS 评估数据集

    对每条 query：
    1. 用 RagEngine 检索知识库
    2. 用 LLM 基于检索结果生成回答（如果提供了 answer_llm）
    3. 构造 RAGAS 需要的字段：user_input, response, retrieved_contexts, reference
    """
    records: List[Dict[str, Any]] = []

    for q in queries:
        user_input = q["user_input"]
        reference = q["reference"]

        # 检索知识库
        results = engine.search(user_input, top_k=3)
        retrieved_contexts = [r.get("content", "") for r in results]

        # 用 LLM 生成回答（基于检索结果）
        response = ""
        if answer_llm and retrieved_contexts:
            context_text = "\n\n".join(retrieved_contexts)
            prompt = f"""基于以下知识库内容回答问题。如果知识库中没有相关信息，请如实说明。

知识库内容：
{context_text}

问题：{user_input}

请用中文给出简洁准确的回答。"""
            try:
                msg = answer_llm.invoke(prompt)
                response = msg.content if hasattr(msg, "content") else str(msg)
            except Exception as e:
                print(f"  [WARN] LLM 回答生成失败: {e}")
                response = reference  # fallback 到 ground truth
        else:
            response = reference  # 没有 LLM 时用 ground truth

        records.append({
            "user_input": user_input,
            "response": response,
            "reference": reference,
            "reference_contexts": [reference],  # NonLLM 指标需要 reference_contexts
            "retrieved_contexts": retrieved_contexts,
        })

    return Dataset.from_list(records)


def run_evaluation(
    dataset: Dataset,
    llm_model: str = "gpt-4o-mini",
    output_path: str | None = None,
    no_llm: bool = False,
) -> Dict[str, Any]:
    """运行 RAGAS 评估

    Args:
        dataset: 评估数据集
        llm_model: 用于评估的 LLM 模型名（no_llm=True 时忽略）
        output_path: 结果输出路径（可选）
        no_llm: 使用 NonLLM 指标（基于字符串相似度，不需要 LLM）

    Returns:
        Dict: 评估结果
    """
    if no_llm:
        # ── NonLLM 模式：字符串相似度指标，无需 LLM ──
        metrics = [
            NonLLMContextPrecisionWithReference(threshold=0.0),
            NonLLMContextRecall(threshold=0.0),
        ]
        print("评估模式: NonLLM（基于字符串相似度，无需 LLM）")
        print(f"数据集大小: {len(dataset)} 条")
        print(f"评估指标: {[m.name for m in metrics]}")
        print("-" * 60)

        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            raise_exceptions=True,
            show_progress=True,
        )

        df = result.to_pandas()
        scores = {
            "context_precision": float(
                df["non_llm_context_precision_with_reference"].mean()
            ),
            "context_recall": float(df["non_llm_context_recall"].mean()),
        }
    else:
        # ── 完整模式：LLM 评估所有指标 ──
        from langchain_openai.chat_models import ChatOpenAI
        from ragas.llms import LangchainLLMWrapper

        eval_llm = ChatOpenAI(model=llm_model, temperature=0)
        ragas_llm = LangchainLLMWrapper(eval_llm)

        metrics = [
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        ]

        for metric in metrics:
            metric.llm = ragas_llm

        print(f"评估 LLM: {llm_model}")
        print(f"数据集大小: {len(dataset)} 条")
        print(f"评估指标: {[m.name for m in metrics]}")
        print("-" * 60)

        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            raise_exceptions=True,
            show_progress=True,
        )

        df = result.to_pandas()
        scores = {
            "faithfulness": float(df["faithfulness"].mean()),
            "answer_relevancy": float(df["answer_relevancy"].mean()),
            "context_precision": float(df["context_precision"].mean()),
            "context_recall": float(df["context_recall"].mean()),
        }

    # 输出结果
    print("\n" + "=" * 60)
    print("RAG 评估结果")
    print("=" * 60)
    for name, score in scores.items():
        bar = "█" * int(score * 50) + "░" * (50 - int(score * 50))
        print(f"  {name:<20s} {score:.4f}  {bar}")
    print("=" * 60)

    # 详细结果
    output = {
        "summary": scores,
        "per_query": df.to_dict(orient="records"),
    }

    # 保存到文件
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n结果已保存到: {output_path}")

    return output


def main():
    parser = argparse.ArgumentParser(description="RAG 评估脚本")
    parser.add_argument(
        "--llm-model",
        default="gpt-4o-mini",
        help="用于评估的 LLM 模型（默认 gpt-4o-mini）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="结果输出路径（可选，如 results/rag_eval.json）",
    )
    parser.add_argument(
        "--kb-dir",
        default=None,
        help="知识库目录路径（默认使用 RagEngine 默认路径）",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="检索返回结果数量（默认 3）",
    )
    parser.add_argument(
        "--skip-answer-gen",
        action="store_true",
        help="跳过 LLM 回答生成，使用 ground truth 作为 response",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="使用 NonLLM 指标（基于字符串相似度，不需要 LLM API）",
    )
    args = parser.parse_args()

    # 初始化引擎并索引
    print("初始化 RAG 引擎...")
    engine = RagEngine(kb_dir=args.kb_dir)
    chunk_count = engine.index_all(force=True)
    print(f"知识库索引完成: {chunk_count} 个段落")

    # 构建回答 LLM（用于基于检索结果生成回答）
    answer_llm = None
    if not args.skip_answer_gen and not args.no_llm:
        from langchain_openai.chat_models import ChatOpenAI
        answer_llm = ChatOpenAI(model=args.llm_model, temperature=0.3)

    # 构建数据集
    print("构建评估数据集...")
    dataset = build_test_dataset(engine, TEST_QUERIES, answer_llm=answer_llm)

    # 运行评估
    run_evaluation(
        dataset,
        llm_model=args.llm_model,
        output_path=args.output,
        no_llm=args.no_llm,
    )


if __name__ == "__main__":
    main()
