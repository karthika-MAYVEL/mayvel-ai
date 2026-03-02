from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from models.search_request import SearchRequest
from application.services.search_service import SearchService
from core.logger import get_app_logger

logger = get_app_logger("api.ask")

router = APIRouter()

@router.post("/ask")
async def ask_seyo(request: SearchRequest):
    """
    Endpoint for accepting natural language queries to Ask Seyo.
    Delegates the step-by-step agentic orchestration to the SearchService.
    """
    try:
        # Initialize the service with user context
        logger.info(f"Received /ask request from user '{request.userId}' (Tenant: '{request.tenantId}'). Query: '{request.query}'")
        service = SearchService(tenantId=request.tenantId, userId=request.userId)
        
        # Get the stream generator from the service
        stream_generator = await service.process_query(request.query)
        
        # Return as a Streaming HTTP Response
        return StreamingResponse(stream_generator, media_type="text/plain")
        
    except ValueError as e:
        logger.warning(f"Validation error for /ask request: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Internal server error handling /ask request: {e}")
        raise HTTPException(status_code=500, detail=str(e))
