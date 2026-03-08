from application.orchestrators.query_orchestrator import SearchOrchestrator
from api.models.search_request import SearchRequest
from utils.logger import get_app_logger

logger = get_app_logger("search_service")

class SearchService:
    def __init__(self, orchestrator: SearchOrchestrator):
        self._orchestrator = orchestrator

    async def search(self, request: SearchRequest, db) -> dict:
        logger.info(f"[search_service] tenant={request.tenantId} query={request.query}")
        try:
            response = await self._orchestrator.search(request, db)
            logger.info(f"[search_service] Search complete: {response.total_count} results across {len(response.groups)} groups")
            return {
                "success": True,
                "data": [item for group in response.groups for item in group.items],
                "meta": response.metadata,
                "error": None
            }
        except Exception as e:
            logger.error(f"[search_service] Search failed: {e}", exc_info=True)
            return {
                "success": False,
                "data": [],
                "meta": {},
                "error": str(e)
            }

def get_search_service() -> SearchService:
    orchestrator = SearchOrchestrator()
    return SearchService(orchestrator)
