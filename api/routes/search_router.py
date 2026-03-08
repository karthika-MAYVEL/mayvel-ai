from fastapi import APIRouter, HTTPException, Depends
from api.models.search_request import SearchRequest
from application.services.search_service import SearchService, get_search_service
from infrastructure.database.database import get_db
from utils.logger import get_app_logger

logger = get_app_logger("api.ask")

router = APIRouter()

@router.post("/ask")
async def ask_seyo(
    request: SearchRequest,
    db=Depends(get_db),
    service: SearchService = Depends(get_search_service)
):
    """
    Endpoint for accepting natural language queries to Ask Seyo.
    Delegates to SearchService.
    """
    try:
        logger.info(f"[api.ask] Received /ask user={request.userId} tenant={request.tenantId} query={request.query}")
        result = await service.search(request, db)
        return result
    except Exception as e:
        logger.error(f"Internal server error handling /ask request: {e}")
        raise HTTPException(status_code=500, detail={"success": False, "data": [], "meta": {}, "error": str(e)})
