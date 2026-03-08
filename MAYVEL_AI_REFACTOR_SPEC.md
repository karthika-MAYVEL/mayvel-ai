# MAYVEL-AI — Complete Refactoring & Cleanup Specification
> **Audience:** Developer / Prompt Engineer executing the full service cleanup.  
> **Scope:** Every layer from FastAPI entrypoint to MongoDB execution, all prompts, models, tests, and README.  
> **Rule:** Read every section before touching a single file. Execute in order.

---

## 0. GROUND RULES (Non-Negotiable)

| Rule | Requirement |
|------|-------------|
| **One responsibility per file** | No file mixes routing, business logic, and DB access |
| **One prompt per agent** | Each domain agent owns one self-contained YAML — no assembly, no merging |
| **One execution path** | T1 → T2 → MongoDB. No legacy fallbacks in production code |
| **No silent swallowing** | Every exception must be logged with full context before re-raise or clean return |
| **No hardcoded strings** | Collection names, group names, limits → constants at module top |
| **Type hints everywhere** | All function signatures must carry full Python type hints |
| **Docstrings on every public symbol** | Format: one-line summary + `@param` / `@returns` |
| **No dead code** | No commented-out blocks, no unreachable code after return/raise |

---

## 1. CANONICAL DIRECTORY STRUCTURE

```
backend/
├── main.py                         # FastAPI app factory, lifespan, middleware
│
├── api/                            # Presentation layer — HTTP only
│   ├── __init__.py
│   ├── router.py                   # Mounts all sub-routers
│   └── routes/
│       ├── ask.py                  # POST /api/v1/ai/ask
│       └── health.py               # GET  /api/v1/health
│
├── application/                    # Application layer — use-case orchestration
│   ├── __init__.py
│   └── search_service.py           # SearchService: validates, calls orchestrator, returns response
│
├── agents/                         # Agent layer — all LLM agents
│   ├── __init__.py
│   ├── agent_registry.py           # get_group_agent(group: str) → GroupAgent
│   ├── root_agent.py               # RootAgent: route(request) → RoutingDecision
│   └── sub_agents/
│       ├── __init__.py
│       ├── base_agent.py           # Abstract base: load_prompt(), generate() interface
│       ├── domain_base_agent.py    # Shared domain logic: prompt loading, LLM call, parse
│       └── groups/
│           ├── __init__.py
│           ├── inspection_agent.py # InspectionGroupAgent
│           ├── task_agent.py       # TaskGroupAgent
│           ├── workflow_agent.py   # WorkflowGroupAgent
│           └── dashboard_agent.py  # DashboardGroupAgent
│
├── core/                           # Infrastructure cross-cutting concerns
│   ├── __init__.py
│   ├── orchestrator.py             # T1→T2→DB pipeline coordinator
│   ├── placeholder_resolver.py     # build_execution_context(), resolve_placeholders()
│   ├── time_resolver.py            # Resolves time_window dicts → datetime bounds
│   └── logger.py                   # get_app_logger(name) factory
│
├── infrastructure/                 # External system adapters
│   ├── __init__.py
│   └── database.py                 # MongoDB Motor connection, get_db()
│
├── llm_sdk/                        # LLM client wrappers
│   ├── __init__.py
│   ├── gemini.py                   # GeminiClient: generate_json()
│   └── token_tracker.py            # Per-request token counter
│
├── models/                         # Pure Pydantic data contracts
│   ├── __init__.py
│   ├── search_request.py           # SearchRequest
│   ├── search_response.py          # SearchResponse, ResultGroup
│   ├── routing_decision.py         # RoutingDecision
│   ├── channel_plan.py             # ChannelPlan, IndependentChannel, ChainChannel, ScopeHints
│   └── query_template.py           # QueryTemplate (LLM output contract)
│
├── knowledge/                      # All prompt YAML files — zero Python logic
│   ├── root_agent.yaml             # Root agent classification prompt
│   └── groups/
│       ├── inspection.yaml         # Complete self-contained inspection prompt
│       ├── task.yaml               # Complete self-contained task prompt
│       ├── workflow.yaml           # Complete self-contained workflow prompt
│       └── dashboard.yaml          # Complete self-contained dashboard prompt
│
├── config/                         # Configuration
│   ├── __init__.py
│   └── settings.py                 # Pydantic BaseSettings — all env vars
│
├── utils/                          # Pure utility functions (no side effects)
│   ├── __init__.py
│   ├── sanitizer.py                # _sanitize_doc(): BSON → JSON-serialisable
│   └── json_parser.py              # Safe JSON parsing with fence stripping
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Fixtures: mock db, mock LLM, sample requests
│   ├── unit/
│   │   ├── test_root_agent.py
│   │   ├── test_placeholder_resolver.py
│   │   ├── test_time_resolver.py
│   │   └── test_sanitizer.py
│   └── integration/
│       ├── test_inspection_agent.py
│       ├── test_orchestrator.py
│       └── test_ask_route.py
│
├── .env.example                    # Template — never commit .env
├── requirements.txt
├── Makefile                        # Convenience targets: run, test, lint, format
└── README.md
```

