import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = BASE_DIR / "data" / "bookmarks.db"
DEFAULT_UPLOADS_PATH = BASE_DIR / "data" / "uploads"


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    session_secret: str
    database_path: str
    uploads_path: str
    login_code_ttl_seconds: int
    login_code_length: int


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        session_secret=_require("SESSION_SECRET"),
        database_path=os.environ.get("DATABASE_PATH", str(DEFAULT_DATABASE_PATH)),
        uploads_path=os.environ.get("UPLOADS_PATH", str(DEFAULT_UPLOADS_PATH)),
        login_code_ttl_seconds=int(os.environ.get("LOGIN_CODE_TTL_SECONDS", "300")),
        login_code_length=int(os.environ.get("LOGIN_CODE_LENGTH", "6")),
    )
