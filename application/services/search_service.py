from typing import List, Dict, Any

from utils.logger import get_app_logger
from application.orchestrators.query_orchestrator import SearchOrchestrator

logger = get_app_logger("search_service")


class SearchService:

    def __init__(self):
        self.orchestrator = SearchOrchestrator()

    async def search(self, request) -> Dict[str, Any]:
        """
        Executes AI search and returns raw execution results.
        No response models are enforced to allow dynamic projections.
        """

        try:
            response = await self.orchestrator.search(request)

            groups = response.groups or []

            results: List[Dict[str, Any]] = []
            for g in groups:
                results.extend(g.items)

            logger.info(
                f"[search_service] Search complete: "
                f"{len(results)} results across {len(groups)} groups"
            )

            meta = {
                "summary": response.summary,
                "groups": len(groups),
                "routing": {
                    "primary_group": response.metadata.get("primary_group"),
                    "secondary_groups": response.metadata.get("secondary_groups"),
                    "routing_path": response.metadata.get("routing_path")
                },
                "token_usage": response.metadata.get("token_usage"),
                "query_time_ms": response.metadata.get("query_time_ms"),
                "generated_queries": response.metadata.get("llm_responses"),
                "executed_pipeline": response.metadata.get("executed_mongo_query")
            }

            return {
                "success": True,
                "message": "Query executed successfully",
                "data": results,
                "meta": meta
            }

        except Exception as exc:
            logger.error(
                f"[search_service] Search failed: {exc}",
                exc_info=True
            )

            return {
                "success": False,
                "message": "Search execution failed",
                "data": [],
                "meta": {
                    "error": str(exc)
                }
            }