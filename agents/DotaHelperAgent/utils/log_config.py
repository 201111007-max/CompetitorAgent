"""日志配置模块

基于 Python 内置 logging 的日志系统，支持：
1. 按日期分文件夹：logs/2026-04-29/
2. 同一天内按 300MB 分文件夹：logs/2026-04-29/part-1/, logs/2026-04-29/part-2/
3. 文件持久化和前端实时展示
"""

import logging
import logging.handlers
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from collections import defaultdict
import threading

# 日志根目录
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# 每天内每个分片的最大大小 (300MB)
DAILY_PART_MAX_BYTES = 300 * 1024 * 1024


class SessionFilter(logging.Filter):
    """会话过滤器 - 添加 session_id 和 component 到日志记录"""
    def filter(self, record):
        record.session_id = getattr(record, 'session_id', 'global')
        record.component = getattr(record, 'component', 'system')
        return True


class JSONFormatter(logging.Formatter):
    """JSON 格式格式化器"""
    def format(self, record):
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "session_id": getattr(record, 'session_id', 'global'),
            "component": getattr(record, 'component', 'system')
        }
        if hasattr(record, 'extra_data'):
            log_data['extra'] = record.extra_data
        return json.dumps(log_data, ensure_ascii=False)


class DailyPartitionRotatingHandler(logging.handlers.RotatingFileHandler):
    """
    按日期分文件夹 + 同一天内按大小分文件夹的日志处理器

    文件夹结构：
    logs/
    ├── 2026-04-29/
    │   ├── part-1/
    │   │   ├── app.log
    │   │   ├── agent.log
    │   │   └── ...
    │   ├── part-2/
    │   │   ├── app.log
    │   │   └── ...
    │   └── part-3/
    │       └── ...
    ├── 2026-04-30/
    │   ├── part-1/
    │   └── ...
    """

    def __init__(self, filename, maxBytes=DAILY_PART_MAX_BYTES, encoding='utf-8'):
        self.base_filename = filename
        self.maxBytes = maxBytes
        self.encoding = encoding
        self.current_date = datetime.now().strftime('%Y-%m-%d')
        self.current_part = 1
        self._lock = threading.RLock()

        # 初始化第一个日志文件
        log_path = self._get_log_path()
        super().__init__(log_path, maxBytes=maxBytes, backupCount=0, encoding=encoding)

    def _get_log_path(self):
        """获取当前应该写入的日志文件路径"""
        date_dir = LOG_DIR / self.current_date
        part_dir = date_dir / f"part-{self.current_part}"
        part_dir.mkdir(parents=True, exist_ok=True)
        return part_dir / self.base_filename

    def _should_roll_over(self, record):
        """检查是否需要滚动到新文件"""
        # 检查日期是否变化
        new_date = datetime.now().strftime('%Y-%m-%d')
        if new_date != self.current_date:
            self.current_date = new_date
            self.current_part = 1
            return True

        # 检查当前文件大小
        if self.stream is None:
            self.stream = self._open()

        msg = "%s\n" % self.format(record)
        self.stream.seek(0, 2)  # 移动到文件末尾
        if self.stream.tell() + len(msg.encode(self.encoding)) >= self.maxBytes:
            # 当前分片已满，创建新的分片
            self.current_part += 1
            return True

        return False

    def doRollover(self):
        """执行日志滚动"""
        with self._lock:
            if self.stream:
                self.stream.close()
                self.stream = None

            # 获取新的日志路径
            self.baseFilename = str(self._get_log_path())
            self.stream = self._open()

    def emit(self, record):
        """发送日志记录"""
        try:
            if self._should_roll_over(record):
                self.doRollover()
            super().emit(record)
        except Exception:
            self.handleError(record)