---

## 2. LAYER-BY-LAYER SPECIFICATION

---

### 2.1 PRESENTATION LAYER — `api/`

**File: `api/routes/ask.py`**

```
RESPONSIBILITY: Accept HTTP POST, validate body, call SearchService, return HTTP response.
DO NOT: call DB, call LLM, parse anything, build pipelines.

ENDPOINT:   POST /api/v1/ai/ask
REQUEST:    SearchRequest  { query: str, tenantId: str, userId: str }
RESPONSE:   SearchResponse { success, data, meta, error }

RULES:
  - Inject db via FastAPI Depends(get_db)
  - Inject service via FastAPI Depends(get_search_service)
  - Log: [api.ask] Received /ask user=X tenant=Y query=Z
  - Catch ALL exceptions → return 500 with structured error body, never let FastAPI default handler fire
  - Never import orchestrator, agents, or models beyond SearchRequest/SearchResponse
```

---

### 2.2 APPLICATION LAYER — `application/search_service.py`

```
RESPONSIBILITY: Use-case orchestration. Receives a validated SearchRequest,
                calls orchestrator, maps result to HTTP response shape.

RULES:
  - SearchService.__init__(orchestrator: SearchOrchestrator)
  - async def search(request: SearchRequest, db) → dict
  - Only maps SearchResponse → { success, data, meta, error } dict
  - Does NOT parse LLM output, does NOT touch MongoDB
  - Log: [search_service] tenant=X query=Y
  - Log: [search_service] Search complete: N results across M groups
```

---

### 2.3 AGENT LAYER

#### 2.3.1 `agents/root_agent.py`

```
RESPONSIBILITY: Classify natural language query → RoutingDecision (T1).

PUBLIC API:
  async def route(request: SearchRequest) → RoutingDecision

INTERNAL FLOW:
  route()
    → _classify()        # LLM call → ChannelPlan JSON → validated ChannelPlan
    → _to_routing_decision()  # ChannelPlan → RoutingDecision

_classify() rules:
  - If no LLM client → _fallback_plan() (keyword heuristic)
  - Strip ```json fences before json.loads()
  - On ANY parse failure → _fallback_plan(), log error, do NOT raise

_to_routing_decision() rules:
  - primary_group  = _ENTITY_TO_GROUP[first independent entity] or 'INSPECTION'
  - user_scoped    = True if scope_hints.userfield OR "my"/"assigned to me" in query
  - complexity     = 'complex' if chains else 'simple'
  - All fields must be populated — no Optional fields left as None silently

_ENTITY_TO_GROUP map (must cover ALL known entity types):
  inspection, inspectionchecklist, inspectionexecution,
  inspectionobservation, inspectionstatus, inspectionresponse, inspectionscore
  → 'INSPECTION'

  task, taskobservation, taskcompletion
  → 'TASK'

  workflow, workflowexecution, workflowtransition
  → 'WORKFLOW'

  dashboard, activity
  → 'DASHBOARD'

