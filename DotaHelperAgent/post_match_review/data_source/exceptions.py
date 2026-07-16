"""数据源异常定义"""


class DataSourceError(Exception):
    """数据源基础异常"""
    pass


class OpenDotaAPIError(DataSourceError):
    """OpenDota API 调用异常"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class DataValidationError(DataSourceError):
    """数据校验异常"""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        self.errors = errors or []
        super().__init__(message)
