import asyncio
import json
from application.orchestrators.query_orchestrator import SearchOrchestrator
from presentation.models.search_request import SearchRequest

PAYLOADS = [
    {
        "query": "Give me the top 5 most failed questions across all my audits",
        "tenantId": "3a1829b0-ac0a-0274-0383-ef2db5411df6",
        "userId": "3a1829b0-aca4-db7b-7abb-c088ed20263b"
    },
    {
        "query": "Show me all active inspections assigned to me",
        "tenantId": "11111111-1111-1111-1111-111111111111",
        "userId": "22222222-2222-2222-2222-222222222222"
    },
    {
        "query": "List all observations flagged this week",
        "tenantId": "33333333-3333-3333-3333-333333333333",
        "userId": "44444444-4444-4444-4444-444444444444"
    }
]

async def run_tests():
    orchestrator = SearchOrchestrator()
    for i, p in enumerate(PAYLOADS, 1):
        print(f"\n{'='*40}\nTEST {i}: {p['query']}\n{'='*40}")
        req = SearchRequest(**p)
        try:
            res = await orchestrator.search(req)
            print("PIPELINE EXECUTED:")
            print(json.dumps(res.metadata.get("executed_mongo_query", []), indent=2))
        except Exception as e:
            print(f"ERROR: {e}")
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(run_tests())
