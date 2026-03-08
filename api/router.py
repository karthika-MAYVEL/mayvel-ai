from fastapi import APIRouter
from api.routes import search_router

api_router = APIRouter()
api_router.include_router(search_router.router, tags=["search"])
