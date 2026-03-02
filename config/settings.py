import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

class Settings:
    """
    Application settings, loaded from environment variables.
    Follows SEYO.AI engineering standards: UPPER_SNAKE_CASE.
    """
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "gemini-2.5-flash")
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    MONGO_URI: str = os.getenv("MONGODB_URI", os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    MONGO_DB: str = os.getenv("MONGO_DB_NAME", os.getenv("MONGO_DB", "seyo_db"))

settings = Settings()
