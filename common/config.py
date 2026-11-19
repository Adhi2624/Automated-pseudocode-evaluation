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
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_json_mode: bool
    llm_timeout: float
    llm_retries: int
    eval_delay_seconds: float
    max_answer_chars: int
    output_xlsx: str

    @property
    def llm_url(self) -> str:
        return f"{self.llm_base_url}/chat/completions"


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
        llm_base_url=env("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
        llm_model=env("LLM_MODEL", "meta-llama/llama-3.1-70b-instruct"),
        llm_api_key=env("LLM_API_KEY") or env("OPENROUTER_API_KEY", ""),
        llm_json_mode=env("LLM_JSON_MODE", "true").strip().lower() in ("1", "true", "yes"),
        llm_timeout=float(env("LLM_TIMEOUT", "60")),
        llm_retries=int(env("LLM_RETRIES", "3")),
        eval_delay_seconds=float(env("EVAL_DELAY_SECONDS", "1")),
        max_answer_chars=int(env("MAX_ANSWER_CHARS", "4000")),
        output_xlsx=env("OUTPUT_XLSX", "user_pseudocode_scores.xlsx"),
    )
