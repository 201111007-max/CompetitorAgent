import pytest
from config.settings import Config


class TestConfig:
    def test_config_loads(self):
        assert Config is not None

    def test_langfuse_host_default(self):
        assert Config.LANGFUSE_HOST == "http://localhost:3000"

    def test_langfuse_init(self):
        Config.init_langfuse()
