# application/services/search_service.py
# Service layer: bridges the HTTP API with the core orchestration engine.

from typing import AsyncGenerator

from core.orchestrator import SearchOrchestrator
from db.client import DatabaseConnector
from models.search_request import SearchRequest
from core.logger import get_app_logger

logger = get_app_logger("search_service")


async def run_search(request: SearchRequest) -> AsyncGenerator[str, None]:
    """
    Processes a SearchRequest end-to-end and yields the JSON-encoded
    SearchResponse as a single newline-delimited chunk.

    @param request: Validated SearchRequest from the API layer.
    @returns: Async generator yielding one JSON line.
    @throws ValueError: Re-raised from assembler on forbidden operators or missing placeholders.
    """
    logger.info(f"SearchService: tenant='{request.tenantId}' query='{request.query}'")
    db = DatabaseConnector.get_db()
    orchestrator = SearchOrchestrator()
    response = await orchestrator.search(request, db=db)
    logger.info(f"Search complete: {response.total_count} results across {len(response.groups)} groups")

    async def _stream():
        yield response.model_dump_json() + "\n"

    return _stream()


# ── Backward-compat class kept for existing tests ─────────────────────────────

class SearchService:
    """
    Legacy class wrapper — delegates to run_search().
    Kept so existing test_search_router.py mocks continue to work.
    """

    def __init__(self, tenantId: str, userId: str):
        self.tenantId = tenantId
        self.userId = userId

    async def process_query(self, query: str) -> AsyncGenerator[str, None]:
        """
        @param query: Natural language query string.
        @returns: Async generator yielding newline-delimited JSON.
        """
        request = SearchRequest(query=query, tenantId=self.tenantId, userId=self.userId)
        return await run_search(request)