class DailyTimedRotatingHandler(logging.handlers.BaseRotatingHandler):
    """
    按日期分文件夹的日志处理器（每天一个文件夹，内部按大小分片）
    """

    def __init__(self, filename, when='midnight', interval=1, maxBytes=DAILY_PART_MAX_BYTES,
                 encoding='utf-8', utc=False, atTime=None):
        self.maxBytes = maxBytes
        self.current_part = 1
        self._size_counter = 0
        self._lock = threading.RLock()
        self._filename = filename  # 保存原始文件名

        # 计算下一次轮转时间
        self.when = when
        self.interval = interval
        self.utc = utc
        self.atTime = atTime

        # 初始化文件路径
        log_path = self._get_log_path()

        # 调用父类初始化
        super().__init__(log_path, 'a', encoding=encoding)

        # 计算下一次轮转时间
        self.rolloverAt = self.computeRollover(int(datetime.now().timestamp()))

    def _get_log_path(self):
        """获取当前应该写入的日志文件路径"""
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        date_dir = LOG_DIR / date_str
        part_dir = date_dir / f"part-{self.current_part}"
        part_dir.mkdir(parents=True, exist_ok=True)
        return part_dir / self._filename

    def computeRollover(self, currentTime):
        """计算下一次轮转时间"""
        if self.when == 'midnight':
            # 获取明天凌晨的时间
            t = datetime.fromtimestamp(currentTime)
            tomorrow = t.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            return int(tomorrow.timestamp())
        else:
            # 默认每天轮转
            return currentTime + 86400

    def shouldRollover(self, record):
        """检查是否需要滚动"""
        with self._lock:
            now = int(datetime.now().timestamp())

            # 检查是否需要按时间轮转（新的一天）
            if now >= self.rolloverAt:
                self.current_part = 1
                self._size_counter = 0
                self.rolloverAt = self.computeRollover(now)
                return 1

            # 检查是否需要按大小轮转
            if self.stream is None:
                self.stream = self._open()

            msg = "%s\n" % self.format(record)
            msg_size = len(msg.encode(self.encoding))

            if self._size_counter + msg_size >= self.maxBytes:
                self.current_part += 1
                self._size_counter = 0
                return 1

            self._size_counter += msg_size
            return 0

    def doRollover(self):
        """执行日志滚动"""
        with self._lock:
            if self.stream:
                self.stream.close()
                self.stream = None

            # 获取新的日志路径
            self.baseFilename = str(self._get_log_path())
            self.stream = self._open()

    def emit(self, record):
        """发送日志记录"""
        try:
            if self.shouldRollover(record):
                self.doRollover()
            logging.FileHandler.emit(self, record)
        except Exception:
            self.handleError(record)


