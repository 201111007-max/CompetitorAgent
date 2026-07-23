"""通用数据格式化器

根据 YAML 声明的 data_requirements 将 MatchData 中的数据格式化为可读文本。
支持 player_stats / player_lane / list_items / simple / custom 五种格式。
"""
from typing import Any, Dict, List, Optional

from post_match_review.domain_types.match_data import MatchData
from post_match_review.observability.logger import get_logger

logger = get_logger("engines.data_formatter")


class DataFormatter:
    """根据 YAML 声明格式化 MatchData 中的数据为可读文本

    支持 player_stats / player_lane / list_items / simple / custom 五种格式。
    custom 格式跳过处理，由分析器 _format_domain_data() 自行处理。

    Attributes:
        LANE_NAMES: 分路编号到名称的映射（Laning/Teamfight 共用）
    """

    LANE_NAMES: Dict[int, str] = {
        1: "安全路（优势路）",
        2: "中路",
        3: "劣势路",
        4: "野区辅助",
        5: "游走辅助",
    }

    def __init__(
        self,
        data_requirements: List[Dict[str, Any]],
    ) -> None:
        """初始化数据格式化器

        Args:
            data_requirements: YAML 中的 data_requirements 列表，
                每项包含 field / label / format 等字段
        """
        self._requirements = data_requirements

    def format(self, match_data: MatchData) -> str:
        """根据声明格式化数据

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 格式化的数据文本，各需求之间以空行分隔
        """
        parts: List[str] = []
        player_map = self._build_player_map(match_data)

        for req in self._requirements:
            field_path: str = req["field"]
            label: str = req.get("label", field_path)
            fmt: str = req.get("format", "simple")

            # custom 格式跳过，由分析器自行处理
            if fmt == "custom":
                logger.debug("字段 %s 为 custom 格式，跳过", field_path)
                continue

            value = self._extract_field(match_data, field_path)
            if value is None:
                logger.debug("字段 %s 为 None，跳过", field_path)
                continue

            if fmt == "player_stats":
                parts.append(self._format_player_stats(req, value, player_map))
            elif fmt == "player_lane":
                parts.append(self._format_player_lane(label, value, player_map))
            elif fmt == "list_items":
                parts.append(self._format_list_items(req, value, player_map))
            elif fmt == "simple":
                parts.append(f"### {label}\n{value}")
            else:
                logger.warning("未知的格式类型: %s, 字段: %s", fmt, field_path)
                parts.append(f"### {label}\n{value}")

        return "\n\n".join(parts)

    def _extract_field(self, obj: Any, path: str) -> Any:
        """从嵌套对象中提取字段值

        支持点号分隔的路径（如 lane_data.lh_at_10），
        同时支持 dataclass 属性和 dict 键访问。

        Args:
            obj: 根对象
            path: 字段路径，点号分隔

        Returns:
            Any: 提取的值，路径不存在时返回 None
        """
        current = obj
        for key in path.split("."):
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(key)
            else:
                current = getattr(current, key, None)
        return current

    def _build_player_map(self, match_data: MatchData) -> Dict[str, str]:
        """构建玩家 ID 到英雄名称的映射

        Args:
            match_data: 结构化比赛数据

        Returns:
            Dict[str, str]: account_id -> hero_name 映射
        """
        return {
            p.account_id: p.hero_name
            for p in match_data.players
            if p.account_id
        }

    def _format_player_stats(
        self,
        req: Dict[str, Any],
        data: Dict[str, Any],
        player_map: Dict[str, str],
    ) -> str:
        """格式化玩家统计数据

        支持主字段 + 可选的 secondary_field（如补刀 + 反补联合输出）。

        Args:
            req: 数据需求声明
            data: 主字段数据（account_id -> value）
            player_map: 玩家映射

        Returns:
            str: 格式化的文本
        """
        label: str = req.get("label", "")
        value_suffix: str = req.get("value_suffix", "")
        secondary_field_path: Optional[str] = req.get("secondary_field")
        secondary_label: str = req.get("secondary_label", "")
        secondary_suffix: str = req.get("secondary_suffix", "")

        lines: List[str] = [f"### {label}"]
        for account_id, value in data.items():
            hero_name = player_map.get(account_id, account_id)
            line = f"- {hero_name}: {value}"
            if value_suffix:
                line += f" {value_suffix}"

            # 处理 secondary_field（如反补数）
            if secondary_field_path and secondary_label:
                secondary_parts = secondary_field_path.split(".")
                # secondary_field 的值需要从 match_data 中提取
                # 但这里只有 data（主字段数据），无法直接获取
                # 因此 secondary_field 需要通过额外逻辑处理
                # 当前实现：在 format() 中预提取 secondary 数据
                pass

            lines.append(line)
        return "\n".join(lines)

    def _format_player_stats_with_secondary(
        self,
        req: Dict[str, Any],
        primary_data: Dict[str, Any],
        secondary_data: Dict[str, Any],
        player_map: Dict[str, str],
    ) -> str:
        """格式化玩家统计数据（带 secondary 字段联合输出）

        Args:
            req: 数据需求声明
            primary_data: 主字段数据（account_id -> value）
            secondary_data: 次字段数据（account_id -> value）
            player_map: 玩家映射

        Returns:
            str: 格式化的文本
        """
        label: str = req.get("label", "")
        value_suffix: str = req.get("value_suffix", "")
        secondary_label: str = req.get("secondary_label", "")
        secondary_suffix: str = req.get("secondary_suffix", "")

        lines: List[str] = [f"### {label}"]
        for account_id, value in primary_data.items():
            hero_name = player_map.get(account_id, account_id)
            secondary_value = secondary_data.get(account_id, 0)
            line = f"- {hero_name}: {value_suffix} {value}, {secondary_label} {secondary_value}"
            lines.append(line)
        return "\n".join(lines)

    def _format_player_lane(
        self,
        label: str,
        data: Dict[str, int],
        player_map: Dict[str, str],
    ) -> str:
        """格式化分路信息

        Args:
            label: 标题
            data: account_id -> lane 编号映射
            player_map: 玩家映射

        Returns:
            str: 格式化的分路文本
        """
        lines: List[str] = [f"### {label}"]
        for account_id, lane in data.items():
            hero_name = player_map.get(account_id, account_id)
            lane_name = self.LANE_NAMES.get(lane, f"未知分路 ({lane})")
            lines.append(f"- {hero_name}: {lane_name}")
        return "\n".join(lines)

    def _format_list_items(
        self,
        req: Dict[str, Any],
        data: List[Any],
        player_map: Dict[str, str],
    ) -> str:
        """格式化列表项数据（如团战列表）

        支持 dict 列表和 dataclass 对象列表。
        每个列表项按照 fields 声明格式化输出。

        Args:
            req: 数据需求声明
            data: 列表数据
            player_map: 玩家映射

        Returns:
            str: 格式化的列表文本
        """
        label: str = req.get("label", "")
        fields: List[Dict[str, Any]] = req.get("fields", [])

        lines: List[str] = [f"### {label}"]

        for i, item in enumerate(data, 1):
            item_lines: List[str] = []

            if isinstance(item, dict):
                # dict 类型：使用字典键访问
                for field_def in fields:
                    source: str = field_def["source"]
                    field_label: str = field_def.get("label", source)
                    raw_value = item.get(source)
                    transform: Optional[str] = field_def.get("transform")
                    value = self._apply_transform(
                        raw_value, transform, player_map, field_def,
                    )
                    if field_label:
                        item_lines.append(f"- {field_label}: {value}")
            else:
                # dataclass 对象：使用属性访问
                for field_def in fields:
                    source: str = field_def["source"]
                    field_label: str = field_def.get("label", source)
                    raw_value = getattr(item, source, None)
                    transform: Optional[str] = field_def.get("transform")
                    value = self._apply_transform(
                        raw_value, transform, player_map, field_def,
                    )
                    if field_label:
                        item_lines.append(f"- {field_label}: {value}")

            # 构建标题行（使用第一个 time_minutes/time_seconds 组合）
            title_parts: List[str] = []
            for field_def in fields:
                transform = field_def.get("transform")
                if transform == "time_minutes" and isinstance(item, dict):
                    title_parts.append(str(item.get(field_def["source"], 0) // 60))
                elif transform == "time_minutes":
                    title_parts.append(str(getattr(item, field_def["source"], 0) // 60))
                elif transform == "time_seconds":
                    if isinstance(item, dict):
                        title_parts.append(f"{item.get(field_def['source'], 0) % 60:02d}")
                    else:
                        title_parts.append(f"{getattr(item, field_def['source'], 0) % 60:02d}")

            if title_parts:
                # 有时间字段，构建带时间的标题
                duration_val = None
                end_field = next(
                    (f for f in fields if f["source"] == "end"), None
                )
                if end_field:
                    start_val = item.get("start", 0) if isinstance(item, dict) else getattr(item, "start", 0)
                    end_val = item.get("end", 0) if isinstance(item, dict) else getattr(item, "end", 0)
                    duration_val = end_val - start_val

                title = f"项目 {i} ({':'.join(title_parts)}"
                if duration_val is not None:
                    title += f", 持续 {duration_val}s"
                title += ")"
                lines.append(f"#### {title}")
            else:
                lines.append(f"#### 项目 {i}")

            lines.extend(item_lines)
            lines.append("")

        return "\n".join(lines)

    def _apply_transform(
        self,
        value: Any,
        transform: Optional[str],
        player_map: Dict[str, str],
        field_def: Dict[str, Any],
    ) -> str:
        """应用值变换

        Args:
            value: 原始值
            transform: 变换类型（time_minutes/time_seconds/player_names/signed_int）
            player_map: 玩家映射
            field_def: 字段定义

        Returns:
            str: 变换后的字符串
        """
        if transform is None or value is None:
            return str(value) if value is not None else ""

        if transform == "time_minutes":
            return str(int(value) // 60)
        elif transform == "time_seconds":
            return f"{int(value) % 60:02d}"
        elif transform == "player_names":
            max_items: int = field_def.get("max_items", 10)
            if isinstance(value, list):
                names = [player_map.get(str(pid), str(pid)) for pid in value[:max_items]]
                return ", ".join(names)
            return str(value)
        elif transform == "signed_int":
            return f"{int(value):+d}"

        return str(value)

    @staticmethod
    def has_declarative_requirements(template: Dict[str, Any]) -> bool:
        """判断模板是否包含可由 DataFormatter 处理的声明

        Args:
            template: YAML 模板内容

        Returns:
            bool: 是否包含非 custom 的 data_requirements
        """
        requirements = template.get("data_requirements", [])
        return any(
            req.get("format", "simple") != "custom"
            for req in requirements
        )

    def format_with_secondary(
        self,
        match_data: MatchData,
    ) -> str:
        """根据声明格式化数据（支持 secondary_field 联合输出）

        与 format() 不同，此方法支持在 player_stats 格式中
        联合输出主字段和 secondary_field 的数据。

        Args:
            match_data: 结构化比赛数据

        Returns:
            str: 格式化的数据文本
        """
        parts: List[str] = []
        player_map = self._build_player_map(match_data)

        for req in self._requirements:
            field_path: str = req["field"]
            label: str = req.get("label", field_path)
            fmt: str = req.get("format", "simple")

            # custom 格式跳过
            if fmt == "custom":
                logger.debug("字段 %s 为 custom 格式，跳过", field_path)
                continue

            value = self._extract_field(match_data, field_path)
            if value is None:
                logger.debug("字段 %s 为 None，跳过", field_path)
                continue

            if fmt == "player_stats":
                # 检查是否有 secondary_field
                secondary_field_path: Optional[str] = req.get("secondary_field")
                if secondary_field_path:
                    secondary_data = self._extract_field(match_data, secondary_field_path)
                    if secondary_data and isinstance(secondary_data, dict):
                        parts.append(
                            self._format_player_stats_with_secondary(
                                req, value, secondary_data, player_map,
                            )
                        )
                        continue
                parts.append(self._format_player_stats(req, value, player_map))
            elif fmt == "player_lane":
                parts.append(self._format_player_lane(label, value, player_map))
            elif fmt == "list_items":
                parts.append(self._format_list_items(req, value, player_map))
            elif fmt == "simple":
                parts.append(f"### {label}\n{value}")
            else:
                logger.warning("未知的格式类型: %s, 字段: %s", fmt, field_path)
                parts.append(f"### {label}\n{value}")

        return "\n\n".join(parts)
