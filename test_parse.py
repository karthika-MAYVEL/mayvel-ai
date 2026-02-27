import json

query_str = """
{
  "query_type": "aggregate",
  "database": "seyo-development",
  "collection": "inspections",
  "filter": {
    "tenantId": "{tenantId}",
    "assignedTo": "{userId}",
    "isDeleted": false
  },
  "pipeline": [
    {
      "$match": {
        "tenantId": "{tenantId}",
        "assignedTo": "{userId}",
        "isDeleted": false
      }
    }
  ]
}
"""

parsed_query = json.loads(query_str)
pipe = parsed_query.get("pipeline", parsed_query) if isinstance(parsed_query, dict) else parsed_query

print("Type of pipe:", type(pipe))

from application.middleware.executor import QueryExecutor

executor = QueryExecutor("abc", "xyz")
safe = executor.prepare_query(pipe)

print("Type of safe:", type(safe))
