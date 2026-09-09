"""Domain Pack（设计文档 79，工单 5）：领域可插拔的配置模型与加载器。

6 个维度子 Agent 的定义从硬编码 dict 下沉为 yaml（``config/domains/<pack>.yaml``），
并同步解耦三处领域渗漏：L1 子 Agent 注册表 / L2 竞品品类与注册表 / L3 维度枚举。

**留双保险**（doc 79 §2.2）：yaml 缺失/损坏时回退代码内 coding_agent 内联默认
（行为与现状逐位一致）；pack 段缺失/畸形 → 可读错误（不静默半装配，doc 79 §4.4）。

「yaml 能加载」≠ 可插拔——验收是第二个领域（saas_pm）全链路独立出报告且
零领域渗漏（doc 79 §4.2/§4.3）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from competitor_agent.observability.logger import get_logger

logger = get_logger("core.domain_pack")

# pack 目录（config/domains/；环境变量 COMPETITOR_AGENT_DOMAINS_DIR 可覆盖，测试用）
_DOMAINS_DIR_ENV = "COMPETITOR_AGENT_DOMAINS_DIR"
DEFAULT_DOMAINS_DIR = Path(__file__).resolve().parent.parent / "config" / "domains"

DEFAULT_ACTIVE_PACK = "coding_agent"


@dataclass(frozen=True)
class DimensionSpec:
    """单个维度子 Agent 的 pack 声明（L1 下沉）。"""

    name: str
    description: str = ""
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    data_sources: tuple[dict[str, str], ...] = ()  # 声明式数据源清单（供 prompt 引用）


@dataclass(frozen=True)
class RegistrySeed:
    """预注册竞品条目（L2 解耦：随 pack 提供）。"""

    name: str
    aliases: tuple[str, ...] = ()
    official_links: dict[str, str] = field(default_factory=dict)
    external_refs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DomainPack:
    """一个领域包：维度 + 注册表种子 + 权重 + 品类标签。"""

    domain: str
    category_label: str = ""
    dimensions: tuple[DimensionSpec, ...] = ()
    registry_seeds: tuple[RegistrySeed, ...] = ()
    default_dimension_weights: dict[str, float] = field(default_factory=dict)

    @property
    def dimension_names(self) -> list[str]:
        return [d.name for d in self.dimensions]

    def dimension(self, name: str) -> DimensionSpec | None:
        for d in self.dimensions:
            if d.name == name:
                return d
        return None


def _domains_dir() -> Path:
    override = os.environ.get(_DOMAINS_DIR_ENV)
    return Path(override) if override else DEFAULT_DOMAINS_DIR


def load_domain_pack(name: str, domains_dir: Path | str | None = None) -> DomainPack:
    """加载指定 pack yaml；文件缺失/段缺失 → 可读错误（doc 79 §4.4 不静默半装配）。"""
    directory = Path(domains_dir) if domains_dir else _domains_dir()
    path = directory / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Domain pack 不存在: {path}（可用 pack 见 {directory}）")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Domain pack YAML 解析失败: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError(f"Domain pack 格式非法（须为映射）: {path}")
    domain = str(data.get("domain") or "").strip()
    if not domain:
        raise ValueError(f"Domain pack 缺少 domain 字段: {path}")
    raw_dims = data.get("dimensions")
    if not isinstance(raw_dims, list) or not raw_dims:
        raise ValueError(f"Domain pack 缺少 dimensions 段（至少 1 个维度）: {path}")
    dimensions: list[DimensionSpec] = []
    for raw in raw_dims:
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            raise ValueError(f"Domain pack dimensions 条目缺少 name: {path}")
        dimensions.append(
            DimensionSpec(
                name=str(raw["name"]).strip(),
                description=str(raw.get("description") or ""),
                tools=tuple(str(t) for t in (raw.get("tools") or [])),
                skills=tuple(str(s) for s in (raw.get("skills") or [])),
                data_sources=tuple(
                    {str(k): str(v) for k, v in ds.items()}
                    for ds in (raw.get("data_sources") or [])
                    if isinstance(ds, dict)
                ),
            )
        )
    names = [d.name for d in dimensions]
    if len(set(names)) != len(names):
        raise ValueError(f"Domain pack 维度名重复: {path}（{names}）")
    raw_seeds = data.get("registry_seeds")
    if not isinstance(raw_seeds, list) or not raw_seeds:
        raise ValueError(f"Domain pack 缺少 registry_seeds 段（至少 1 个竞品）: {path}")
    seeds: list[RegistrySeed] = []
    for raw in raw_seeds:
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            raise ValueError(f"Domain pack registry_seeds 条目缺少 name: {path}")
        seeds.append(
            RegistrySeed(
                name=str(raw["name"]).strip(),
                aliases=tuple(str(a) for a in (raw.get("aliases") or [])),
                official_links={
                    str(k): str(v) for k, v in (raw.get("official_links") or {}).items()
                },
                external_refs={
                    str(k): str(v) for k, v in (raw.get("external_refs") or {}).items()
                },
            )
        )
    weights_raw = data.get("default_dimension_weights") or {}
    weights = {str(k): float(v) for k, v in weights_raw.items() if isinstance(v, (int, float))}
    return DomainPack(
        domain=domain,
        category_label=str(data.get("category_label") or ""),
        dimensions=tuple(dimensions),
        registry_seeds=tuple(seeds),
        default_dimension_weights=weights,
    )


def active_domain_pack(config: Any = None, domains_dir: Path | str | None = None) -> DomainPack:
    """按激活配置加载 pack；失败回退内联 coding 默认（行为与现状逐位一致，doc 79 §2.2）。"""
    name = active_pack_name(config)
    try:
        return load_domain_pack(name, domains_dir)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("Domain pack 加载失败（回退内联 coding 默认）: %s", exc)
        return _inline_coding_pack()


def _inline_coding_pack() -> DomainPack:
    """yaml 缺失时的兜底：coding_agent 内联默认（与 yaml 下沉前逐位一致）。"""
    from competitor_agent.agent.subagent_registry_defaults import CODING_DIMENSIONS

    return CODING_DIMENSIONS


# 模块级激活覆盖（测试/运行时切换；优先于 env 与 config）
_ACTIVE_PACK_OVERRIDE: str | None = None


def set_active_pack(name: str) -> None:
    """运行时切换激活 pack（同步重建注册表/子 Agent 注册表/技能加载器缓存）。"""
    global _ACTIVE_PACK_OVERRIDE
    _ACTIVE_PACK_OVERRIDE = name
    pack = load_domain_pack(name)
    from competitor_agent.agent.subagent_registry import reset_subagent_registry
    from competitor_agent.core import competitor_registry
    from competitor_agent.skills.loader import reset_skill_loader

    competitor_registry.reload_registry_from_pack(pack)
    reset_subagent_registry()
    reset_skill_loader()
    logger.info("DomainPack 已切换: %s（category=%s, dims=%s）",
                name, pack.category_label, pack.dimension_names)


def active_pack_name(config: Any = None) -> str:
    """激活 pack 名：模块覆盖 > env > config.domains.active_pack（缺省 coding_agent）。"""
    if _ACTIVE_PACK_OVERRIDE:
        return _ACTIVE_PACK_OVERRIDE
    env = os.environ.get("COMPETITOR_AGENT_ACTIVE_PACK")
    if env and env.strip():
        return env.strip()
    if config is not None:
        return str(getattr(getattr(config, "domains", None), "active_pack", "") or DEFAULT_ACTIVE_PACK)
    try:
        from competitor_agent.config.loader import load_config

        return str(load_config().domains.active_pack or DEFAULT_ACTIVE_PACK)
    except Exception:  # noqa: BLE001 — 配置不可用时回退默认 pack（不炸导入方）
        return DEFAULT_ACTIVE_PACK


__all__ = [
    "DEFAULT_DOMAINS_DIR",
    "DimensionSpec",
    "DomainPack",
    "RegistrySeed",
    "active_domain_pack",
    "active_pack_name",
    "load_domain_pack",
    "set_active_pack",
]