DELETED from this file:
  - classify_intent()         (retired legacy shim)
  - IntentClassification      (retired legacy model)
  - plan()                    (replaced by route())
```

#### 2.3.2 `agents/sub_agents/domain_base_agent.py`

```
RESPONSIBILITY: Shared logic for all GroupAgents.

RULES:
  - _KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "knowledge" / "groups"
  - _load_prompt(group_yaml_stem: str) → str
      Reads _KNOWLEDGE_DIR / f"{group_yaml_stem}.yaml" as raw text.
      NO yaml.safe_load(). NO section extraction. The ENTIRE file is the system prompt.
      Raises FileNotFoundError clearly if missing.

  - async generate(routing, user_query, tenant_id, user_id) → QueryTemplate
      1. system_prompt = self._load_prompt()
      2. user_msg = self._build_user_message(routing, user_query)
      3. raw = self._llm.generate_json(prompt=user_msg, system_instruction=system_prompt)
      4. parsed = safe_parse_json(raw)           # from utils/json_parser.py
      5. return QueryTemplate.model_validate(parsed)

  - _build_user_message() must include:
      - Original user query
      - entity_hint from routing
      - status_filter if present
      - time_window if present
      - user_scoped flag
```

#### 2.3.3 `agents/sub_agents/groups/inspection_agent.py`

```
RESPONSIBILITY: Generate QueryTemplate for the INSPECTION domain.

class InspectionGroupAgent(DomainBaseAgent):
    _GROUP_YAML = "inspection"

    Entities owned:
      Inspection, InspectionChecklist, InspectionExecution,
      InspectionObservation, InspectionStatus, InspectionResponse, InspectionScore

    Overrides: none required — all logic lives in domain_base_agent + inspection.yaml
```

---

### 2.4 CORE LAYER

#### 2.4.1 `core/orchestrator.py`

```
RESPONSIBILITY: Single pipeline coordinator. T1 → T2 → MongoDB.

RULES:
  - NO legacy _dispatch_legacy(), NO plan(), NO get_agent() calls
  - search(request, db) is the ONLY public method
  - _route() returns RoutingDecision or None on hard failure
      On None → return clean empty SearchResponse, routing_path='failed'
  - _dispatch(request, routing, db, start_ms) → SearchResponse
      1. get_group_agent(routing.primary_group)
      2. agent.generate(routing=routing, user_query=..., tenant_id=..., user_id=...)
      3. build_execution_context() + resolve_placeholders()
      4. _log_query_plan()
      5. _run_pipeline(db, pipeline)
      6. Build and return SearchResponse
  - _log_query_plan() must be a standalone module function, never defined inside another function
  - _serialize_for_log() must be a standalone module function
  - execute_search() shim kept ONLY for backward compat with SearchService until it migrates
```

#### 2.4.2 `core/placeholder_resolver.py`

```
RESPONSIBILITY: Replace {{TENANT_ID}}, {{USER_ID}}, {{NOW}}, {{START}}, {{END}}
                inside a resolved MongoDB pipeline.

RULES:
  - build_execution_context(tenant_id, user_id, template) → dict
      Always includes: TENANT_ID, USER_ID, NOW
      Conditionally includes: START, END from template.time_bounds if present
  - resolve_placeholders(pipeline: list, context: dict) → list
      Deep traversal — handles nested dicts, lists, strings
      String replacement only (never eval, never exec)
      Unknown placeholders: log warning, leave unchanged
```

#### 2.4.3 `core/time_resolver.py`  ← NEW FILE (extract from placeholder_resolver)

```
RESPONSIBILITY: Convert a time_window dict → (start: datetime, end: datetime).

RULES:
  - resolve_time_window(time_window: dict) → tuple[datetime, datetime]
  - Supported kinds:
      today, thisWeek, thisMonth, lastMonth,
      lastNDays (requires amount: int),
      absolute (requires from_date, to_date ISO strings)
  - All datetimes returned as UTC-aware
  - Unknown kind → raise ValueError clearly
  - This is PURE logic — no LLM calls, no DB, no side effects
