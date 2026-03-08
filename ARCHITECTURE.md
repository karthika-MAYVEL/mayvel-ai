# Ask Seyo: System Architecture & Request Lifecycle

This document provides a comprehensive overview of the architecture, core components, and the step-by-step request flow for the `agentic-system` service. It outlines how the system routes natural language queries, coordinates multiple specialized agents, and executes secure database operations.

## 1. High-Level Architecture Overview

The system operates on a **Multi-Agent Orchestration** pattern consisting of two primary tiers of intelligence:
1. **Tier 1 (T1) - Routing & Classification:** A Gateway/Root agent understands the user's intent and determines which domain-expert agent should handle the request.
2. **Tier 2 (T2) - Domain Generation:** Specialized sub-agents (e.g., Template, Inspection) take over to translate the natural language into precise, secure MongoDB aggregation pipelines.

The service is built on FastAPI, utilizing asynchronous communication with an Async MongoDB driver (Motor) to ensure high concurrency and responsiveness.

---

## 2. Core Components & Processes

### 2.1 API & Service Layer
- **`main.py`**: The entry point. Initializes the FastAPI application, mounts defined routers, and establishes the async MongoDB connection pool during startup.
- **`api/search_router.py`**: Exposes the primary `/ask` endpoint. Maps incoming JSON requests (query, tenantId, userId) to the service layer and returns a uniform envelope `SearchResponse`.
- **`application/services/search_service.py`**: A thin layer that connects the HTTP handler to the core orchestration engine, initializing the `SearchOrchestrator` and passing along the database connection.

### 2.2 Orchestration Engine (`core/orchestrator.py`)
The `SearchOrchestrator` acts as the system's brain. It manages the two-call T1→T2 flow:
- Controls the handover between the classification agent and domain-generation agents.
- Resolves context variables and placeholders (e.g., date logic, tenant boundaries) via `core/placeholder_resolver.py`.
- securely executes the final pipeline against the MongoDB datastore.

### 2.3 Agent Subsystems (`agents/`)
- **Root Agent (`agents/root_agent.py`)**: The T1 orchestrator. Uses LLM prompting to parse intent and produce a structured `RoutingDecision` (or fallback `ChannelPlan`). It identifies exactly which "domain" (e.g., TEMPLATE or INSPECTION) the user is asking about.
- **Agent Registry (`agents/agent_registry.py`)**: A lookup layer that maps the T1 `RoutingDecision` groups to their specific `DomainBaseAgent` class implementations.
- **Domain Sub-Agents (`agents/sub_agents/`)**: The distinct T2 domain experts (e.g., `InspectionGroupAgent`, `TemplateGroupAgent`) that generate the exact MongoDB aggregations (`QueryTemplate`) for their respective data domains.

### 2.4 Data Execution & Context
- **Placeholder Resolver (`core/placeholder_resolver.py` & `time_resolver.py`)**: Vital for translating natural language timeframes (e.g., "last 30 days") and injecting secure `tenantId` and `userId` filters dynamically into the LLM-generated JSON pipeline.

---

## 3. Request Lifecycle: In-Depth Technical Flow

Understanding this flow is critical for extending the system. When a user submits a query (e.g., *"Show me all failed safety inspections assigned to me in the last 7 days"*), the request traverses the stack as follows:

### Step 1: Ingress & Initialization (`api/search_router.py` → `application/services/search_service.py`)
1. **HTTP `POST /ask`**: 
   - **Method**: `api.search_router.ask_seyo(request: SearchRequest)`
   - **Input**: `SearchRequest(query="...", userId="...", tenantId="...")` validated via Pydantic.
2. **Service Initialization**:
   - **Method**: `search_router.py` instantiates `SearchService(tenantId, userId)`.
   - **Action**: It calls `await service.process_query(request.query)`. This legacy wrapper internally passes the request to `run_search(request)`.
   - **Database Prep**: `DatabaseConnector.get_db()` fetches the active Motor instance (established during the FastAPI lifespan event in `main.py`).

### Step 2: Tier-1 Intent Routing (`core/orchestrator.py` → `agents/root_agent.py`)
3. **Orchestrator Kickoff**:
   - **Method**: `SearchOrchestrator.search(request, db)` begins execution, tracking time and resetting `token_tracker`.
4. **Classification**:
   - **Method**: Orchestrator calls `await self._root_agent.route(request)`. (Note: Falls back to `plan(request)` if `route` is unimplemented/legacy).
   - **Action**: `RootAgent` sends the system prompt and user query to `GeminiClient`, instructing it to return a JSON object representing the `RoutingDecision`.
   - **Output**: A Pydantic `RoutingDecision` object. For example: `primary_group="INSPECTION"`, `user_scoped=True`, `time_window={"kind": "lastNDays", "amount": 7}`.

### Step 3: Tier-2 Domain Pipeline Generation (`agents/agent_registry.py` → `agents/sub_agents/*`)
5. **Dynamic Agent Resolution**:
   - **Method**: Orchestrator calls `get_group_agent(routing.primary_group)` in `agents/agent_registry.py`.
   - **Action**: Returns an instance of the corresponding domain agent (e.g., `InspectionGroupAgent`).
6. **Pipeline Generation**:
   - **Method**: Orchestrator calls `await agent.generate(routing, user_query, tenant_id, user_id)`.
   - **Action**: The Domain Agent passes the `RoutingDecision` and schema rules to the LLM to generate the raw MongoDB pipeline.
   - **Output**: A `QueryTemplate` object containing the `pipeline` (a list of MongoDB aggregation stages) containing placeholders like `<TENANT_ID>`, `<USER_ID>`, and `<START_DATE>`.

### Step 4: Resolution & Security Enforcement (`core/placeholder_resolver.py`)
7. **Context Assembly**:
   - **Method**: Orchestrator calls `build_execution_context(tenantId, userId, template)`.
   - **Action**: Resolves the `QueryTemplate.time_window` into exact Python `datetime` boundaries using `time_resolver.py`.
   - **Output**: A `context` dictionary mapping placeholder string keys to their safe, computed values.
8. **Pipeline Sanitization & Injection**:
   - **Method**: Orchestrator calls `resolve_placeholders(pipeline, context)`.
   - **Action**: Recursively walks the pipeline JSON tree, substituting `<TENANT_ID>` with the actual JWT-verified `tenantId`, `<USER_ID>` with the `userId`, and time placeholders with ISO strings. **Crucial step for multi-tenant isolation.**
   - **Output**: A fully executable and secure Python list representing the MongoDB aggregation pipeline.

### Step 5: Database Execution & Formatting (`core/orchestrator.py` → `FastAPI`)
9. **Async Execution**:
   - **Method**: Orchestrator calls `await _run_pipeline(db, pipeline)`.
   - **Action**: Calls Motor: `db["entities"].aggregate(pipeline).to_list(length=_MAX_RESULTS)`.
10. **Data Serialization**:
   - **Method**: Puts results through `_sanitize_doc(doc)`.
   - **Action**: Recursively converts un-serializable BSON types (`ObjectId`, `datetime`, `Decimal128`) into standard JSON strings/floats.
11. **Final Output**:
   - **Action**: Results are packed into an array of `ResultGroup` inside a `SearchResponse` envelope, alongside metadata like `token_usage` and `query_time_ms`.
   - **Delivery**: `api.search_router.ask_seyo` returns this envelope as an HTTP 200 `JSONResponse` to the client.
