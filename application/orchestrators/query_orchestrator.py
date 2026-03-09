import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from application.agents.root_agent import RootAgent
from application.agents.agent_registry import get_group_agent
from presentation.models.search_request import SearchRequest
from presentation.models.search_response import SearchResponse, ResultGroup
from presentation.models.routing_decision import RoutingDecision
from utils.placeholder_resolver import build_execution_context, resolve_placeholders
from utils.sanitizer import _sanitize_doc
from utils.logger import get_app_logger
import infrastructure.llm_sdk.token_tracker as token_tracker

logger = get_app_logger("orchestrator")

_COLLECTION = "entities"


class SearchOrchestrator:
    """
    Full pipeline coordinator.

    1. RootAgent (T1)  — classifies the query into a RoutingDecision.
    2. GroupAgent (T2) — generates a QueryTemplate with a MongoDB pipeline.
    3. Resolver        — substitutes placeholders with runtime context.
    4. Executor        — runs the pipeline against MongoDB.
    5. Builder         — assembles and returns a SearchResponse.
    """

    def __init__(self):
        self._root_agent = RootAgent()

    async def search(self, request: SearchRequest) -> SearchResponse:
        """
        End-to-end search execution.

        @param request: Validated SearchRequest from the API layer.
        @param db:      Live Motor database instance.
        @returns:       Structured SearchResponse.
        """
        start_ms = int(time.monotonic() * 1000)
        token_tracker.reset()
        logger.info(f"Orchestrator search start: '{request.query[:80]}'")

        routing = await self._route(request)
        if routing is None:
            return SearchResponse(
                summary="No intent could be routed.",
                total_count=0,
                groups=[],
                metadata={"routing_path": "failed"},
            )

        return await self._dispatch(request, routing, db, start_ms)

    # ── Private ───────────────────────────────────────────────────────────────

    async def _route(self, request: SearchRequest) -> RoutingDecision | None:
        """Calls T1 RootAgent to classify the query into a RoutingDecision."""
        try:
            routing = await self._root_agent.route(request)
            logger.info(
                f"T1 routing: primary={routing.primary_group} "
                f"secondary={routing.secondary_groups} "
                f"user_scoped={routing.user_scoped}"
            )
            return routing
        except Exception as exc:
            logger.warning(f"T1 routing failed: {exc}")
            return None

    async def _dispatch(
        self,
        request: SearchRequest,
        routing: RoutingDecision,
        db: Any,
        start_ms: int,
    ) -> SearchResponse:
        """
        T2 dispatch: generates a QueryTemplate, resolves placeholders,
        executes the pipeline, and builds the SearchResponse.

        @param request:   Validated SearchRequest.
        @param routing:   RoutingDecision from T1.
        @param db:        MongoDB database instance.
        @param start_ms:  Request start time in milliseconds.
        @returns:         Structured SearchResponse.
        """
        primary = routing.primary_group
        agent = get_group_agent(primary)
        groups: list[ResultGroup] = []
        channels_queried: list[str] = []
        pipeline_used: list = []
        template = None

        try:
            template = await agent.generate(
                routing=routing,
                user_query=request.query,
                tenant_id=request.tenantId,
                user_id=request.userId if routing.user_scoped else None,
            )

            if template.query_type == "find" and not template.pipeline and template.filter:
                template.pipeline = [{"$match": template.filter}]

            context = build_execution_context(request.tenantId, request.userId, template)
            pipeline = resolve_placeholders(template.pipeline, context)
            pipeline_used = pipeline

            _log_query_plan(
                label=f"T2 [{primary}]",
                query=request.query,
                entity=template.entity_type or primary.lower(),
                pipeline=pipeline,
                routing=routing,
            )

            items = await _run_pipeline(db, pipeline)
            logger.info(f"T2 [{primary}]: pipeline returned {len(items)} documents")

            entity = template.entity_type or primary.lower()
            groups.append(ResultGroup(entity_type=entity, count=len(items), items=items))
            channels_queried.append(entity)

        except Exception as exc:
            logger.error(f"T2 [{primary}] failed: {exc}", exc_info=True)
            groups.append(ResultGroup(entity_type=primary.lower(), count=0, items=[]))

        total = sum(g.count for g in groups)
        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        tokens = token_tracker.get_totals()

        _log_token_summary(request.query, tokens, elapsed_ms)

        response = SearchResponse(
            summary=_build_summary(total, channels_queried, request.query),
            total_count=total,
            groups=groups,
            metadata={
                "channels_queried": channels_queried,
                "query_time_ms": elapsed_ms,
                "routing_path": "two_call",
                "primary_group": primary,
                "secondary_groups": routing.secondary_groups,
                "token_usage": tokens,
                "llm_responses": [
                    {"stage": "T1_Router", "response": routing.model_dump()},
                    {"stage": f"T2_Query_Generator_{primary}", "response": template.model_dump() if template else None},
                ],
                "executed_mongo_query": pipeline_used,
            },
        )

        _log_query_execution(request, pipeline_used, response, elapsed_ms)
        return response


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _run_pipeline(db: Any, pipeline: list) -> list:
    """Executes a MongoDB aggregation pipeline. Returns [] in offline mode."""
    if db is None:
        logger.warning("No DB connection — returning empty results (offline mode).")
        return []
    cursor = db[_COLLECTION].aggregate(pipeline)
    raw_docs = await cursor.to_list(length=None)
    return [_sanitize_doc(doc) for doc in raw_docs]


