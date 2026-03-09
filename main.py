import uvicorn
from fastapi import FastAPI
from contextlib import asynccontextmanager
from presentation.router import router as search_router
from config.settings import settings
from infrastructure.database.database import connect_db, disconnect_db

from utils.logger import get_app_logger

logger = get_app_logger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan events for FastAPI.
    """
    logger.info("Initializing Ask Seyo API Gateway service...")
    await connect_db()
    logger.info("Service initialization complete. Ready to receive requests.")
    yield
    logger.info("Shutting down Ask Seyo API Gateway service...")
    await disconnect_db()
    logger.info("Service shutdown complete.")

app = FastAPI(title="Ask Seyo API Gateway", lifespan=lifespan)
app.include_router(search_router, prefix="/api/v1/ai")

if __name__ == "__main__":
    logger.info(f"Starting Ask Seyo Gateway on {settings.HOST}:{settings.PORT}...")
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)
