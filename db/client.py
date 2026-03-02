from motor.motor_asyncio import AsyncIOMotorClient
from config.settings import settings
from core.logger import get_app_logger

logger = get_app_logger("database")

class DatabaseConnector:
    """
    Manages the async MongoDB connection using Motor.
    """
    client: AsyncIOMotorClient = None
    db = None

    @classmethod
    async def connect(cls):
        """
        Initializes the MongoDB connection pool.
        """
        try:
            logger.info(f"Attempting connection to MongoDB at {settings.MONGO_URI}...")
            cls.client = AsyncIOMotorClient(settings.MONGO_URI)
            cls.db = cls.client[settings.MONGO_DB]
            # Verify connection
            await cls.client.admin.command('ping')
            logger.info("Successfully connected to MongoDB pool.")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise e

    @classmethod
    async def close(cls):
        """
        Closes the MongoDB connection pool.
        """
        if cls.client:
            cls.client.close()
            logger.info("MongoDB connection closed.")

    @classmethod
    def get_db(cls):
        """
        Returns the database instance.
        """
        if cls.db is None:
            raise Exception("Database is not initialized. Call connect() first.")
        return cls.db
