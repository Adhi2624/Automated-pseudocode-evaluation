"""Central configuration read from environment (and optional .env file)."""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    mongo_uri: str
    mongo_db: str
    mongo_collection: str
    cors_origins: tuple
    ollama_url: str
    ollama_model: str
    ollama_timeout: float
    ollama_retries: int
    eval_delay_seconds: float
    max_answer_chars: int
    output_xlsx: str


def _parse_origins(value: str) -> tuple:
    return tuple(o.strip() for o in value.split(",") if o.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    env = os.environ.get
    return Settings(
        mongo_uri=env("MONGO_URI", "mongodb://localhost:27017/"),
        mongo_db=env("MONGO_DB", "sproc"),
        mongo_collection=env("MONGO_COLLECTION", "user-details"),
        cors_origins=_parse_origins(env("CORS_ORIGINS", "")),
        ollama_url=env("OLLAMA_URL", "http://localhost:11434/api/generate"),
        ollama_model=env("OLLAMA_MODEL", "llama3.1:latest"),
        ollama_timeout=float(env("OLLAMA_TIMEOUT", "60")),
        ollama_retries=int(env("OLLAMA_RETRIES", "3")),
        eval_delay_seconds=float(env("EVAL_DELAY_SECONDS", "1")),
        max_answer_chars=int(env("MAX_ANSWER_CHARS", "4000")),
        output_xlsx=env("OUTPUT_XLSX", "user_pseudocode_scores.xlsx"),
    )
