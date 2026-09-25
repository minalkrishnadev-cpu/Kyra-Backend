from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Load .env from project root before reading env vars
def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        root = Path(__file__).resolve().parents[2]
        load_dotenv(root / ".env")
    except ImportError:
        pass


_load_env()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    return raw in {"1", "true", "t", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    kyra_openai_api_key: str | None = os.getenv("KYRA_OPENAI_API_KEY")
    openai_model_vision: str = os.getenv("OPENAI_MODEL_VISION", "gpt-5.2-vision")
    birefnet_enabled: bool = _env_bool("BIREFNET_ENABLED", True)


settings = Settings()

