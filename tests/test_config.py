import pytest
from app.config import Config


class TestConfig:
    def test_config_loads(self):
        assert Config is not None

    def test_langchain_tracing_default(self):
        assert Config.LANGCHAIN_TRACING_V2 is False

    def test_langchain_project_default(self):
        assert Config.LANGCHAIN_PROJECT == "langchain-project"
