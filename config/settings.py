import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")


class Config:
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    MODELSCOPE_CACHE: Optional[str] = os.getenv("MODELSCOPE_CACHE")
    LANGFUSE_PUBLIC_KEY: Optional[str] = os.getenv("LANGFUSE_PUBLIC_KEY")
    LANGFUSE_SECRET_KEY: Optional[str] = os.getenv("LANGFUSE_SECRET_KEY")
    LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "http://localhost:3000")

    @classmethod
    def init_langfuse(cls):
        from langfuse import Langfuse
        return Langfuse(
            public_key=cls.LANGFUSE_PUBLIC_KEY,
            secret_key=cls.LANGFUSE_SECRET_KEY,
            host=cls.LANGFUSE_HOST
        )

    @classmethod
    def validate(cls) -> bool:
        return bool(cls.OPENAI_API_KEY or cls.ANTHROPIC_API_KEY)
