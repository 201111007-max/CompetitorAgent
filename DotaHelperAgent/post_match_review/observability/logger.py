"""模块独立 logger（pmr.* 命名空间）"""
import logging


def get_logger(name: str) -> logging.Logger:
    """获取 pmr 命名空间下的 logger

    Args:
        name: 子模块名称，如 'data_source.opendota_client'

    Returns:
        logging.Logger: 格式化的 logger 实例
    """
    logger = logging.getLogger(f"pmr.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger
