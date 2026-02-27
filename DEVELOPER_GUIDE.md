# Ask Seyo: Developer Guide & Architecture Overview

Welcome to the **Ask Seyo Agentic System**! This document is designed for new developers joining the team. It provides a crystal-clear, step-by-step breakdown of what was built during Phase 1, why specific approaches and functions were chosen, and how the core mechanics of the multi-tenant AI system work.

---

## 1. Introduction & Phase 1 Objectives

**The Goal:** To build a secure, multi-tenant conversational interface ("Ask Seyo") that allows construction managers, safety auditors, and site leads to query complex database information (Inspections, Checklists) using natural language instead of clicking through UI menus.

**The Approach:** We used a Multi-Agent Orchestration pattern (mimicking the Google Agent Development Kit - ADK handover protocol). Instead of one massive AI trying to do everything, we built a Gateway Agent that routes queries to specialized Expert Sub-Agents.

---

## 2. Architecture Overview (The Flow)

When a user asks: *"Show me all failed fire safety inspections"*, here is the exact path the request takes:

1. **`main.py (FastAPI)`**: Receives the HTTP request.
2. **`search/orchestrator.py`**: Intercepts the query and sends it to the Root Agent.
3. **`agents/root_agent.py`**: Classifies if the user is asking about a "Checklist", "Inspection", or "Sequential" (both).
4. **`agents/*_agent.py`**: The sub-agent crafts a raw MongoDB JSON query based on authorized schema templates.
5. **`middleware/executor.py`**: Intercepts the raw query, injects the user's `tenantId` (for security), and strips out dangerous operators.
6. **`infrastructure/database/mongo.py`**: Executes the safe query directly on the real MongoDB database asynchronously via Motor.
7. **`services/synthesizer.py`**: Streams the JSON results back through the LLM to format it into a friendly, human-readable paragraph.

---

## 3. Step-by-Step Implementation Breakdown

### Step 1: The Gateway (Root Agent)
**File:** `agents/root_agent.py`

*   **What it does:** Acts as the traffic cop. It uses Google Gemini to read the user's natural language and classify the "Intent".
*   **Key Function:** `classify_intent(user_query: str) -> IntentClassification`
*   **Why we did it this way:** 
    *   **Pydantic Enforcement:** We used Pydantic's `BaseModel` and `Field` validators to force the LLM to return strictly structured JSON (`intent`, `confidence`, `reasoning`). This prevents unpredictable string outputs.
    *   **Best Practice:** A single routing layer ensures that specialized agents are only invoked when a query strictly matches their domain, saving tokens and improving accuracy.

### Step 2: The Domain Experts (Sub-Agents)
**Files:** `agents/checklist_agent.py` & `agents/inspection_agent.py`

*   **What they do:** They hold specific "Skills". They know the exact structure of their respective MongoDB collections.
*   **Key Function:** `generate_query(user_query: str, context: dict = None) -> str`
*   **Why we did it this way:** 
    *   **Prompt Configuration:** The system instructions for these agents are decoupled and stored in `config/prompts.yaml`. If the database schema changes, a developer only updates the YAML file without touching Python code.
    *   **Best Practice:** Context Injection. The `inspection_agent` accepts a `context` parameter. This allows it to receive IDs resolved from previous steps, enabling complex multi-turn searches.

### Step 3: ADK Handover Orchestration
**File:** `search/orchestrator.py`

*   **What it does:** The brain of the operation. It manages communication between agents natively.
*   **Key Function:** `async def execute_search(self, user_query: str, db=None, executor=None) -> dict`
*   **Why we did it this way:**
    *   **Sequential Logic:** If the Root Agent detects a "Sequential" intent (e.g., "Find the fire checklist, then show its inspections"), the orchestrator handles it autonomously. It asks the Checklist agent for a query, runs it against the database to get the `checklistId`, and then hands that ID explicitly to the Inspection agent.
    *   **Best Practice:** Asynchronous Handover. By making the orchestrator `async`, it doesn't block the main thread while waiting for intermediate database queries to resolve.


### Step 4: The Security Middleware (Executor)
**File:** `middleware/executor.py`

*   **What it does:** The firewall between the AI and the Database. It guarantees multi-tenant data isolation.
*   **Key Function:** `prepare_query(self, pipeline: list) -> list`
*   **Why we did it this way:**
    *   **No Hallucinations:** LLMs can hallucinate. If an LLM accidentally generates a query to fetch *all* tenants, the Executor forcefully overwrites the `{tenantId}` string with the verified Session JWT identity.
    *   **Sanitization:** The `_validate_and_sanitize` recursive function crawls the JSON tree and actively deletes `$where` or `$function` operators, preventing NoSQL injection attacks. It also forcefully injects `isDeleted: false` to ensure archived records are ignored.
    *   **Best Practice:** Zero-Trust. We treat the LLM output as untrusted user input. 

### Step 5: Streaming Response (Synthesizer)
**File:** `services/synthesizer.py`

*   **What it does:** Converts the raw JSON database payload back into natural language.
*   **Key Function:** `synthesize_stream(self, original_query: str, db_results: dict)`
*   **Why we did it this way:**
    *   **Token Streaming:** We used `generate_content_stream()` via `yield`. Instead of making the user wait 10 seconds for a massive database summary, the UI starts printing characters immediately as the LLM thinks.
    *   **Best Practice:** Generators (`yield`) map perfectly to FastAPI's `StreamingResponse`, resulting in an incredibly fast Time-To-First-Byte (TTFB).

### Step 6: Native Async Database Binding
**File:** `infrastructure/database/mongo.py` & `main.py`

*   **What it does:** Connects the API to MongoDB.
*   **Key Function:** `lifespan(app: FastAPI)`
*   **Why we did it this way:**
    *   **Motor (Async MongoDB):** We avoided `pymongo` (which is synchronous) and used `AsyncIOMotorClient`. Because FastAPI handles thousands of concurrent requests via asyncio, using a synchronous DB driver would crash the event loop under load.
    *   **Best Practice:** Connection Pooling. We initialize the connection once during the `lifespan` startup event, rather than opening and closing a connection for every single HTTP request.

---

## 4. Engineering Standards Applied

To adhere to the Seyo Engineering Rulebook, the following implementations are strictly enforced across this service:

1. **Central Configuration (`core/config.py`):** Secrets and host setups are pulled from `.env` using OS loaders formatted in `UPPER_SNAKE_CASE`. No magic strings exist in the code paths.
2. **Pydantic Validation:** All incoming requests (`AskRequest`) and outgoing classifications use strict Pydantic `Field` descriptions for automatic OpenAPI interface documentation.
3. **Docstrings:** Every class and method has standard Python multi-line docstrings detailing arguments and return types.
4. **API Versioning:** Routes are explicitly versioned (e.g., `/api/v1/ask`) to allow for future iteration without breaking backwards compatibility.

---

## 5. Next Steps for New Developers

If you are picking up this project, your immediate next steps should be:

1. **Get your `.env` running:** Ensure you have your `GEMINI_API_KEY` and MongoDB URI set up.
2. **Read `config/prompts.yaml`:** This is where the magic happens. If you want to add a completely new agent (e.g., "Schedule Agent"), you define its behavior here.
3. **Explore `search/orchestrator.py`:** If you want to add new intents, you will need to add an `elif intent == "Schedule":` block in the orchestrator to tell it how to handle the new domain.
4. **Extend the Executor:** Look at `middleware/executor.py`. As the database schema grows, you may need to add new recursive checks or soft-delete enforcement rules.
