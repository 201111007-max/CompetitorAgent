"""进度快照持久化存储

在复盘过程中定期保存 ReviewAgentState 快照，
支持中断后从最近快照恢复，避免重新分析。
"""
import json
from pathlib import Path
from typing import Optional

from dota_helper.data_path_manager import DataPathManager
from dota_helper.domain_types.state import ReviewAgentState
from dota_helper.observability.logger import get_logger

logger = get_logger("persistence.progress_store")


class ProgressStore:
    """进度快照持久化存储

    将 ReviewAgentState 序列化为 JSON 并存储到 DataPathManager.progress_dir。
    每次复盘的进度保存为 {match_id}.json。

    Args:
        path_manager: 统一数据路径管理器
    """

    def __init__(self, path_manager: DataPathManager) -> None:
        """初始化进度存储

        Args:
            path_manager: 统一数据路径管理器
        """
        self._path_manager = path_manager

    async def save_snapshot(self, state: ReviewAgentState) -> Path:
        """保存进度快照

        Args:
            state: 复盘 Agent 状态

        Returns:
            Path: 保存的文件路径
        """
        path = self._path_manager.get_progress_path(state.match_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = state.to_dict()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(
                "进度快照保存成功: match_id=%s, completed_phases=%d, confidence=%.2f",
                state.match_id,
                len(state.completed_phases),
                state.confidence,
            )
            return path
        except Exception as e:
            logger.error("进度快照保存失败: match_id=%s, error=%s", state.match_id, str(e))
            raise

    async def load_snapshot(self, match_id: str) -> Optional[ReviewAgentState]:
        """加载最近进度快照

        Args:
            match_id: 比赛 ID

        Returns:
            Optional[ReviewAgentState]: 恢复的状态实例，不存在时返回 None
        """
        path = self._path_manager.get_progress_path(match_id)
        if not path.exists():
            logger.debug("进度快照不存在: match_id=%s", match_id)
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = ReviewAgentState.from_dict(data)
            logger.info(
                "进度快照加载成功: match_id=%s, completed_phases=%d, confidence=%.2f",
                match_id,
                len(state.completed_phases),
                state.confidence,
            )
            return state
        except Exception as e:
            logger.error("进度快照加载失败: match_id=%s, error=%s", match_id, str(e))
            return None

    async def clear_snapshot(self, match_id: str) -> None:
        """清除进度快照（复盘完成后清理）

        Args:
            match_id: 比赛 ID
        """
        path = self._path_manager.get_progress_path(match_id)
        if path.exists():
            try:
                path.unlink()
                logger.info("进度快照已清除: match_id=%s", match_id)
            except Exception as e:
                logger.warning("进度快照清除失败: match_id=%s, error=%s", match_id, str(e))
        else:
            logger.debug("进度快照不存在，无需清除: match_id=%s", match_id)

    async def has_snapshot(self, match_id: str) -> bool:
        """检查进度快照是否存在

        Args:
            match_id: 比赛 ID

        Returns:
            bool: 快照是否存在
        """
        return self._path_manager.get_progress_path(match_id).exists()
