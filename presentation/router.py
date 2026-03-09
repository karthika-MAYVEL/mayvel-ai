from fastapi import APIRouter, HTTPException, Depends

from presentation.models.search_request import SearchRequest
from presentation.models.search_response import Response

from application.services.search_service import SearchService

from utils.logger import get_app_logger

logger = get_app_logger("api.ask")

router = APIRouter()


@router.post("/ask")
async def ask_seyo(
    request: SearchRequest,
   ):
    """
    Accepts a natural language query and returns structured search results.
    """
    service = SearchService()

    try:
        logger.info(f"Received /ask — user={request.userId} tenant={request.tenantId} query={request.query}")
        response = await service.search(request)
        return response
    except Exception as e:
        logger.error(f"Unhandled error in /ask: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )