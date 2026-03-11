# core/orchestrator.py
# Orchestrator: coordinates the full search pipeline using RootAgent + sub-agents.
# Supports both the new two-call T1→T2 path (RoutingDecision) and the
# legacy ChannelPlan path for backward-compat during Stage B→C migration.

import json
import time
from datetime import datetime
from typing import Any

from application.agents.root_agent import RootAgent
from application.agents.agent_registry import get_group_agent
from utils.placeholder_resolver import build_execution_context, resolve_placeholders
from presentation.models.search_request import SearchRequest
from presentation.models.search_response import SearchResponse, ResultGroup
from presentation.models.routing_decision import RoutingDecision
from utils.logger import get_app_logger
import infrastructure.llm_sdk.token_tracker as token_tracker
from infrastructure.database.database import get_database

logger = get_app_logger("orchestrator")

_COLLECTION = "entities"
# _MAX_RESULTS = 200


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
        token_tracker.reset()  # fresh counter for this request
        logger.info(f"Orchestrator search start: '{request.query[:80]}'")

        routing = await self._route(request)
        if routing is None:
            return SearchResponse(
                summary="No intent could be routed.",
                total_count=0,
                groups=[],
                metadata={"routing_path": "failed"}
            )

        db = get_database()
        return await self._dispatch(request, routing, db, start_ms)

    async def _route(
        self, request: SearchRequest
    ) -> RoutingDecision | None:
        """
        Obtains a RoutingDecision from the root agent.
        """
        try:
            routing = await self._root_agent.route(request)
            logger.info(
                f"T1 RoutingDecision: primary={routing.primary_group} "
                f"secondary={routing.secondary_groups} "
                f"user_scoped={routing.user_scoped}"
            )
            return routing
        except Exception as exc:
            logger.warning(f"T1 routing failed ({exc}).")
            return None

    async def _dispatch(
        self,
        request: SearchRequest,
        routing: RoutingDecision,
        db: Any,
        start_ms: int,
    ) -> SearchResponse:
        """
        Executes the new two-call path: T1 (already done) + one T2 call.
        Handles primary and all secondary groups in a single T2 LLM call.

        @param request: The validated SearchRequest.
        @param routing: RoutingDecision from T1.
        @param db: MongoDB database instance.
        @param start_ms: Request start time in milliseconds.
        @returns: Structured SearchResponse.
        """
        primary = routing.primary_group
        agent = get_group_agent(primary)
        groups: list[ResultGroup] = []
        channels_queried: list[str] = []
        pipeline_used: list = []

        try:
            template = await agent.generate(
                routing=routing,
                user_query=request.query,
                tenant_id=request.tenantId,
                user_id=request.userId if routing.user_scoped else None,
            )
            
            if template.query_type == "find" and not template.pipeline and template.filter:
                template.pipeline = [{"$match": template.filter}]
                
            context = build_execution_context(request.tenantId, getattr(request, 'userId', None), template)
            pipeline = resolve_placeholders(template.pipeline, context)
            pipeline_used = pipeline
            # pipeline = _apply_limit(pipeline)
            _log_query_plan(
                label=f"TWO-CALL T2 [{primary}]",
                query=request.query,
                entity=template.entity_type or primary.lower(),
                pipeline=pipeline,
                routing=routing,
            )
            
            import json
            logger.info(f"BEFORE EXECUTION - DB Pipeline: {json.dumps(pipeline, default=str)}")
            items = await _run_pipeline(db, pipeline)
            logger.info(f"AFTER EXECUTION - Raw DB Query: {json.dumps(pipeline, default=str)}")
            logger.info(f"Raw DB Items Returned ({len(items)}): {json.dumps(items, default=str)}")
            
            entity = template.entity_type or primary.lower()
            groups.append(ResultGroup(entity_type=entity, count=len(items), items=items))
            channels_queried.append(entity)
            logger.info(f"Two-call T2[{primary}]: {len(items)} results")
        except Exception as exc:
            logger.error(f"Two-call T2[{primary}] failed: {exc}")
            groups.append(ResultGroup(entity_type=primary.lower(), count=0, items=[]))

        total = sum(g.count for g in groups)
        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        tokens = token_tracker.get_totals()

        _log_token_summary(request.query, tokens, elapsed_ms)

        resp = SearchResponse(
            summary=_build_summary(total, channels_queried, request.query),
            total_count=total,
            groups=groups,
            metadata={
                "channels_queried":  channels_queried,
                "query_time_ms":     elapsed_ms,
                "routing_path":      "two_call",
                "primary_group":     primary,
                "secondary_groups":  routing.secondary_groups,
                "token_usage":       tokens,
                "llm_responses": [
                    {"stage": "T1_Router", "response": routing.model_dump() if routing else None},
                    {"stage": f"T2_Query_Generator_{primary}", "response": template.model_dump() if 'template' in locals() else None}
                ],
                "executed_mongo_query": pipeline_used,
            },
        )
        
        _log_query_execution(request, pipeline_used, resp, elapsed_ms)
        
        return resp



    # Kept for backward-compat with SearchService until it is updated
    async def execute_search(self, user_query: str, db=None, executor=None) -> dict:
        """Legacy shim — wraps search() for the existing SearchService."""
        request = SearchRequest(query=user_query, tenantId="", userId="")
        response = await self.search(request, db=db)
        return response.model_dump()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log_token_summary(query: str, tokens: dict, elapsed_ms: int) -> None:
    """Emits a structured token-usage log line for monitoring."""
    logger.info(
        f"[REQUEST TOKEN SUMMARY] query='{query[:60]}' | "
        f"llm_calls={tokens['llm_calls']} | "
        f"prompt_tokens={tokens['prompt_tokens']} | "
        f"output_tokens={tokens['output_tokens']} | "
        f"total_tokens={tokens['total_tokens']} | "
        f"query_time_ms={elapsed_ms}"
    )