```

---

### 2.5 MODELS LAYER — `models/`

```
ALL models are pure Pydantic v2. Zero business logic. Zero imports from agents/core.

query_template.py — QueryTemplate:
  entity_type: str
  pipeline: list[dict]
  time_bounds: dict | None          # populated by time_resolver, consumed by placeholder_resolver
  explanation: str | None           # LLM self-explanation for debugging

routing_decision.py — RoutingDecision:
  primary_group: str                # e.g. 'INSPECTION'
  secondary_groups: list[str]       # e.g. ['TASK']
  user_scoped: bool
  entity_hint: str | None           # raw entity from LLM e.g. 'inspectionchecklist'
  status_filter: str | None
  time_window: dict | None
  query_complexity: Literal['simple', 'complex']

search_request.py — SearchRequest:
  query: str
  tenantId: str
  userId: str

search_response.py — SearchResponse, ResultGroup:
  SearchResponse:
    summary: str
    total_count: int
    groups: list[ResultGroup]
    metadata: dict

  ResultGroup:
    entity_type: str
    count: int
    items: list[dict]
```

---

### 2.6 KNOWLEDGE LAYER — `knowledge/`

**THE MOST IMPORTANT RULE FOR PROMPTS:**

```
Each YAML file IS the system prompt — raw text, top to bottom.
NO assembly_order keys. NO section merging in Python.
Python reads the file as a plain string and passes it to the LLM.
```

#### `knowledge/groups/inspection.yaml` — Complete Specification

```
MUST CONTAIN (in this order, as readable prose/yaml text):

1. ROLE DECLARATION
   "You are the Inspection Query Agent for the Mayvel platform..."

2. DATABASE CONTRACT
   - Collection name: entities
   - Tenant isolation: EVERY query MUST include { "entityType": "...", "tenantId": "{{TENANT_ID}}" }
   - Output format: valid JSON only, no markdown, no explanation outside the JSON block
   - Output schema: QueryTemplate with fields: entity_type, pipeline, explanation

3. ENTITY CATALOGUE (all 7 inspection entities)
   For each entity:
     - entityType value (exact string as stored in MongoDB)
     - Key fields and their MongoDB field paths
     - Common query patterns

4. QUERY PATTERNS P1–P6
   P1: List all (no filter beyond tenant)
   P2: Filter by status
   P3: Filter by assignee/user
   P4: Filter by time window (uses {{START}} {{END}})
   P5: Search by keyword
   P6: Related entity lookup (e.g. checklists for an inspection)

5. TIME PLACEHOLDER RULES
   - {{NOW}}   = current UTC datetime
   - {{START}} = window start datetime
   - {{END}}   = window end datetime
   - Never hardcode dates. Always use placeholders.

6. DEDUPLICATION RULES
   - When multiple patterns apply, prefer the most specific
   - Never generate duplicate $match stages

7. OUTPUT SCHEMA (JSON example)
   {
     "entity_type": "inspection",
     "pipeline": [ ... ],
     "explanation": "..."
   }

8. FEW-SHOT EXAMPLES (minimum 3)
   Example 1: "list all inspections" → P1 pipeline
   Example 2: "show failed inspections this month" → P2 + P4
   Example 3: "inspections assigned to me" → P3 with {{USER_ID}}
```

---

### 2.7 LLM SDK LAYER — `llm_sdk/`

#### `llm_sdk/gemini.py`

```
RESPONSIBILITY: Single HTTP/SDK wrapper for Gemini API.

RULES:
  - GeminiClient.__init__(): load API key from settings, log if missing
  - generate_json(prompt, system_instruction, agent) → str
      Returns raw LLM string — does NOT parse JSON
      Logs: [llm_sdk.gemini] [AGENT:{agent}] IN: '...' | OUT: '...' | TOKENS: in=X out=Y
      On API error → raise, do NOT swallow
  - client property → None if no API key (enables offline mode detection)
