import time
import requests
import json
import sys

URL = "http://127.0.0.1:8005/api/v1/ai/ask"

PAYLOADS = [
    {
        "query": "Give me the top 5 most failed questions across all my audits",
        "tenantId": "3a1829b0-ac0a-0274-0383-ef2db5411df6",
        "userId": "3a1829b0-aca4-db7b-7abb-c088ed20263b"
    },
    {
        "query": "Show me all active inspections assigned to me",
        "tenantId": "3a1829b0-ac0a-0274-0383-ef2db5411df6",
        "userId": "3a1829b0-aca4-db7b-7abb-c088ed20263b"
    },
    {
        "query": "List all observations flagged this week",
        "tenantId": "3a1829b0-ac0a-0274-0383-ef2db5411df6",
        "userId": "3a1829b0-aca4-db7b-7abb-c088ed20263b"
    }
]

def run_tests():
    for i, payload in enumerate(PAYLOADS, 1):
        print(f"\n--- TEST {i} ---")
        print(f"QUERY: {payload['query']}")
        try:
            resp = requests.post(URL, json=payload)
            print(f"STATUS CODE: {resp.status_code}")
            data = resp.json()
            # print meta data which contains the mongo query
            meta = data.get("meta", {})
            query_used = meta.get("executed_mongo_query")
            print("MONGO PIPELINE/QUERY:")
            print(json.dumps(query_used, indent=2))
            llm_responses = meta.get("llm_responses", [])
            print("LLM RESPONSES:")
            print(json.dumps(llm_responses, indent=2))
        except Exception as e:
            print(f"ERROR: {e}")
            
        if i < len(PAYLOADS):
            print("Waiting 5 seconds before next request...")
            time.sleep(5)

if __name__ == "__main__":
    run_tests()