def setup_logging(
    log_level: str = "INFO",
    daily_max_bytes: int = DAILY_PART_MAX_BYTES,
    console_output: bool = True
):
    """
    配置日志系统（按日期分文件夹 + 同一天内按大小分文件夹）

    Args:
        log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        daily_max_bytes: 每天内每个分片的最大大小（默认 300MB）
        console_output: 是否输出到控制台

    Returns:
        配置好的根日志记录器
    """

    # 根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # 清除现有处理器
    root_logger.handlers = []

    # 添加会话过滤器
    session_filter = SessionFilter()
    root_logger.addFilter(session_filter)

    # === 1. 控制台处理器 (开发调试) ===
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_formatter = logging.Formatter(LOG_FORMAT)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

    # === 2. 文件处理器 - 普通文本日志（按日期+大小分文件夹） ===
    text_handler = DailyTimedRotatingHandler(
        "app.log",
        when='midnight',
        interval=1,
        maxBytes=daily_max_bytes,
        encoding='utf-8'
    )
    text_handler.setLevel(logging.INFO)
    text_formatter = logging.Formatter(LOG_FORMAT)
    text_handler.setFormatter(text_formatter)
    root_logger.addHandler(text_handler)

    # === 3. 文件处理器 - JSON 格式 ===
    json_handler = DailyTimedRotatingHandler(
        "app.json.log",
        when='midnight',
        interval=1,
        maxBytes=daily_max_bytes,
        encoding='utf-8'
    )
    json_handler.setLevel(logging.DEBUG)
    json_formatter = JSONFormatter()
    json_handler.setFormatter(json_formatter)
    root_logger.addHandler(json_handler)

    # === 4. 错误日志单独文件 ===
    error_handler = DailyTimedRotatingHandler(
        "error.log",
        when='midnight',
        interval=1,
        maxBytes=daily_max_bytes,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(text_formatter)
    root_logger.addHandler(error_handler)

    # === 5. 按组件分离日志 ===
    components = ['agent', 'tool', 'cache', 'api', 'web']
    for comp in components:
        comp_handler = DailyTimedRotatingHandler(
            f"{comp}.log",
            when='midnight',
            interval=1,
            maxBytes=daily_max_bytes,
            encoding='utf-8'
        )
        comp_handler.setLevel(logging.DEBUG)

        # 添加过滤器，只记录该组件的日志
        class ComponentFilter(logging.Filter):
            def __init__(self, component):
                super().__init__()
                self.component = component

            def filter(self, record):
                return getattr(record, 'component', '') == self.component

        comp_handler.addFilter(ComponentFilter(comp))
        comp_handler.setFormatter(text_formatter)
        root_logger.addHandler(comp_handler)

    # 创建日志目录结构说明
    _create_log_readme()

    return root_logger


def _create_log_readme():
    """创建日志目录说明文件"""
    readme_path = LOG_DIR / "README.md"
    if not readme_path.exists():
        readme_content = """# 日志文件说明

## 文件夹结构

```
logs/
├── 2026-04-29/              # 日期文件夹
│   ├── part-1/              # 第1个300MB分片
│   │   ├── app.log          # 主应用日志
│   │   ├── app.json.log     # 结构化日志
│   │   ├── error.log        # 错误日志
│   │   ├── agent.log        # Agent 组件日志
│   │   ├── tool.log         # 工具调用日志
│   │   ├── cache.log        # 缓存操作日志
│   │   ├── api.log          # API 请求日志
│   │   └── web.log          # Web 服务日志
│   ├── part-2/              # 第2个300MB分片（当日志超过300MB时创建）
│   └── part-3/              # 第3个300MB分片
├── 2026-04-30/              # 新的一天
│   └── part-1/
└── ...
```

## 轮转规则

1. **按日期轮转**：每天凌晨自动创建新的日期文件夹
2. **按大小轮转**：同一天内，当日志达到 300MB 时，自动创建新的 part-N 文件夹
3. **文件命名**：保持简单，便于查找

## 日志级别

- DEBUG: 调试信息
- INFO: 一般信息
- WARNING: 警告
- ERROR: 错误
- CRITICAL: 严重错误

## 使用建议

1. 按日期查找：先进入对应日期的文件夹
2. 按时间段查找：同一日期内，part-1 是当天的早期日志，part-N 是后期的日志
3. 清理策略：可以安全删除旧的日期文件夹
"""
        readme_path.write_text(readme_content, encoding='utf-8')


def get_logger(name: str, component: str = "system") -> logging.Logger:
    """
    获取配置好的日志记录器

    Args:
        name: 日志记录器名称
        component: 组件标识 (agent/tool/cache/api/web)

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)

    # 添加组件标识方法
    def _log_with_context(level, msg, session_id=None, extra_data=None, *args, **kwargs):
        extra = {
            'session_id': session_id or 'global',
            'component': component
        }
        if extra_data:
            extra['extra_data'] = extra_data
        getattr(logger, level)(msg, extra=extra, *args, **kwargs)

    # 绑定便捷方法
    logger.debug_ctx = lambda msg, session_id=None, extra_data=None: _log_with_context('debug', msg, session_id, extra_data)
    logger.info_ctx = lambda msg, session_id=None, extra_data=None: _log_with_context('info', msg, session_id, extra_data)
    logger.warning_ctx = lambda msg, session_id=None, extra_data=None: _log_with_context('warning', msg, session_id, extra_data)
    logger.error_ctx = lambda msg, session_id=None, extra_data=None: _log_with_context('error', msg, session_id, extra_data)

    return logger


def setup_logging_with_memory(
    log_level: str = "INFO",
    daily_max_bytes: int = DAILY_PART_MAX_BYTES,
    memory_max_entries: int = 1000,
    console_output: bool = True
):
    """
    配置完整的日志系统（文件 + 内存）

    Args:
        log_level: 日志级别
        daily_max_bytes: 每天内每个分片的最大大小
        memory_max_entries: 内存缓存最大条目数
        console_output: 是否输出到控制台

    Returns:
        (根日志记录器, 内存处理器)
    """
    from utils.memory_log_handler import get_memory_handler

    # 基础配置
    root_logger = setup_logging(log_level, daily_max_bytes, console_output)

    # 添加内存处理器（用于前端展示）
    memory_handler = get_memory_handler(memory_max_entries)
    memory_handler.setLevel(logging.DEBUG)
    json_formatter = JSONFormatter()
    memory_handler.setFormatter(json_formatter)
    root_logger.addHandler(memory_handler)

    return root_logger, memory_handler


def get_latest_log_files():
    """
    获取最新的日志文件列表

    Returns:
        dict: {component: latest_file_path}
    """
    result = {}
    components = ['app', 'app.json', 'error', 'agent', 'tool', 'cache', 'api', 'web']

    # 获取最新的日期文件夹
    date_dirs = sorted([d for d in LOG_DIR.iterdir() if d.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}', d.name)], reverse=True)

    if not date_dirs:
        return result

    latest_date_dir = date_dirs[0]

    # 获取该日期下最新的 part 文件夹
    part_dirs = sorted([d for d in latest_date_dir.iterdir() if d.is_dir() and d.name.startswith('part-')],
                       key=lambda x: int(x.name.split('-')[1]), reverse=True)

    if not part_dirs:
        return result

    latest_part_dir = part_dirs[0]

    # 获取各组件的最新日志文件
    for comp in components:
        log_file = latest_part_dir / f"{comp}.log"
        if log_file.exists():
            result[comp] = str(log_file)

    return result


def get_log_files_by_date(date_str: str = None):
    """
    获取指定日期的所有日志文件

    Args:
        date_str: 日期字符串 (YYYY-MM-DD)，默认为今天

    Returns:
        dict: {part_number: {component: file_path}}
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    date_dir = LOG_DIR / date_str
    if not date_dir.exists():
        return {}

    result = {}
    components = ['app', 'app.json', 'error', 'agent', 'tool', 'cache', 'api', 'web']

    for part_dir in sorted(date_dir.iterdir()):
        if not part_dir.is_dir() or not part_dir.name.startswith('part-'):
            continue

        part_num = part_dir.name
        result[part_num] = {}

        for comp in components:
            log_file = part_dir / f"{comp}.log"
            if log_file.exists():
                result[part_num][comp] = str(log_file)

    return result