```

#### `llm_sdk/token_tracker.py`

```
RESPONSIBILITY: Thread-local per-request token counting.

RULES:
  - reset()             clears all counters
  - record(in, out)     adds to running totals
  - get_totals() → dict { llm_calls, prompt_tokens, output_tokens, total_tokens }
```

---

### 2.8 CONFIG LAYER — `config/settings.py`

```python
# ALL environment variables defined here. Nothing else reads os.environ directly.

class Settings(BaseSettings):
    # LLM
    GEMINI_API_KEY: str = ""

    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "mayvel"

    # App
    APP_ENV: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    MAX_RESULTS: int = 200

    model_config = SettingsConfig(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
```

---

### 2.9 UTILS LAYER — `utils/`

#### `utils/sanitizer.py`

```python
# _sanitize_doc() extracted from orchestrator.py
# Converts BSON types → JSON-serialisable Python types
# Handles: ObjectId, datetime, Decimal128, bytes, nested dicts/lists
# Import bson lazily — keep it as optional dependency
```

#### `utils/json_parser.py`

```python
# safe_parse_json(raw: str) → dict
# 1. Strip leading/trailing whitespace
# 2. Strip ```json ... ``` or ``` ... ``` fences
# 3. json.loads()
# 4. On failure → raise ValueError with the raw string for debugging
```

---

### 2.10 INFRASTRUCTURE LAYER — `infrastructure/database.py`

```python
# Motor async MongoDB client
# get_db() → AsyncGenerator[AsyncIOMotorDatabase, None]
#   Used as FastAPI dependency
# connect_db() / disconnect_db() called from main.py lifespan
# Log connection URI (mask password if present)
# On connection failure → raise RuntimeError clearly
```

---

## 3. BUGS TO FIX BEFORE ANYTHING ELSE

Fix these in order. Do not refactor until these are resolved.

### BUG 1 — `orchestrator.py`: `_log_query_plan` is split by dead code (CRITICAL)

**What happened:** `serialize_for_log()` was defined in the middle of `_log_query_plan()`, making everything after it (pipeline printing, the closing bar, `print()`) unreachable dead code after `serialize_for_log`'s `return` statement.

```python
# BROKEN — function defined inside another function, splits it in half
def _log_query_plan(...):
    lines = [...]

    def serialize_for_log(node):   # ← inserted here, splits the function
        ...
        return node

    lines += [...]   # ← NEVER REACHED
    print(...)       # ← NEVER REACHED
```

**Fix:** Move `_serialize_for_log` to module level. Rename with underscore prefix.

---

### BUG 2 — `orchestrator.py`: Legacy path calls retired `get_agent()` (CRITICAL)

```python
# BROKEN
agent = get_agent(entity)             # → raises "get_agent is retired"

# FIX: remove the entire legacy path. Use _dispatch() only.
```

---

### BUG 3 — `root_agent.py`: `route()` does not exist (CRITICAL)

```python
# BROKEN: orchestrator calls self._root_agent.route(request)
# root_agent.py only defines plan(), not route()
# → AttributeError → silent fallback → legacy path → BUG 2 → crash

# FIX: implement route() as shown in root_agent.py spec above
```

---

### BUG 4 — `root_agent.py`: `classify_intent()` shim references a deleted path (LOW)

```python
# classify_intent() calls asyncio.get_event_loop().run_until_complete(agent.plan(...))
# plan() is being retired. This shim is only called by retired legacy code.
# FIX: delete classify_intent() and IntentClassification entirely.
```

---

### BUG 5 — `_log_query_plan`: `_COLLECTION` referenced as hardcoded string (LOW)

```python
# BROKEN (inside the dead-code block, but still wrong principle)
f"{hdr}  COLLECTION    {rst}: {val}entities{rst}"

# FIX: reference the module constant
f"{hdr}  COLLECTION    {rst}: {val}{_COLLECTION}{rst}"
```

---

## 4. EXECUTION ORDER

Execute these steps in strict order. Commit after each phase.

```
Phase 1 — Fix critical bugs (BUG 1, 2, 3)
  ├── Fix orchestrator.py: move _serialize_for_log, remove legacy path
  ├── Fix root_agent.py: implement route(), delete plan()/classify_intent()
  └── Smoke test: POST /ask "list all inspections" → expect data in response

Phase 2 — Directory restructure
  ├── Create new directory tree
  ├── Move files to correct locations (do not rewrite yet)
  ├── Update all imports
  └── Smoke test again

Phase 3 — Extract & clean each layer
  ├── Extract time_resolver.py from placeholder_resolver.py
  ├── Extract sanitizer.py and json_parser.py from orchestrator.py
  ├── Clean config/settings.py (replace all os.environ calls)
  ├── Clean infrastructure/database.py
  └── Unit test each extracted module

Phase 4 — Consolidate knowledge/prompts
  ├── Write inspection.yaml as single self-contained file
  ├── Remove assembly_order, base_query_prompt.yaml, system_prompt.yaml
  ├── Update domain_base_agent._load_prompt() to read raw text only
  └── Integration test InspectionGroupAgent end-to-end

Phase 5 — Add remaining domain agents
  ├── task.yaml + TaskGroupAgent
  ├── workflow.yaml + WorkflowGroupAgent
  └── dashboard.yaml + DashboardGroupAgent

Phase 6 — Tests
  ├── Unit tests for all utils, resolvers, models
  ├── Integration tests for each agent
  └── End-to-end test for full /ask pipeline

Phase 7 — README + Makefile
```

---

## 5. REQUEST → RESPONSE FLOW (Final State)

```
POST /api/v1/ai/ask
  { query, tenantId, userId }
        │
        ▼
  api/routes/ask.py
  (HTTP validation only)
        │
        ▼
  application/search_service.py
  (use-case orchestration)
        │
        ▼
  core/orchestrator.py → search()
        │
        ├──[T1]─▶ agents/root_agent.py → route()
        │           │
        │           ├── llm_sdk/gemini.py → generate_json()
        │           │     (system: root_agent.yaml, user: query)
        │           │
        │           └── _to_routing_decision()
        │                 RoutingDecision {
        │                   primary_group: "INSPECTION",
        │                   user_scoped: false,
        │                   entity_hint: "inspection",
        │                   time_window: null
        │                 }
        │
        ├──[T2]─▶ agents/agent_registry.py → get_group_agent("INSPECTION")
        │           │
        │           └── InspectionGroupAgent.generate()
        │                 │
        │                 ├── knowledge/groups/inspection.yaml  (raw system prompt)
        │                 ├── llm_sdk/gemini.py → generate_json()
        │                 └── utils/json_parser.py → safe_parse_json()
        │                       QueryTemplate {
        │                         entity_type: "inspection",
        │                         pipeline: [
        │                           { $match: { entityType: "inspection",
        │                                       tenantId: "{{TENANT_ID}}" } },
        │                           { $sort: { createdAt: -1 } },
        │                           { $limit: 50 }
        │                         ]
        │                       }
        │
        ├──[T3]─▶ core/placeholder_resolver.py
        │           build_execution_context() → { TENANT_ID, USER_ID, NOW }
        │           resolve_placeholders()    → concrete pipeline
        │                 pipeline: [
        │                   { $match: { entityType: "inspection",
        │                               tenantId: "3a162b9b-..." } },
        │                   { $sort: { createdAt: -1 } },
        │                   { $limit: 50 }
        │                 ]
        │
        ├──[LOG]─▶ core/orchestrator._log_query_plan()
        │           (coloured terminal output of resolved pipeline)
        │
        └──[T4]─▶ infrastructure/database.py (Motor)
                    db["entities"].aggregate(pipeline)
                    → list[dict] (raw BSON docs)
                    → utils/sanitizer._sanitize_doc() per doc
                    → list[dict] (JSON-safe)
                          │
                          ▼
                    SearchResponse {
                      summary: "Found 12 result(s) across inspection.",
                      total_count: 12,
                      groups: [{ entity_type: "inspection", count: 12, items: [...] }],
                      metadata: { routing_path: "two_call", token_usage: {...} }
                    }
                          │
                          ▼
                    api/routes/ask.py
                    → HTTP 200 { success: true, data: [...], meta: {...}, error: null }
```

---

## 6. README.md TEMPLATE

````markdown
# Mayvel AI — Agentic Search Service

Natural language query interface over MongoDB using a multi-agent LLM pipeline.

## Architecture

```
API → SearchService → Orchestrator → RootAgent (T1) → GroupAgent (T2) → MongoDB
```

## Prerequisites

- Python 3.11+
- MongoDB 6.0+
- Gemini API key

## Setup

```bash
git clone https://github.com/karthika-MAYVEL/mayvel-ai.git
cd mayvel-ai/backend

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env — set GEMINI_API_KEY and MONGO_URI
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_API_KEY` | Google Gemini API key | *(required)* |
| `MONGO_URI` | MongoDB connection string | `mongodb://localhost:27017` |
| `MONGO_DB_NAME` | Target database | `mayvel` |
| `MAX_RESULTS` | Max docs returned | `200` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

## Running

```bash
make run
# or
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Testing

```bash
make test
# or
pytest tests/ -v
```

## Example Request

```bash
curl -X POST http://localhost:8000/api/v1/ai/ask \
  -H "Content-Type: application/json" \
  -d '{
    "query": "list all inspections",
    "tenantId": "3a162b9b-5195-fd8d-0fe4-42356e11c031",
    "userId":   "3a162ba0-6f23-b242-566a-63f8387e045e"
  }'
