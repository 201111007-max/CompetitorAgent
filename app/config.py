import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

project_root = Path(__file__).parent
load_dotenv(project_root / ".env")


class Config:
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    LANGCHAIN_API_KEY: Optional[str] = os.getenv("LANGCHAIN_API_KEY")
    LANGCHAIN_TRACING_V2: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    LANGCHAIN_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "langchain-project")

    @classmethod
    def validate(cls) -> bool:
        return bool(cls.OPENAI_API_KEY or cls.ANTHROPIC_API_KEY)
