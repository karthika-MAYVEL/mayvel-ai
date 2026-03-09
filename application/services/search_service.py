from typing import List, Any
from application.orchestrators.query_orchestrator import SearchOrchestrator
from presentation.models.search_request import SearchRequest
from presentation.models.global_search_response import (
    GlobalSearchResponseWrapper, 
    GlobalSearchData, 
    GlobalSearchMeta,
)
from utils.logger import get_app_logger

logger = get_app_logger("search_service")

class SearchService:
    orchestrator =  SearchOrchestrator()

    async def search(self, request: SearchRequest) -> GlobalSearchResponseWrapper:
        try:
            # FIX: Access the orchestrator via 'self'
            response = await self.orchestrator.search(request)
            
            logger.info(
                f"[search_service] Search complete: {response.total_count} results "
                f"across {len(response.groups)} groups"
            )

            # Flatten nested group items into a single list
            # Ensure 'item' matches the GlobalSearchItem schema requirements
            flattened_items = [
                item for group in response.groups for item in group.items
            ]

            # Construct the Pydantic Response Model
            return GlobalSearchResponseWrapper(
                success=True,
                message=f"{response.total_count} results analyzed",
                total_results=response.total_count,
                data=GlobalSearchData(global_search_response=flattened_items),
                meta=GlobalSearchMeta(
                    llm_responses=response.metadata.get("llm_responses", []),
                    executed_mongo_query=response.metadata.get("executed_mongo_query")
                )
            )

        except Exception as e:
            logger.error(f"[search_service] Search failed: {e}", exc_info=True)
            
            # Return a valid failure response using the model wrapper
            return GlobalSearchResponseWrapper(
                success=False,
                message="Search failed",
                total_results=0,
                data=GlobalSearchData(global_search_response=[]),
                meta=GlobalSearchMeta(llm_responses=[], executed_mongo_query=None)
            )
