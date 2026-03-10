# config/settings.py
# All values are read from environment variables or .env file.
# Defaults are safe for local development only.
# Production values must be set in the environment — never in this file.
#
# Usage anywhere in the codebase:
#   from config.settings import settings
#   settings.MONGO_URI
#
# All string fields use Field(default="...") so the source of each
# default is explicit and every field is individually documentable.

from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # ── App ───────────────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "staging", "production"] = Field(
        default="development", description="Runtime environment"
    )
    HOST: str = Field(default="0.0.0.0", description="Bind host")
    PORT: int = Field(default=8000, description="Bind port")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # ── LLM ───────────────────────────────────────────────────────────────────
    LLM_API_KEY: str = Field(default="", description="Gemini API key")
    LLM_MODEL_NAME: str = Field(
        default="gemini-2.0-flash", description="Gemini model identifier"
    )

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGO_URI: str = Field(
        default="mongodb://localhost:27017", description="MongoDB connection URI"
    )
    MONGO_DB_NAME: str = Field(default="mayvel", description="Target database name")
    MONGO_COLLECTION: str = Field(
        default="entities", description="Unified collection name"
    )

    # ── Routing metadata labels ───────────────────────────────────────────────
    # Internal constants written into response metadata.
    # Override only if your observability tooling expects different values.
    ROUTING_PATH_FAILED: str = Field(default="failed")
    ROUTING_PATH_TWO_CALL: str = Field(default="two_call")
    LLM_STAGE_T1: str = Field(default="T1_Router")
    LLM_STAGE_T2_PREFIX: str = Field(default="T2_Query_Generator_")

    # ── Logging ───────────────────────────────────────────────────────────────
    QUERY_LOG_DIR: str = Field(
        default="logs", description="Directory for daily JSONL query tracker logs"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",        # silently ignore unknown env vars
        case_sensitive=False,  # MONGO_URI and mongo_uri both work
    )


# Single shared instance — import this everywhere.
# Pydantic reads the .env file and environment variables once at import time.
settings = Settings()




# config/settings.py
# Reads all values directly from environment variables.
# Usage: from config.settings import settings

# import os
# from dataclasses import dataclass


# @dataclass(frozen=True)
# class Settings:

#     # ── App ───────────────────────────────────────────────────────────────────
#     APP_ENV: str        = os.getenv("APP_ENV", "development")
#     HOST: str           = os.getenv("HOST", "0.0.0.0")
#     PORT: int           = int(os.getenv("PORT", "8000"))
#     LOG_LEVEL: str      = os.getenv("LOG_LEVEL", "INFO")

#     # ── LLM ───────────────────────────────────────────────────────────────────
#     LLM_API_KEY: str    = os.getenv("LLM_API_KEY", "")
#     LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "gemini-2.0-flash")

#     # ── MongoDB ───────────────────────────────────────────────────────────────
#     MONGO_URI: str        = os.getenv("MONGO_URI", "mongodb://localhost:27017")
#     MONGO_DB_NAME: str    = os.getenv("MONGO_DB_NAME", "mayvel")
#     MONGO_COLLECTION: str = os.getenv("MONGO_COLLECTION", "entities")

#     # ── Routing metadata labels ───────────────────────────────────────────────
#     ROUTING_PATH_FAILED: str   = os.getenv("ROUTING_PATH_FAILED", "failed")
#     ROUTING_PATH_TWO_CALL: str = os.getenv("ROUTING_PATH_TWO_CALL", "two_call")
#     LLM_STAGE_T1: str          = os.getenv("LLM_STAGE_T1", "T1_Router")
#     LLM_STAGE_T2_PREFIX: str   = os.getenv("LLM_STAGE_T2_PREFIX", "T2_Query_Generator_")

#     # ── Logging ───────────────────────────────────────────────────────────────
#     QUERY_LOG_DIR: str = os.getenv("QUERY_LOG_DIR", "logs")


# settings = Settings()