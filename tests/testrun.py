"""
SEYO Inspection AI Service — Test Suite
Levels: LOW · MODERATE · HIGH  (5 queries each)
Gap between requests: 1 min 30 sec after each response
All results logged to: test_results_<timestamp>.json
"""

import requests
import json
import time
import os
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
API_URL   = "http://0.0.0.0:8005/api/v1/ai/ask"
TENANT_ID = "3a1829b0-ac0a-0274-0383-ef2db5411df6"
USER_ID   = "3a1829b0-aca4-db7b-7abb-c088ed20263b"
GAP_SEC   = 90  # 1 min 30 sec

# Output file — one file for entire run, all requests appended
RUN_TS    = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE  = f"test_results_{RUN_TS}.json"

# ─────────────────────────────────────────────────────────────────────────────
# TEST QUERIES
# ─────────────────────────────────────────────────────────────────────────────
TEST_CASES = {

    "LOW": [
        "Show all inspections",
        "Show me all completed inspections",
        "List all inspections that are in progress",
        "Show all inspections created this month",
        "Give me all inspections scheduled this week",
    ],

    "MODERATE": [
        "Show me all inspections assigned to me",
        "Give me all my inspections that are yet to start",
        "Show my observations flagged as issues",
        "List all tasks assigned to me that are overdue",
        "Show me all inspections I created in the last 7 days",
    ],

    "HIGH": [
        "Give me the top 5 most failed questions across all my audits",
        "Show me all responses submitted across inspections this month with their scores",
        "Which questions have the highest failure rate across all completed inspections",
        "Show me all observations linked to inspections I was assigned to this week",
        "Give me a breakdown of all my tasks and their linked inspection observations",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# FILE LOGGER
# ─────────────────────────────────────────────────────────────────────────────
def init_log_file(path: str):
    """Create the log file with run metadata header."""
    run_meta = {
        "run_metadata": {
            "started_at":  datetime.now().isoformat(),
            "api_url":     API_URL,
            "tenant_id":   TENANT_ID,
            "user_id":     USER_ID,
            "gap_sec":     GAP_SEC,
            "total_levels": len(TEST_CASES),
            "total_queries": sum(len(q) for q in TEST_CASES.values()),
        },
        "requests": []
    }
    with open(path, "w") as f:
        json.dump(run_meta, f, indent=2)
    print(f"  Log file : {os.path.abspath(path)}")

def append_request_log(path: str, entry: dict):
    """Append one request record into the requests[] array in the log file."""
    with open(path, "r") as f:
        data = json.load(f)
    data["requests"].append(entry)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

def finalize_log_file(path: str, summary: dict, total_sec: float):
    """Write summary block at the end of the log file."""
    with open(path, "r") as f:
        data = json.load(f)
    data["run_metadata"]["finished_at"]   = datetime.now().isoformat()
    data["run_metadata"]["total_time_sec"] = round(total_sec, 2)
    data["summary"] = summary
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def now_ts():
    return datetime.now().isoformat()

def now_str():
    return datetime.now().strftime("%H:%M:%S")

def separator(char="─", width=70):
    print(char * width)

def send_request(query: str) -> dict:
    payload = {
        "query":    query,
        "tenantId": TENANT_ID,
        "userId":   USER_ID,
    }
    sent_at = now_ts()
    start   = time.time()
    try:
        resp    = requests.post(API_URL, json=payload, timeout=60)
        elapsed = round(time.time() - start, 3)
        is_json = "application/json" in resp.headers.get("content-type", "")
        body    = resp.json() if is_json else resp.text
        return {
            "sent_at":     sent_at,
            "received_at": now_ts(),
            "elapsed_sec": elapsed,
            "status_code": resp.status_code,
            "ok":          resp.status_code == 200,
            "request_payload": payload,
            "response_body":   body,
            "error":           None,
        }
    except requests.exceptions.ConnectionError:
        return {
            "sent_at": sent_at, "received_at": now_ts(), "elapsed_sec": None,
            "status_code": None, "ok": False,
            "request_payload": payload, "response_body": None,
            "error": "Connection refused — is the service running?",
        }
    except requests.exceptions.Timeout:
        return {
            "sent_at": sent_at, "received_at": now_ts(), "elapsed_sec": None,
            "status_code": None, "ok": False,
            "request_payload": payload, "response_body": None,
            "error": "Request timed out (>60s)",
        }
    except Exception as e:
        return {
            "sent_at": sent_at, "received_at": now_ts(), "elapsed_sec": None,
            "status_code": None, "ok": False,
            "request_payload": payload, "response_body": None,
            "error": str(e),
        }

def build_log_entry(level: str, idx: int, query: str, result: dict) -> dict:
    """Build the full structured log record for one request."""
    body = result["response_body"]

    exec_meta    = {}
    llm_response = None
    exec_query   = None

    if isinstance(body, dict):
        # ── Token / timing metadata ──────────────────────────────────────────
        exec_meta = {
            "llm_calls":     body.get("llm_calls"),
            "prompt_tokens": body.get("prompt_tokens"),
            "output_tokens": body.get("output_tokens"),
            "total_tokens":  body.get("total_tokens"),
            "query_time_ms": body.get("query_time_ms"),
            "result_count":  (
                len(body["results"]) if isinstance(body.get("results"), list)
                else len(body["data"]) if isinstance(body.get("data"), list)
                else None
            ),
        }

        # ── LLM generated response (QueryTemplate from T2) ───────────────────
        # Common response keys the service may use
        llm_response = (
            body.get("query_template")      # explicit key
            or body.get("llm_response")     # alt key
            or body.get("agent_response")   # alt key
            or body.get("query_plan")       # alt key
        )
        # If not under a dedicated key, extract known QueryTemplate fields
        if llm_response is None:
            qt_keys = {
                "query_type", "database", "collection", "entity_type",
                "filter", "projection", "pipeline", "time_field", "time_window",
                "userfield", "userfield_reason", "deduplication_applied",
                "scoring_applied", "placeholders_used", "explanation",
            }
            subset = {k: body[k] for k in qt_keys if k in body}
            if subset:
                llm_response = subset

        # ── Executed MongoDB query / pipeline ────────────────────────────────
        exec_query = (
            body.get("executed_pipeline")   # explicit key
            or body.get("db_pipeline")      # alt key
            or body.get("mongo_pipeline")   # alt key
            or body.get("execution_query")  # alt key
        )
        # Fallback: pull pipeline from inside the query_template if present
        if exec_query is None and isinstance(llm_response, dict):
            exec_query = llm_response.get("pipeline") or None

    return {
        "seq":    f"{level}-{idx}",
        "level":  level,
        "index":  idx,
        "status": "PASS" if result["ok"] else "FAIL",

        # ── Input ─────────────────────────────────────────────────────────────
        "request": {
            "sent_at": result["sent_at"],
            "payload": result["request_payload"],
        },

        # ── LLM output — QueryTemplate generated by T2 ───────────────────────
        "llm_response": llm_response,

        # ── Actual MongoDB query sent to DB ───────────────────────────────────
        "execution_query": exec_query,

        # ── HTTP response envelope ────────────────────────────────────────────
        "response": {
            "received_at": result["received_at"],
            "elapsed_sec": result["elapsed_sec"],
            "status_code": result["status_code"],
            "full_body":   result["response_body"],
            "error":       result["error"],
        },

        # ── Performance counters ──────────────────────────────────────────────
        "execution": exec_meta,
    }

def print_result(entry: dict):
    status = "✅ PASS" if entry["status"] == "PASS" else "❌ FAIL"
    print(f"\n  [{entry['seq']}] {status}")
    print(f"  Query      : {entry['request']['payload']['query']}")
    if entry["response"]["error"]:
        print(f"  Error      : {entry['response']['error']}")
    else:
        print(f"  HTTP       : {entry['response']['status_code']}")
        print(f"  Time       : {entry['response']['elapsed_sec']}s")
        ex = entry["execution"]
        if ex.get("result_count") is not None:
            print(f"  Results    : {ex['result_count']} records")
        if ex.get("total_tokens"):
            print(f"  Tokens     : {ex['total_tokens']} (prompt={ex['prompt_tokens']} out={ex['output_tokens']})")
        if ex.get("query_time_ms"):
            print(f"  Query time : {ex['query_time_ms']}ms")

        # LLM response summary
        llm = entry.get("llm_response")
        if isinstance(llm, dict):
            print(f"  LLM entity : {llm.get('entity_type')}  query_type={llm.get('query_type')}")
            print(f"  LLM scope  : userfield={llm.get('userfield')}  dedup={llm.get('deduplication_applied')}")
            if llm.get("explanation"):
                print(f"  LLM note   : {llm.get('explanation')}")

        # Execution query (pipeline)
        eq = entry.get("execution_query")
        if eq:
            pipeline_str = json.dumps(eq, separators=(",", ":"))
            preview = pipeline_str[:200] + " ..." if len(pipeline_str) > 200 else pipeline_str
            print(f"  Pipeline   : {preview}")

def countdown(seconds: int):
    for remaining in range(seconds, 0, -10):
        print(f"    ⏳ Next request in {remaining}s ...", end="\r")
        time.sleep(min(10, remaining))
    print(" " * 50, end="\r")

# ─────────────────────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────────────────────
def run_level(level: str, queries: list, summary: dict, is_last_level: bool):
    separator("═")
    print(f"  LEVEL: {level}  ({len(queries)} queries)")
    separator("═")

    level_pass = 0
    level_fail = 0

    for idx, query in enumerate(queries, 1):
        result = send_request(query)
        entry  = build_log_entry(level, idx, query, result)
        append_request_log(LOG_FILE, entry)
        print_result(entry)

        if result["ok"]:
            level_pass += 1
        else:
            level_fail += 1

        is_last_request = is_last_level and (idx == len(queries))
        if not is_last_request:
            print(f"\n  ⏸  Waiting {GAP_SEC}s before next request...")
            countdown(GAP_SEC)

    summary[level] = {
        "pass":  level_pass,
        "fail":  level_fail,
        "total": len(queries),
        "pass_pct": round(level_pass / len(queries) * 100),
    }
    print(f"\n  Level {level} complete — {level_pass}/{len(queries)} passed\n")

def print_summary(summary: dict, total_sec: float):
    separator("═")
    print("  FINAL SUMMARY")
    separator("═")
    grand_pass = grand_fail = grand_total = 0
    for level, s in summary.items():
        bar = ("█" * s["pass"]) + ("░" * s["fail"])
        print(f"  {level:<10} {bar:<10}  {s['pass']}/{s['total']}  ({s['pass_pct']}%)")
        grand_pass  += s["pass"]
        grand_fail  += s["fail"]
        grand_total += s["total"]
    separator()
    pct = round(grand_pass / grand_total * 100)
    print(f"  TOTAL      {grand_pass}/{grand_total} passed  ({pct}%)")
    print(f"  Wall time  {round(total_sec / 60, 1)} min")
    print(f"  Log saved  {os.path.abspath(LOG_FILE)}")
    separator("═")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    separator("═")
    print(f"  SEYO AI Service Test Suite")
    print(f"  Started  : {now_str()}")
    print(f"  Endpoint : {API_URL}")
    print(f"  Tenant   : {TENANT_ID}")
    print(f"  User     : {USER_ID}")
    print(f"  Gap      : {GAP_SEC}s between requests")
    init_log_file(LOG_FILE)
    separator("═")

    summary    = {}
    start_time = time.time()
    levels     = list(TEST_CASES.keys())

    for i, level in enumerate(levels):
        run_level(
            level,
            TEST_CASES[level],
            summary,
            is_last_level=(i == len(levels) - 1),
        )

    total_sec = time.time() - start_time
    finalize_log_file(LOG_FILE, summary, total_sec)
    print_summary(summary, total_sec)
    print(f"\n  Finished : {now_str()}\n")


if __name__ == "__main__":
    main()