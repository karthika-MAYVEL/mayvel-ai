import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager

from core.config import settings
from infrastructure.database.mongo import DatabaseConnector
from presentation.routes.ask import router as ask_router
from core.logger import get_app_logger

logger = get_app_logger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan events for FastAPI. Connects to and gracefully closes the MongoDB connection pool.
    """
    # Startup
    logger.info("Initializing Ask Seyo API Gateway service...")
    await DatabaseConnector.connect()
    logger.info("Service initialization complete. Ready to receive requests.")
    yield
    # Shutdown
    logger.info("Shutting down Ask Seyo API Gateway service...")
    await DatabaseConnector.close()
    logger.info("Service shutdown complete.")

# Initialize the FastAPI App Service
app = FastAPI(title="Ask Seyo API Gateway", lifespan=lifespan)

# Mount the defined API routes
app.include_router(ask_router, prefix="/api/v1")

if __name__ == "__main__":
    logger.info(f"Starting Ask Seyo Gateway on {settings.HOST}:{settings.PORT}...")
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