def _build_summary(total: int, channels: list[str], query: str) -> str:
    if total == 0:
        return f"No results found for: {query}"
    return f"Found {total} result(s) across {', '.join(channels) or 'unknown'}."


def _log_token_summary(query: str, tokens: dict, elapsed_ms: int) -> None:
    """Emits a structured token-usage log line for monitoring."""
    logger.info(
        f"[TOKEN SUMMARY] query='{query[:60]}' | "
        f"llm_calls={tokens['llm_calls']} | "
        f"prompt={tokens['prompt_tokens']} | "
        f"output={tokens['output_tokens']} | "
        f"total={tokens['total_tokens']} | "
        f"elapsed_ms={elapsed_ms}"
    )


def _log_query_execution(
    request: SearchRequest,
    pipeline: list,
    response: SearchResponse,
    elapsed_ms: int,
) -> None:
    """Appends a structured entry to the daily JSONL query tracker log."""
    try:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"query_tracker_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "elapsed_ms": elapsed_ms,
            "request": request.model_dump(),
            "pipeline": pipeline,
            "response": response.model_dump(),
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:
        logger.error(f"Failed to write query tracker log: {exc}")


# ── Terminal query plan printer ───────────────────────────────────────────────

_ANSI = {
    "reset":   "\033[0m",  "bold":    "\033[1m",
    "cyan":    "\033[96m", "yellow":  "\033[93m",
    "green":   "\033[92m", "blue":    "\033[94m",
    "magenta": "\033[95m", "dim":     "\033[2m",
}


def _log_query_plan(
    label: str,
    query: str,
    entity: str,
    pipeline: list,
    routing: RoutingDecision | None = None,
) -> None:
    """
    Prints a colour-coded query plan to stdout before pipeline execution.

    @param label:    Execution path label (e.g. 'T2 [INSPECTION]').
    @param query:    Original user query string.
    @param entity:   Entity type the query targets.
    @param pipeline: Resolved MongoDB aggregation pipeline.
    @param routing:  Optional RoutingDecision for additional context.
    """
    C = _ANSI
    bar = f"{C['cyan']}{C['bold']}{'═' * 72}{C['reset']}"
    hdr = f"{C['yellow']}{C['bold']}"
    val = C['green']
    dim = C['dim']
    rst = C['reset']

    stage_names = [list(s.keys())[0] if isinstance(s, dict) else "?" for s in pipeline]

    lines = [
        "", bar,
        f"{C['magenta']}{C['bold']}  ▶  PRE-EXECUTION QUERY PLAN  ·  {label}{rst}",
        bar,
        f"{hdr}  USER QUERY    {rst}: {val}{query}{rst}",
        f"{hdr}  ENTITY TYPE   {rst}: {val}{entity}{rst}",
        f"{hdr}  COLLECTION    {rst}: {val}{_COLLECTION}{rst}",
        f"{hdr}  STAGE COUNT   {rst}: {val}{len(pipeline)}{rst}  {dim}({', '.join(stage_names)}){rst}",
    ]

    if routing:
        lines += [
            f"{hdr}  PRIMARY GROUP {rst}: {val}{routing.primary_group}{rst}",
            f"{hdr}  USER SCOPED   {rst}: {val}{routing.user_scoped}{rst}",
            f"{hdr}  ENTITY HINT   {rst}: {val}{routing.entity_hint or '—'}{rst}",
            f"{hdr}  STATUS FILTER {rst}: {val}{routing.status_filter or '—'}{rst}",
            f"{hdr}  TIME WINDOW   {rst}: {val}{routing.time_window.model_dump() if routing.time_window else '—'}{rst}",
            f"{hdr}  COMPLEXITY    {rst}: {val}{routing.query_complexity}{rst}",
        ]

    lines.append(f"{C['blue']}{C['bold']}  PIPELINE:{rst}")
    for line in json.dumps(pipeline, indent=2, default=str).splitlines():
        lines.append(f"  {dim}{line}{rst}")
    lines += [bar, ""]

    print("\n".join(lines), flush=True)