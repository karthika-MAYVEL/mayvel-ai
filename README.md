# Ask Seyo: Agentic System

This is the FastAPI-based microservice for the "Ask Seyo" conversational agent system. It uses Google's GenAI models to translate natural language into secure MongoDB aggregation pipelines.

## Prerequisites

1.  **Python 3.11+**
2.  **MongoDB** running locally or a remote MongoDB URI.
3.  **Google Gemini API Key**

## Setup Instructions

1.  **Navigate to the project directory:**
    ```bash
    cd /home/tempuser/Documents/Projects/seyo/backend/agentic-system
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    Ensure your `.env` file is properly configured. You can copy the template:
    ```bash
    cp .env.example .env
    ```
    Open `.env` and fill in your actual Gemini API key and MongoDB connection string:
    ```env
    LLM_API_KEY=your_actual_gemini_api_key
    LLM_MODEL_NAME=gemini-2.5-flash
    PORT=8000
    HOST=0.0.0.0
    MONGO_URI=mongodb://localhost:27017  # Change if using Atlas
    MONGO_DB=seyo_db                     # Your target database name
    ```

## Running the Service

You can start the FastAPI server using `uvicorn`:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
*(The service will automatically connect to MongoDB on startup thanks to the lifespan events in `main.py`.)*

## Testing the API

You can test the API using tools like `curl`, Postman, or Thunder Client. The endpoint streams a natural language response back.

**Example 1: Checklist Intent**
```bash
curl -X POST http://localhost:8000/api/v1/ask \
     -H "Content-Type: application/json" \
     -d '{"query": "Show me all fire safety checklists"}'
```

**Example 2: Inspection Intent**
```bash
curl -X POST http://localhost:8000/api/v1/ask \
     -H "Content-Type: application/json" \
     -d '{"query": "Find me all failed inspections from last week"}'
```

**Example 3: Sequential Intent (Complex)**
```bash
curl -X POST http://localhost:8000/api/v1/ask \
     -H "Content-Type: application/json" \
     -d '{"query": "Show me all inspections for the scaffolding checklist"}'
```

### Mocking Data for Testing
If your `seyo_db` in MongoDB is currently empty, the queries will succeed but return 0 results. To test the LLM's full synthesis capabilities, you might want to open MongoDB Compass (or the `mongosh` CLI) and insert some dummy records into the `checklists` and `inspections` collections.

Example document for `checklists`:
```json
{
  "_id": { "$oid": "60a7d5b8f1b4c3d2e1f0a1b2" },
  "tenantId": "tenant_abc123",
  "title": "Weekly Scaffolding Checklist",
  "category": "Safety",
  "status": "active",
  "isDeleted": false
}
```
