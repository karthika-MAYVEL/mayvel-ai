# core/orchestrator.py
# Orchestrator: coordinates the full search pipeline using RootAgent + sub-agents.
# Supports both the new two-call T1→T2 path (RoutingDecision) and the
# legacy ChannelPlan path for backward-compat during Stage B→C migration.

import json
import time
from datetime import datetime
from typing import Any

from agents.root_agent import RootAgent
from agents.agent_registry import get_agent, get_group_agent
from core.query_assembler import resolve
from models.search_request import SearchRequest
from models.search_response import SearchResponse, ResultGroup
from models.routing_decision import RoutingDecision
from core.logger import get_app_logger
import llm_sdk.token_tracker as token_tracker

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

        Tries the new two-call T1→T2 path first (RoutingDecision).
        Falls back to the legacy ChannelPlan path if the root agent
        does not produce a RoutingDecision.

        @param request: The validated SearchRequest from the API layer.
        @param db: Live Motor database instance (None = mock/no-DB mode).
        @returns: A structured SearchResponse.
        """
        start_ms = int(time.monotonic() * 1000)
        token_tracker.reset()  # fresh counter for this request
        logger.info(f"Orchestrator search start: '{request.query[:80]}'")

        # ── Try two-call path via RoutingDecision ────────────────────────────
        routing = await self._try_routing_decision(request)
        if routing is not None:
            return await self._dispatch_two_call(request, routing, db, start_ms)

        # ── Fall back to legacy ChannelPlan path ─────────────────────────────
        return await self._dispatch_legacy(request, db, start_ms)

    # ------------------------------------------------------------------
    # Two-call T1 → T2 path
    # ------------------------------------------------------------------

    async def _try_routing_decision(
        self, request: SearchRequest
    ) -> RoutingDecision | None:
        """
        Attempts to obtain a RoutingDecision from the root agent.
        Returns None if the root agent cannot produce one (e.g. no LLM key).

        @param request: The incoming SearchRequest.
        @returns: RoutingDecision or None.
        """
        try:
            routing = await self._root_agent.route(request)
            logger.info(
                f"T1 RoutingDecision: primary={routing.primary_group} "
                f"secondary={routing.secondary_groups} "
                f"user_scoped={routing.user_scoped}"
            )
            return routing
        except (AttributeError, NotImplementedError):
            # root_agent.route() not yet implemented (Stage B compat)
            return None
        except Exception as exc:
            logger.warning(f"T1 routing failed ({exc}); falling back to legacy path.")
            return None

    async def _dispatch_two_call(
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

        try:
            template = await agent.generate(
                routing=routing,
                user_query=request.query,
                tenant_id=request.tenantId,
                user_id=request.userId if routing.user_scoped else None,
            )
            pipeline = resolve(
                template.pipeline,
                tenant_id=request.tenantId,
                user_id=request.userId,
            )
            # pipeline = _apply_limit(pipeline)
            _log_query_plan(
                label=f"TWO-CALL T2 [{primary}]",
                query=request.query,
                entity=template.entity_type or primary.lower(),
                pipeline=pipeline,
                routing=routing,
            )
            items = await _run_pipeline(db, pipeline)
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

        return SearchResponse(
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
            },
        )

    # ------------------------------------------------------------------
    # Legacy ChannelPlan path
    # ------------------------------------------------------------------

    async def _dispatch_legacy(
        self, request: SearchRequest, db: Any, start_ms: int
    ) -> SearchResponse:
        """
        Legacy execution path using ChannelPlan (independent + chain channels).
        Kept for backward-compat until Stage C migration is complete.

        @param request: The validated SearchRequest.
        @param db: MongoDB database instance.
        @param start_ms: Request start time in milliseconds.
        @returns: Structured SearchResponse.
        """
        plan = await self._root_agent.plan(request)
        logger.info(
            f"[LEGACY] ChannelPlan: {len(plan.independent)} independent, "
            f"{len(plan.chains)} chains"
        )
        groups: list[ResultGroup] = []
        channels_queried: list[str] = []

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
                # pipeline = _apply_limit(pipeline, request.limit)
                _log_query_plan(
                    label=f"LEGACY CHANNEL [{entity}]",
                    query=request.query,
                    entity=entity,
                    pipeline=pipeline,
                )
                items = await _run_pipeline(db, pipeline)
                groups.append(ResultGroup(entity_type=entity, count=len(items), items=items))
                channels_queried.append(entity)
                logger.info(f"[LEGACY] Channel '{entity}': {len(items)} results")
            except Exception as exc:
                logger.error(f"[LEGACY] Channel '{entity}' failed: {exc}")
                groups.append(ResultGroup(entity_type=entity, count=0, items=[]))

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
                # pipeline = _apply_limit(pipeline, request.limit)
                _log_query_plan(
                    label=f"LEGACY CHAIN [{root_entity}]",
                    query=request.query,
                    entity=root_entity,
                    pipeline=pipeline,
                )
                items = await _run_pipeline(db, pipeline)
                groups.append(ResultGroup(entity_type=root_entity, count=len(items), items=items))
                channels_queried.append(root_entity)
                logger.info(f"[LEGACY] Chain '{root_entity}': {len(items)} results")
            except Exception as exc:
                logger.error(f"[LEGACY] Chain '{root_entity}' failed: {exc}")
                groups.append(ResultGroup(entity_type=root_entity, count=0, items=[]))

        total = sum(g.count for g in groups)
        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        tokens = token_tracker.get_totals()

        _log_token_summary(request.query, tokens, elapsed_ms)

        return SearchResponse(
            summary=_build_summary(total, channels_queried, request.query),
            total_count=total,
            groups=groups,
            metadata={
                "channels_queried":  channels_queried,
                "query_time_ms":     elapsed_ms,
                "routing_path":      "legacy_channel_plan",
                "coverage_reason":   plan.coverage_reason,
                "token_usage":       tokens,
            },
        )

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
        f"{hdr}  COLLECTION    {rst}: {val}entities{rst}",
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
    """Runs an aggregation pipeline; returns [] if no db is connected."""
    if db is None:
        logger.warning("No DB connection — returning empty results (offline mode).")
        return []
    cursor = db[_COLLECTION].aggregate(pipeline)
    raw_docs = await cursor.to_list(length=_MAX_RESULTS)
    return [_sanitize_doc(doc) for doc in raw_docs]


def _sanitize_doc(doc: Any) -> Any:
    """
    Recursively converts BSON types to JSON-serialisable Python types.
    Handles ObjectId, datetime, Decimal128, bytes, and nested dicts/lists.

    @param doc: A MongoDB document (dict, list, or scalar).
    @returns: A fully JSON-serialisable equivalent.
    """
    # Import lazily to keep bson as an optional dep
    try:
        from bson import ObjectId, Decimal128
        _HAS_BSON = True
    except ImportError:
        _HAS_BSON = False

    if isinstance(doc, dict):
        return {k: _sanitize_doc(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [_sanitize_doc(v) for v in doc]
    if isinstance(doc, datetime):
        return doc.isoformat()
    if isinstance(doc, bytes):
        import base64
        return base64.b64encode(doc).decode()
    if _HAS_BSON:
        if isinstance(doc, ObjectId):
            return str(doc)
        if isinstance(doc, Decimal128):
            return float(doc.to_decimal())
    return doc


def _build_summary(total: int, channels: list[str], query: str) -> str:
    if total == 0:
        return f"No results found for: {query}"
    channel_str = ", ".join(channels) if channels else "unknown"
    return f"Found {total} result(s) across {channel_str}."