def _log_query_execution(request: SearchRequest, pipeline: list, response: SearchResponse, elapsed_ms: int) -> None:
    """Logs the user query, generated pipeline, and response to a tracking file."""
    try:
        from pathlib import Path
        
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"query_tracker_{today}.jsonl"
        
        # We need a custom encoder or we can dump models to dict
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "elapsed_ms": elapsed_ms,
            "request": request.model_dump(),
            "pipeline": pipeline,
            "response": response.model_dump()
        }
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:
        logger.error(f"Failed to write query tracker log: {exc}")


# ANSI colour codes for highlighted terminal output
_ANSI = {
    "reset":  "\033[0m",
    "bold":   "\033[1m",
    "cyan":   "\033[96m",
    "yellow": "\033[93m",
    "green":  "\033[92m",
    "blue":   "\033[94m",
    "magenta":"\033[95m",
    "dim":    "\033[2m",
    "red":    "\033[91m",
}


def _log_query_plan(
    label: str,
    query: str,
    entity: str,
    pipeline: list,
    routing=None,
) -> None:
    """
    Prints a richly highlighted query plan to stdout before the pipeline executes.
    Each section is colour-coded for easy scanning in the terminal.

    @param label:    Short label identifying the execution path (e.g. 'TWO-CALL T2 [INSPECTION]').
    @param query:    Original user query string.
    @param entity:   Entity type the query targets.
    @param pipeline: Resolved MongoDB aggregation pipeline list.
    @param routing:  Optional RoutingDecision for extra T2-path context.
    """
    C = _ANSI
    bar  = f"{C['cyan']}{C['bold']}{'═' * 72}{C['reset']}"
    hdr  = f"{C['yellow']}{C['bold']}"
    val  = f"{C['green']}"
    dim  = f"{C['dim']}"
    rst  = C['reset']

    stage_names = [
        list(stage.keys())[0] if isinstance(stage, dict) else "?"
        for stage in pipeline
    ]

    lines = [
        "",
        bar,
        f"{C['magenta']}{C['bold']}  ▶  PRE-EXECUTION QUERY PLAN  ·  {label}{rst}",
        bar,
        f"{hdr}  USER QUERY    {rst}: {val}{query}{rst}",
        f"{hdr}  ENTITY TYPE   {rst}: {val}{entity}{rst}",
        f"{hdr}  COLLECTION    {rst}: {val}{_COLLECTION}{rst}",
        f"{hdr}  STAGE COUNT   {rst}: {val}{len(pipeline)}{rst}  {dim}({', '.join(stage_names)}){rst}",
    ]

    if routing is not None:
        lines += [
            f"{hdr}  PRIMARY GROUP {rst}: {val}{routing.primary_group}{rst}",
            f"{hdr}  USER SCOPED   {rst}: {val}{routing.user_scoped}{rst}",
            f"{hdr}  ENTITY HINT   {rst}: {val}{routing.entity_hint or '—'}{rst}",
            f"{hdr}  STATUS FILTER {rst}: {val}{routing.status_filter or '—'}{rst}",
            f"{hdr}  TIME WINDOW   {rst}: {val}{routing.time_window.model_dump() if routing.time_window else '—'}{rst}",
            f"{hdr}  COMPLEXITY    {rst}: {val}{routing.query_complexity}{rst}",
        ]

    lines += [
        f"{C['blue']}{C['bold']}  PIPELINE:{rst}",
    ]
    pipeline_json = json.dumps(pipeline, indent=2, default=str)
    for line in pipeline_json.splitlines():
        lines.append(f"  {dim}{line}{rst}")

    lines.append(bar)
    lines.append("")

    print("\n".join(lines), flush=True)

# def _apply_limit(pipeline: list, limit: int) -> list:
#     """Injects a $limit stage if none is present."""
#     has_limit = any("$limit" in stage for stage in pipeline)
#     if not has_limit:
#         return [*pipeline, {"$limit": min(limit, _MAX_RESULTS)}]
#     return pipeline


async def _run_pipeline(db: Any, pipeline: list) -> list:
    """
    Executes a MongoDB aggregation pipeline and returns sanitized documents.
    """

    from utils.sanitizer import _sanitize_doc

    if db is None:
        logger.warning("No DB connection — returning empty results (offline mode).")
        return []

    try:
        cursor = db[_COLLECTION].aggregate(pipeline)

        # IMPORTANT: Motor requires a length argument
        raw_docs = await cursor.to_list(length=None)

        sanitized = []
        for doc in raw_docs:
            sanitized.append(_sanitize_doc(doc))

        return sanitized

    except Exception as exc:
        logger.error(f"Mongo pipeline execution failed: {exc}", exc_info=True)
        raise


def _build_summary(total: int, channels: list[str], query: str) -> str:
    if total == 0:
        return f"No results found for: {query}"
    channel_str = ", ".join(channels) if channels else "unknown"
    return f"Found {total} result(s) across {channel_str}."