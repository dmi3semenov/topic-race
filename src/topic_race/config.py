from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
OUT_DIR = PROJECT_ROOT / "out"
CACHE_DB = DATA_DIR / "cache.db"
SESSION_DIR = DATA_DIR / "sessions"


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    phone: str
    group_name: str
    session_name: str

    @property
    def session_path(self) -> Path:
        return SESSION_DIR / self.session_name


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    api_id = os.environ["TG_API_ID"]
    api_hash = os.environ["TG_API_HASH"]
    phone = os.environ["TG_PHONE"]
    group_name = os.environ.get("TG_GROUP_NAME", "Материалы")
    session_name = os.environ.get("TG_SESSION_NAME", "topic_race")

    return Settings(
        api_id=int(api_id),
        api_hash=api_hash,
        phone=phone,
        group_name=group_name,
        session_name=session_name,
    )
