import logging
from typing import AsyncGenerator
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from config.settings import settings
from utils.logger import get_app_logger

logger = get_app_logger("database")


class Database:
    client: AsyncIOMotorClient | None = None


db = Database()


async def connect_db():
    if db.client is not None:
        return

    uri = settings.MONGO_URI
    masked_uri = uri

    if "@" in uri:
        prefix, rest = uri.split("://", 1)
        if ":" in rest and "@" in rest:
            auth, host = rest.split("@", 1)
            user = auth.split(":", 1)[0]
            masked_uri = f"{prefix}://{user}:***@{host}"

    logger.info(f"Connecting to MongoDB at {masked_uri} / {settings.MONGO_DB_NAME}")

    try:
        db.client = AsyncIOMotorClient(uri)
        await db.client.admin.command("ping")
        logger.info("Successfully connected to MongoDB.")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise RuntimeError(f"Database connection failed: {e}")


async def disconnect_db():
    if db.client is not None:
        db.client.close()
        db.client = None
        logger.info("MongoDB connection closed.")


# ---------------------------------------------------------
# FASTAPI DEPENDENCY (Generator)
# ---------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncIOMotorDatabase, None]:
    if db.client is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")

    yield db.client[settings.MONGO_DB_NAME]


# ---------------------------------------------------------
# DIRECT ACCESS (For services / orchestrators)
# ---------------------------------------------------------

def get_database() -> AsyncIOMotorDatabase:
    """
    Returns the Mongo database instance.
    Use this in service layer / orchestrators.
    """
    if db.client is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")

    return db.client[settings.MONGO_DB_NAME]