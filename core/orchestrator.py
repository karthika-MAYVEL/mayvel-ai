# core/orchestrator.py
# Orchestrator: coordinates the full search pipeline using RootAgent + sub-agents.

import time
from typing import Any

from agents.root_agent import RootAgent
from agents.agent_registry import get_agent
from core.query_assembler import resolve
from models.search_request import SearchRequest
from models.search_response import SearchResponse, ResultGroup
from core.logger import get_app_logger

logger = get_app_logger("orchestrator")

_COLLECTION = "entities"
_MAX_RESULTS = 200


class SearchOrchestrator:
    """
    Full pipeline coordinator.
    1. Root Agent classifies the query into a ChannelPlan.
    2. Each channel gets its sub-agent; sub-agent returns a QueryTemplate.
    3. Assembler resolves placeholders → executable pipeline.
    4. Executor runs the pipeline against MongoDB.
    5. Results are merged into a SearchResponse.
    """

    def __init__(self):
        self._root_agent = RootAgent()

    async def search(self, request: SearchRequest, db=None) -> SearchResponse:
        """
        End-to-end search execution.

        @param request: The validated SearchRequest from the API layer.
        @param db: Live Motor database instance (None = mock/no-DB mode).
        @returns: A structured SearchResponse.
        """
        start_ms = int(time.monotonic() * 1000)
        logger.info(f"Orchestrator search start: '{request.query[:80]}'")

        plan = await self._root_agent.plan(request)
        logger.info(
            f"ChannelPlan: {len(plan.independent)} independent, "
            f"{len(plan.chains)} chains"
        )

        groups: list[ResultGroup] = []
        channels_queried: list[str] = []

        # ── Independent channels ─────────────────────────────────────────────
        for channel in plan.independent:
            entity = channel.entity_type
            try:
                agent = get_agent(entity)
                template = await agent.generate(channel, request.query)
                pipeline = resolve(
                    template.pipeline,
                    tenant_id=request.tenantId,
                    user_id=request.userId,
                )
                pipeline = _apply_limit(pipeline, request.limit)
                items = await _run_pipeline(db, pipeline)
                groups.append(ResultGroup(entity_type=entity, count=len(items), items=items))
                channels_queried.append(entity)
                logger.info(f"Channel '{entity}': {len(items)} results")
            except Exception as e:
                logger.error(f"Channel '{entity}' failed: {e}")
                groups.append(ResultGroup(entity_type=entity, count=0, items=[]))

        # ── Chain channels ────────────────────────────────────────────────────
        for chain_channel in plan.chains:
            root_entity = chain_channel.root_entity
            try:
                agent = get_agent(root_entity)
                template = await agent.generate(chain_channel, request.query)
                pipeline = resolve(
                    template.pipeline,
                    tenant_id=request.tenantId,
                    user_id=request.userId,
                )
                pipeline = _apply_limit(pipeline, request.limit)
                items = await _run_pipeline(db, pipeline)
                groups.append(ResultGroup(entity_type=root_entity, count=len(items), items=items))
                channels_queried.append(root_entity)
                logger.info(f"Chain '{root_entity}': {len(items)} results")
            except Exception as e:
                logger.error(f"Chain '{root_entity}' failed: {e}")
                groups.append(ResultGroup(entity_type=root_entity, count=0, items=[]))

        total = sum(g.count for g in groups)
        elapsed_ms = int(time.monotonic() * 1000) - start_ms

        return SearchResponse(
            summary=_build_summary(total, channels_queried, request.query),
            total_count=total,
            groups=groups,
            metadata={
                "channels_queried": channels_queried,
                "query_time_ms": elapsed_ms,
                "coverage_reason": plan.coverage_reason,
            },
        )

    # Kept for backward-compat with SearchService until it is updated
    async def execute_search(self, user_query: str, db=None, executor=None) -> dict:
        """Legacy shim — wraps search() for the existing SearchService."""
        request = SearchRequest(query=user_query, tenantId="", userId="")
        response = await self.search(request, db=db)
        return response.model_dump()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_limit(pipeline: list, limit: int) -> list:
    """Injects a $limit stage if none is present."""
    has_limit = any("$limit" in stage for stage in pipeline)
    if not has_limit:
        return [*pipeline, {"$limit": min(limit, _MAX_RESULTS)}]
    return pipeline


async def _run_pipeline(db: Any, pipeline: list) -> list:
    """Runs an aggregation pipeline; returns [] if no db is connected."""
    if db is None:
        logger.warning("No DB connection — returning empty results (offline mode).")
        return []
    cursor = db[_COLLECTION].aggregate(pipeline)
    return await cursor.to_list(length=_MAX_RESULTS)


def _build_summary(total: int, channels: list[str], query: str) -> str:
    if total == 0:
        return f"No results found for: {query}"
    channel_str = ", ".join(channels) if channels else "unknown"
    return f"Found {total} result(s) across {channel_str}."
