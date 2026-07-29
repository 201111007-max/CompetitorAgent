"""统一数据路径管理 — 集中管理所有运行时数据路径

所有用户产生的动态数据统一存放于 ~/.dota_helper/data/，
包内静态数据（如内置技能）留在包内随代码分发。

目录结构：
~/.dota_helper/data/
├── memory/               # Level 1-2: 记忆持久化 (SQLite + JSON)
├── skills/               # Level 3: 用户自定义技能 (YAML)
├── sessions/             # ReAct Agent 会话持久化
├── reviews/              # 复盘报告持久化
├── progress/             # 进度恢复快照
├── cache/                # 比赛数据缓存
└── ward_analysis/        # Ward HTML 输出
"""
from pathlib import Path
from typing import Optional

from dota_helper.observability.logger import get_logger

logger = get_logger("data_path_manager")

# 默认数据根目录
DEFAULT_DATA_DIR = Path.home() / ".dota_helper" / "data"


class DataPathManager:
    """统一数据路径管理

    集中管理所有运行时数据路径，确保目录存在，提供统一的路径入口。

    Args:
        data_dir: 数据根目录，默认为 ~/.dota_helper/data/
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        """初始化数据路径管理器

        Args:
            data_dir: 数据根目录路径（字符串或 None），
                     None 时使用默认路径 ~/.dota_helper/data/
        """
        if data_dir is not None:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = DEFAULT_DATA_DIR

    @property
    def data_dir(self) -> Path:
        """用户数据根目录

        Returns:
            Path: 数据根目录路径
        """
        return self._data_dir

    @property
    def memory_dir(self) -> Path:
        """记忆持久化目录 (Level 1-2: SQLite + JSON)

        Returns:
            Path: memory 目录路径
        """
        return self._data_dir / "memory"

    @property
    def skills_dir(self) -> Path:
        """用户自定义技能目录 (Level 3: YAML)

        Returns:
            Path: skills 目录路径
        """
        return self._data_dir / "skills"

    @property
    def sessions_dir(self) -> Path:
        """ReAct Agent 会话持久化目录

        Returns:
            Path: sessions 目录路径
        """
        return self._data_dir / "sessions"

    @property
    def reviews_dir(self) -> Path:
        """复盘报告持久化目录

        Returns:
            Path: reviews 目录路径
        """
        return self._data_dir / "reviews"

    @property
    def progress_dir(self) -> Path:
        """进度恢复快照目录

        Returns:
            Path: progress 目录路径
        """
        return self._data_dir / "progress"

    @property
    def cache_dir(self) -> Path:
        """比赛数据缓存目录

        Returns:
            Path: cache 目录路径
        """
        return self._data_dir / "cache"

    @property
    def ward_analysis_dir(self) -> Path:
        """Ward HTML 输出目录

        Returns:
            Path: ward_analysis 目录路径
        """
        return self._data_dir / "ward_analysis"

    def ensure_dirs(self) -> None:
        """确保所有数据目录存在

        创建所有必要的数据子目录（如果不存在）。
        """
        dirs = [
            self.memory_dir,
            self.skills_dir,
            self.sessions_dir,
            self.reviews_dir,
            self.progress_dir,
            self.cache_dir,
            self.ward_analysis_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        logger.debug("数据目录已确保存在: %s", self._data_dir)

    def get_review_path(self, match_id: str) -> Path:
        """获取复盘报告文件路径

        Args:
            match_id: 比赛 ID

        Returns:
            Path: 报告文件路径
        """
        return self.reviews_dir / f"{match_id}.json"

    def get_progress_path(self, match_id: str) -> Path:
        """获取进度快照文件路径

        Args:
            match_id: 比赛 ID

        Returns:
            Path: 进度文件路径
        """
        return self.progress_dir / f"{match_id}.json"

    def get_cache_path(self, match_id: str) -> Path:
        """获取比赛数据缓存文件路径

        Args:
            match_id: 比赛 ID

        Returns:
            Path: 缓存文件路径
        """
        return self.cache_dir / f"{match_id}.json"

    def get_session_path(self, session_id: str) -> Path:
        """获取会话文件路径

        Args:
            session_id: 会话 ID

        Returns:
            Path: 会话文件路径
        """
        return self.sessions_dir / f"{session_id}.json"