```

## Domain Agents

| Agent | Group Key | Entities Covered |
|-------|-----------|-----------------|
| InspectionGroupAgent | `INSPECTION` | Inspection, Checklist, Execution, Observation, Status, Response, Score |
| TaskGroupAgent | `TASK` | Task, TaskObservation, TaskCompletion |
| WorkflowGroupAgent | `WORKFLOW` | Workflow, WorkflowExecution, WorkflowTransition |
| DashboardGroupAgent | `DASHBOARD` | Aggregations, KPIs, Activity |

## Adding a New Domain Agent

1. Create `knowledge/groups/{domain}.yaml` (self-contained prompt)
2. Create `agents/sub_agents/groups/{domain}_agent.py` extending `DomainBaseAgent`
3. Register in `agents/agent_registry.py`
4. Add entity → group mappings to `agents/root_agent._ENTITY_TO_GROUP`
5. Add tests in `tests/integration/test_{domain}_agent.py`
````

---

## 7. MAKEFILE

```makefile
.PHONY: run test lint format clean

run:
	uvicorn main:app --host 0.0.0.0 --port 8000 --reload

test:
	pytest tests/ -v --tb=short

lint:
	ruff check .

format:
	ruff format .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
```

---

## 8. `.env.example`

```env
# LLM
GEMINI_API_KEY=your-gemini-api-key-here

# MongoDB
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=mayvel

# App
APP_ENV=development
LOG_LEVEL=INFO
MAX_RESULTS=200
```

---

## 9. CHECKLIST — Definition of Done

Before marking this refactor complete, verify every item:

- [ ] `POST /ask "list all inspections"` returns `data` array with real documents
- [ ] Terminal shows coloured `PRE-EXECUTION QUERY PLAN` block including resolved pipeline JSON
- [ ] `routing_path` in metadata is `"two_call"` — never `"legacy_channel_plan"`
- [ ] No `get_agent()` calls exist anywhere in the codebase
- [ ] No `plan()` or `classify_intent()` calls exist anywhere
- [ ] `assembly_order` key does not exist in any YAML file
- [ ] `base_query_prompt.yaml` is deleted
- [ ] `system_prompt.yaml` is deleted
- [ ] All files in `knowledge/groups/` are standalone complete prompts
- [ ] `pytest tests/` passes with zero failures
- [ ] `ruff check .` reports zero errors
- [ ] `.env` is in `.gitignore`
- [ ] `README.md` covers setup, config, run, test, and example request
