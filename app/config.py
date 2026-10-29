"""Settings from .env. Keys are excluded from repr so they never reach logs or tracebacks."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    qloo_base_url: str
    llm_base_url: str
    llm_model: str
    qloo_api_key: str = field(repr=False)
    llm_api_key: str = field(repr=False)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_base_url and self.llm_model)


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    return "" if value.startswith("your_") else value


# Browser origins allowed to call the API: the production frontend (ALLOWED_ORIGINS) plus local dev.
DEV_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"


def parse_origins(raw: str) -> list[str]:
    """"https://a.vercel.app, https://b.com/" -> ["https://a.vercel.app", "https://b.com"]."""
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def load_settings() -> Settings:
    load_dotenv(REPO / ".env")
    settings = Settings(
        qloo_base_url=_env("QLOO_BASE_URL").rstrip("/"),
        llm_base_url=_env("LLM_BASE_URL").rstrip("/"),
        llm_model=_env("LLM_MODEL"),
        qloo_api_key=_env("QLOO_API_KEY"),
        llm_api_key=_env("LLM_API_KEY"),
    )
    if not (settings.qloo_api_key and settings.qloo_base_url):
        raise SystemExit("Set QLOO_API_KEY and QLOO_BASE_URL in .env first.")
    return settings
