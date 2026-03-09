from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # ── App ───────────────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "staging", "production"] = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # ── LLM ───────────────────────────────────────────────────────────────────
    LLM_API_KEY: str = ""
    LLM_MODEL_NAME: str = "gemini-3-flash-preview"

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "FLATNEW"
    MONGO_COLLECTION: str = "entities"

    # ── Query execution ───────────────────────────────────────────────────────
    QUERY_TYPE_FIND: str = "find"

    # ── Routing metadata labels ───────────────────────────────────────────────
    ROUTING_PATH_FAILED: str = "failed"
    ROUTING_PATH_TWO_CALL: str = "two_call"

    # ── LLM stage labels (written into response metadata) ────────────────────
    LLM_STAGE_T1: str = "T1_Router"
    LLM_STAGE_T2_PREFIX: str = "T2_Query_Generator_"

    # ── Logging ───────────────────────────────────────────────────────────────
    QUERY_LOG_DIR: str = "logs"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()