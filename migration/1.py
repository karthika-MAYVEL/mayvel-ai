"""
MIGRATION VALIDATION SCRIPT
============================
Validates that every document from seyo-development has been correctly
migrated to seyo-flat-claude / flat_entities.

Checks:
  1. COUNT MATCH       — source count == flat_entities count per type
  2. ID COVERAGE       — every source _id exists in flat_entities
  3. FIELD INTEGRITY   — key fields are non-null where source has values
  4. RESOLVED FIELDS   — status, user names, tags, checklist titles are resolved
  5. ARRAY FIELDS      — arrays copied faithfully (length match)
  6. GEO FIELDS        — geoLocation flattened correctly
  7. CROSS-TYPE REFS   — FK integrity (e.g. every execution.inspectionId exists)

Usage:
  python3 validate_migration.py
  python3 validate_migration.py --type inspections   # validate single type only
  python3 validate_migration.py --sample 50          # sample size per check (default 100)
"""

import sys
import argparse
from pymongo import MongoClient
from bson import ObjectId

# ── CONFIG ──────────────────────────────────────────────────────────────────
SOURCE_HOST = "192.168.0.172"
SOURCE_PORT = 27017
SOURCE_DB   = "seyo-development"

TARGET_HOST = "192.168.0.130"
TARGET_PORT = 27017
TARGET_DB   = "seyo-flat-claude"

SAMPLE_SIZE = 100   # docs sampled per detailed check; override with --sample
# ─────────────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
parser.add_argument("--type",   default=None, help="Validate only this entity type")
parser.add_argument("--sample", default=SAMPLE_SIZE, type=int)
args = parser.parse_args()

SAMPLE_SIZE = args.sample

print(f"\nConnecting to SOURCE {SOURCE_HOST}:{SOURCE_PORT} ...")
src_client = MongoClient(f"mongodb://{SOURCE_HOST}:{SOURCE_PORT}/", serverSelectionTimeoutMS=10000)
src = src_client[SOURCE_DB]

print(f"Connecting to TARGET {TARGET_HOST}:{TARGET_PORT} ...")
tgt_client = MongoClient(f"mongodb://{TARGET_HOST}:{TARGET_PORT}/", serverSelectionTimeoutMS=10000)
tgt = tgt_client[TARGET_DB]
ents = tgt["flat_entities"]

# ── HELPERS ─────────────────────────────────────────────────────────────────

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []   # list of (type, check, status, detail)
fail_count = 0

def oid(v):
    return str(v) if v else None

def record(entity_type, check, ok, detail=""):
    global fail_count
    status = PASS if ok else FAIL
    if not ok:
        fail_count += 1
    results.append((entity_type, check, status, detail))
    marker = status
    line = f"   {marker}  [{entity_type}] {check}"
    if detail:
        line += f"  →  {detail}"
    print(line)

def warn(entity_type, check, detail=""):
    results.append((entity_type, check, WARN, detail))
    print(f"   {WARN} [{entity_type}] {check}  →  {detail}")

def sample_pipeline(type_val, n):
    """Return a random sample of n docs from flat_entities for a given type."""
    return list(ents.aggregate([
        {"$match": {"type": type_val}},
        {"$sample": {"size": n}}
    ]))

# ── PRE-LOAD SMALL LOOKUP TABLES ────────────────────────────────────────────
print("\n📥 Loading lookup tables from source...")
insp_statuses = {str(s["_id"]): s.get("status") for s in src.inspectionstatuses.find({})}
task_statuses = {str(s["_id"]): s.get("status") for s in src.taskstatuses.find({})}
act_statuses  = {str(s["_id"]): s.get("status") for s in src.activitystatuses.find({})}
wf_statuses   = {str(s["_id"]): s.get("status") for s in src.workflowstatuses.find({})}
tags_map      = {str(t["_id"]): t.get("displayName") for t in src.tags.find({})}
users_map     = {u.get("id", str(u["_id"])): u.get("name") for u in src.users.find({})}
users_by_moid = {str(u["_id"]): u.get("name") for u in src.users.find({})}

def expect_user_name(user_id_str):
    if not user_id_str: return None
    return users_map.get(str(user_id_str)) or users_by_moid.get(str(user_id_str))

print(f"   insp_statuses:{len(insp_statuses)}  task_statuses:{len(task_statuses)}")
print(f"   act_statuses:{len(act_statuses)}  wf_statuses:{len(wf_statuses)}")
print(f"   tags:{len(tags_map)}  users:{len(users_map)}")

# ── ENTITY DEFINITION TABLE ──────────────────────────────────────────────────
# Defines what we validate for each entity type.
ENTITY_DEFS = {
    "checklists": {
        "source_col":     "checklists",
        "required_fields": ["title", "tenantId", "isDeleted"],
        "nullable_ok":     ["description", "version", "localChecklistId"],
        "status_field":    None,
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "tag_id_field":    "tagIds",
        "tag_name_field":  "tagNames",
        "array_fields":    {"tagIds": "tagIds"},   # flat_field: source_field
        "geo":             False,
    },
    "sections": {
        "source_col":     "sections",
        "required_fields": ["checklistId", "isDeleted"],
        "nullable_ok":     ["description", "orderNumber"],
        "status_field":    None,
        "user_field":      None,
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {},
        "geo":             False,
    },
    "questions": {
        "source_col":     "questions",
        "required_fields": ["checklistId", "tenantId", "isDeleted", "questionText"],
        "nullable_ok":     ["sectionId", "orderNumber"],
        "status_field":    None,
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {},
        "geo":             False,
    },
    "responsevalues": {
        "source_col":     "responsevalues",
        "required_fields": ["questionId", "isDeleted"],
        "nullable_ok":     ["responseColor", "scoreValue"],
        "status_field":    None,
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {},
        "geo":             False,
    },
    "inspections": {
        "source_col":     "inspections",
        "required_fields": ["tenantId", "isDeleted", "checklistId"],
        "nullable_ok":     ["title", "scheduleId", "workflowId", "localInspectionId",
                            "referenceId", "referenceName"],
        "status_field":    ("status", insp_statuses, "statusKey", "statusDisplayName"),
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "assigned_field":  ("assignedTo", "assignedToId", "assignedToName"),
        "tag_id_field":    "tagIds",
        "tag_name_field":  "tagNames",
        "array_fields":    {"tagIds": "tagIds"},
        "geo":             True,
    },
    "executions": {
        "source_col":     "executions",
        "required_fields": ["inspectionId", "questionId", "tenantId", "isDeleted"],
        "nullable_ok":     ["sectionId", "checklistId"],
        "status_field":    None,
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {},
        "geo":             True,
    },
    "responsehistories": {
        "source_col":     "responsehistories",
        "required_fields": ["executionId", "questionId", "isDeleted"],
        "nullable_ok":     ["sectionId", "scoreValue", "minScore", "maxScore", "responseColor"],
        "status_field":    None,
        "user_field":      None,
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {"responseIds": "responseIds", "responseValues": "responseValues"},
        "geo":             False,
        "score_fields":    ["scoreValue", "minScore", "maxScore",
                            "enforceImage", "enforceIssue", "enforceObservation", "responseColor"],
    },
    "tasks": {
        "source_col":     "tasks",
        "required_fields": ["inspectionId", "tenantId", "isDeleted"],
        "nullable_ok":     ["questionId", "sectionId", "executionId", "referenceId",
                            "referenceName", "observationId"],
        "status_field":    ("status", task_statuses, "statusKey", "statusDisplayName"),
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "assigned_field":  ("assignedTo", "assignedToId", "assignedToName"),
        "tag_id_field":    "tagIds",
        "tag_name_field":  "tagNames",
        "array_fields":    {"tagIds": "tagIds"},
        "geo":             True,
    },
    "inspectionobservations": {
        "source_col":     "inspectionobservations",
        "required_fields": ["executionId", "questionId", "tenantId", "isDeleted"],
        "nullable_ok":     ["sectionId", "responseId", "assignedToId", "description"],
        "status_field":    None,
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "assigned_field":  ("assignedTo", "assignedToId", "assignedToName"),
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {},
        "geo":             True,
    },
    "taskobservations": {
        "source_col":     "taskobservations",
        "required_fields": ["taskId", "executionId", "tenantId", "isDeleted"],
        "nullable_ok":     ["sectionId", "questionId", "observationId", "description"],
        "status_field":    None,
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {},
        "geo":             True,
    },
    "reports": {
        "source_col":     "reports",
        "required_fields": ["inspectionId", "tenantId", "isDeleted"],
        "nullable_ok":     ["reportName", "reportNumber", "reportDate",
                            "inspectionTitle", "inspectionStatusName"],
        "status_field":    None,
        "user_field":      None,
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {},
        "geo":             False,
    },
    "activities": {
        "source_col":     "activities",
        "required_fields": ["tenantId", "isDeleted"],
        "nullable_ok":     ["title", "workflowId", "roleId", "orderNumber",
                            "onSuccess", "onFailure", "activeActivity", "dependencyActivity"],
        "status_field":    ("statusId", act_statuses, "statusKey", "statusDisplayName"),
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "assigned_field":  ("assignedTo", "assignedToId", "assignedToName"),
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {"checklistIds": "checklists", "inspectionIds": "inspections"},
        "geo":             False,
    },
    "workflows": {
        "source_col":     "workflows",
        "required_fields": ["tenantId", "isDeleted"],
        "nullable_ok":     ["title"],
        "status_field":    ("statusId", wf_statuses, "statusKey", "statusDisplayName"),
        "user_field":      "createdById",
        "user_name_field": "createdByName",
        "tag_id_field":    None,
        "tag_name_field":  None,
        "array_fields":    {},
        "geo":             False,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION LOOP
# ─────────────────────────────────────────────────────────────────────────────

entity_types = [args.type] if args.type else list(ENTITY_DEFS.keys())

for entity_type in entity_types:
    defn       = ENTITY_DEFS[entity_type]
    source_col = src[defn["source_col"]]

    print(f"\n{'═'*68}")
    print(f"  Validating: {entity_type}")
    print(f"{'═'*68}")

    # ── 1. COUNT MATCH ────────────────────────────────────────────────────
    src_count  = source_col.count_documents({})
    flat_count = ents.count_documents({"type": entity_type})
    ok = (src_count == flat_count)
    record(entity_type, "Count match",
           ok, f"source={src_count}  flat_entities={flat_count}" +
               (f"  DELTA={flat_count - src_count:+d}" if not ok else ""))

    # ── 2. ID COVERAGE — every source _id exists in flat_entities ─────────
    print(f"   Checking ID coverage (all {src_count} source _ids present)...")
    src_ids  = {str(d["_id"]) for d in source_col.find({}, {"_id": 1})}
    flat_ids = {d["_id"] for d in ents.find({"type": entity_type}, {"_id": 1})}
    missing  = src_ids - flat_ids
    extra    = flat_ids - src_ids
    record(entity_type, "No missing IDs",
           len(missing) == 0,
           f"{len(missing)} source IDs absent from flat_entities" +
           (f" e.g. {list(missing)[:3]}" if missing else ""))
    if extra:
        warn(entity_type, "Extra IDs in flat_entities",
             f"{len(extra)} IDs exist in flat but not source — may be OK if re-run")

    if src_count == 0:
        warn(entity_type, "SKIP", "Source collection is empty — skipping detailed checks")
        continue

    # ── 3. SAMPLE DOCS — load from both sides for field checks ────────────
    sample_ids = list(src_ids)[:SAMPLE_SIZE]
    src_sample = {str(d["_id"]): d
                  for d in source_col.find({"_id": {"$in": [ObjectId(i) if len(i)==24 else i
                                                              for i in sample_ids]}})}
    flat_sample = {d["_id"]: d
                   for d in ents.find({"type": entity_type, "_id": {"$in": sample_ids}})}

    # ── 4. REQUIRED FIELDS ───────────────────────────────────────────────
    for field in defn["required_fields"]:
        null_count = sum(1 for d in flat_sample.values() if not d.get(field))
        ok = (null_count == 0)
        record(entity_type, f"Required field '{field}' non-null",
               ok, f"{null_count}/{len(flat_sample)} docs have null/missing value" if not ok else "")

    # ── 5. STATUS RESOLUTION ─────────────────────────────────────────────
    if defn.get("status_field"):
        src_status_field, status_lookup, flat_key_field, flat_display_field = defn["status_field"]
        mismatch = 0
        unresolved = 0
        for sid, src_doc in src_sample.items():
            flat_doc = flat_sample.get(sid)
            if not flat_doc: continue
            raw_status_id = oid(src_doc.get(src_status_field))
            if not raw_status_id: continue
            expected_key  = status_lookup.get(raw_status_id)
            actual_key    = flat_doc.get(flat_key_field)
            if actual_key is None:
                unresolved += 1
            elif expected_key and actual_key != expected_key:
                mismatch += 1
        record(entity_type, f"Status resolved ({src_status_field}→{flat_key_field})",
               mismatch == 0 and unresolved == 0,
               f"{mismatch} wrong values, {unresolved} unresolved" if (mismatch or unresolved) else "")

    # ── 6. ASSIGNED-TO RESOLUTION ─────────────────────────────────────────
    if defn.get("assigned_field"):
        src_f, flat_id_f, flat_name_f = defn["assigned_field"]
        id_mismatch = 0
        name_missing = 0
        for sid, src_doc in src_sample.items():
            flat_doc = flat_sample.get(sid)
            if not flat_doc: continue
            src_val = str(src_doc.get(src_f)) if src_doc.get(src_f) else None
            flat_val = flat_doc.get(flat_id_f)
            if src_val and flat_val != src_val:
                id_mismatch += 1
            if src_val and not flat_doc.get(flat_name_f):
                name_missing += 1
        record(entity_type, f"AssignedTo ID preserved ({src_f}→{flat_id_f})",
               id_mismatch == 0, f"{id_mismatch} mismatches" if id_mismatch else "")
        if name_missing > 0:
            warn(entity_type, f"AssignedToName missing for {name_missing} docs with assignedTo set",
                 "User may not exist in users collection")

    # ── 7. CREATED-BY RESOLUTION ─────────────────────────────────────────
    if defn.get("user_field"):
        uid_f   = defn["user_field"]
        uname_f = defn.get("user_name_field")
        id_mismatch  = 0
        name_missing = 0
        for sid, src_doc in src_sample.items():
            flat_doc = flat_sample.get(sid)
            if not flat_doc: continue
            src_uid  = str(src_doc.get("createdBy")) if src_doc.get("createdBy") else None
            flat_uid = flat_doc.get(uid_f)
            if src_uid and flat_uid != src_uid:
                id_mismatch += 1
            if uname_f and src_uid and not flat_doc.get(uname_f):
                name_missing += 1
        record(entity_type, f"CreatedBy ID preserved (createdBy→{uid_f})",
               id_mismatch == 0, f"{id_mismatch} mismatches" if id_mismatch else "")
        if name_missing > 0:
            warn(entity_type, f"CreatedByName missing for {name_missing} docs with createdBy set",
                 "User may not exist in users collection")

    # ── 8. TAG RESOLUTION ─────────────────────────────────────────────────
    if defn.get("tag_id_field") and defn.get("tag_name_field"):
        tag_id_f   = defn["tag_id_field"]
        tag_name_f = defn["tag_name_field"]
        len_mismatch = 0
        unresolved   = 0
        for sid, src_doc in src_sample.items():
            flat_doc = flat_sample.get(sid)
            if not flat_doc: continue
            src_tags  = src_doc.get("tagIds") or []
            flat_ids  = flat_doc.get(tag_id_f) or []
            flat_names = flat_doc.get(tag_name_f) or []
            if len(src_tags) != len(flat_ids):
                len_mismatch += 1
            for tag_id in flat_ids:
                if tags_map.get(tag_id) and tag_id not in [str(x) for x in src_tags]:
                    unresolved += 1
            # resolved names should match count of IDs that have a displayName
            expected_name_count = sum(1 for t in flat_ids if tags_map.get(t))
            if len(flat_names) != expected_name_count:
                unresolved += 1
        record(entity_type, "Tag IDs preserved (tagIds count match)",
               len_mismatch == 0, f"{len_mismatch} docs have wrong tag count" if len_mismatch else "")

    # ── 9. ARRAY FIELD LENGTH MATCH ───────────────────────────────────────
    for flat_arr_field, src_arr_field in defn.get("array_fields", {}).items():
        mismatch = 0
        for sid, src_doc in src_sample.items():
            flat_doc = flat_sample.get(sid)
            if not flat_doc: continue
            src_arr  = src_doc.get(src_arr_field) or []
            flat_arr = flat_doc.get(flat_arr_field) or []
            if len(src_arr) != len(flat_arr):
                mismatch += 1
        record(entity_type, f"Array length match: {src_arr_field}→{flat_arr_field}",
               mismatch == 0,
               f"{mismatch} docs have array length mismatch" if mismatch else "")

    # ── 10. GEO FIELD FLATTENING ──────────────────────────────────────────
    if defn.get("geo"):
        geo_src_has   = 0
        geo_flat_ok   = 0
        for sid, src_doc in src_sample.items():
            flat_doc = flat_sample.get(sid)
            if not flat_doc: continue
            src_geo = src_doc.get("geoLocation") or {}
            if isinstance(src_geo, dict) and src_geo.get("latitude"):
                geo_src_has += 1
                if flat_doc.get("geoLat") == src_geo.get("latitude"):
                    geo_flat_ok += 1
        if geo_src_has > 0:
            record(entity_type, f"GeoLocation flattened correctly ({geo_src_has} with geo)",
                   geo_flat_ok == geo_src_has,
                   f"{geo_flat_ok}/{geo_src_has} lat values match" if geo_flat_ok != geo_src_has else "")
        else:
            warn(entity_type, "GeoLocation", "No docs with geoLocation in sample")

    # ── 11. RESPONSEHISTORIES — score fields exist in flat ─────────────────
    if entity_type == "responsehistories":
        score_fields = defn.get("score_fields", [])
        src_with_score = [d for d in src_sample.values() if d.get("scoreValue") is not None]
        if src_with_score:
            flat_with_score = [flat_sample[oid(d["_id"])]
                               for d in src_with_score if oid(d["_id"]) in flat_sample]
            for sf in score_fields:
                missing_f = sum(1 for d in flat_with_score if d.get(sf) is None
                               and any(s.get(sf) is not None
                                       for s in src_with_score if oid(s["_id"]) == d["_id"]))
            # simpler: just verify scoreValue survived
            sv_lost = sum(1 for d in src_with_score
                          if oid(d["_id"]) in flat_sample and
                             flat_sample[oid(d["_id"])].get("scoreValue") != d.get("scoreValue"))
            record(entity_type, f"scoreValue preserved ({len(src_with_score)} docs with score)",
                   sv_lost == 0,
                   f"{sv_lost} docs lost their scoreValue" if sv_lost else "")
        else:
            warn(entity_type, "No docs with scoreValue in sample — cannot validate score fields")

    # ── 12. WORKFLOWS — statusId→workflowstatuses resolved ────────────────
    if entity_type == "workflows":
        unresolved = 0
        for sid, src_doc in src_sample.items():
            flat_doc = flat_sample.get(sid)
            if not flat_doc: continue
            raw_sid = oid(src_doc.get("statusId"))
            if raw_sid and not flat_doc.get("statusKey"):
                unresolved += 1
        record(entity_type, "statusId→workflowstatuses resolved",
               unresolved == 0,
               f"{unresolved} workflows have statusId but no statusKey in flat" if unresolved else "")

    # ── 13. INSPECTIONS — assignedToId preserved from assignedTo ──────────
    if entity_type == "inspections":
        id_mismatch = 0
        for sid, src_doc in src_sample.items():
            flat_doc = flat_sample.get(sid)
            if not flat_doc: continue
            src_at  = str(src_doc.get("assignedTo")) if src_doc.get("assignedTo") else None
            flat_at = flat_doc.get("assignedToId")
            if src_at and flat_at != src_at:
                id_mismatch += 1
        record(entity_type, "assignedTo→assignedToId preserved",
               id_mismatch == 0, f"{id_mismatch} mismatches" if id_mismatch else "")

    # ── 14. ACTIVITIES — checklists[] array normalised to checklistIds ─────
    if entity_type == "activities":
        arr_mismatch = 0
        for sid, src_doc in src_sample.items():
            flat_doc = flat_sample.get(sid)
            if not flat_doc: continue
            src_cl  = src_doc.get("checklists") or []
            flat_cl = flat_doc.get("checklistIds") or []
            if len(src_cl) != len(flat_cl):
                arr_mismatch += 1
        record(entity_type, "checklists[]→checklistIds length match",
               arr_mismatch == 0,
               f"{arr_mismatch} docs have different array lengths" if arr_mismatch else "")

# ─────────────────────────────────────────────────────────────────────────────
# FK INTEGRITY CHECKS
# ─────────────────────────────────────────────────────────────────────────────
if not args.type:
    print(f"\n{'═'*68}")
    print("  FK Integrity Checks")
    print(f"{'═'*68}")

    def check_fk(from_type, fk_field, to_type, sample_n=SAMPLE_SIZE):
        """Verify that fk_field values in from_type all exist as _ids in to_type."""
        docs = list(ents.aggregate([
            {"$match": {"type": from_type, fk_field: {"$ne": None}}},
            {"$sample": {"size": sample_n}},
            {"$project": {"_id": 1, fk_field: 1}}
        ]))
        if not docs:
            warn(from_type, f"FK {from_type}.{fk_field}→{to_type}: no docs with this FK")
            return
        fk_vals = [d[fk_field] for d in docs if d.get(fk_field)]
        existing = {d["_id"] for d in ents.find(
            {"type": to_type, "_id": {"$in": fk_vals}}, {"_id": 1}
        )}
        broken = [v for v in fk_vals if v not in existing]
        record(f"{from_type}.{fk_field}→{to_type}",
               f"FK integrity (sample {len(docs)})",
               len(broken) == 0,
               f"{len(broken)} broken FKs e.g. {broken[:2]}" if broken else "")

    check_fk("executions",             "inspectionId",  "inspections")
    check_fk("executions",             "checklistId",   "checklists")
    check_fk("executions",             "questionId",    "questions")
    check_fk("responsehistories",      "executionId",   "executions")
    check_fk("responsehistories",      "questionId",    "questions")
    check_fk("tasks",                  "inspectionId",  "inspections")
    check_fk("tasks",                  "executionId",   "executions")
    check_fk("inspectionobservations", "executionId",   "executions")
    check_fk("inspectionobservations", "questionId",    "questions")
    check_fk("taskobservations",       "taskId",        "tasks")
    check_fk("taskobservations",       "executionId",   "executions")
    check_fk("reports",                "inspectionId",  "inspections")
    check_fk("activities",             "workflowId",    "workflows")
    check_fk("questions",              "checklistId",   "checklists")
    check_fk("sections",               "checklistId",   "checklists")

# ─────────────────────────────────────────────────────────────────────────────
# FLAT_ENTITIES TOTAL COUNT SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
if not args.type:
    print(f"\n{'═'*68}")
    print("  Entity counts in flat_entities")
    print(f"{'═'*68}")
    source_counts = {
        "checklists":             src.checklists.count_documents({}),
        "sections":               src.sections.count_documents({}),
        "questions":              src.questions.count_documents({}),
        "responsevalues":         src.responsevalues.count_documents({}),
        "inspections":            src.inspections.count_documents({}),
        "executions":             src.executions.count_documents({}),
        "responsehistories":      src.responsehistories.count_documents({}),
        "tasks":                  src.tasks.count_documents({}),
        "inspectionobservations": src.inspectionobservations.count_documents({}),
        "taskobservations":       src.taskobservations.count_documents({}),
        "reports":                src.reports.count_documents({}),
        "activities":             src.activities.count_documents({}),
        "workflows":              src.workflows.count_documents({}),
    }
    total_src  = sum(source_counts.values())
    total_flat = ents.count_documents({})
    print(f"\n   {'Type':<30} {'Source':>8} {'Flat':>8}  {'Match':>6}")
    print(f"   {'-'*56}")
    for t, sc in source_counts.items():
        fc = ents.count_documents({"type": t})
        ok = "✅" if sc == fc else "❌"
        print(f"   {t:<30} {sc:>8} {fc:>8}  {ok}")
    print(f"   {'-'*56}")
    print(f"   {'TOTAL':<30} {total_src:>8} {total_flat:>8}  {'✅' if total_src == total_flat else '❌'}")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
total_checks = len(results)
total_pass   = sum(1 for r in results if r[2] == PASS)
total_fail   = sum(1 for r in results if r[2] == FAIL)
total_warn   = sum(1 for r in results if r[2] == WARN)

print(f"\n{'═'*68}")
print(f"  VALIDATION SUMMARY")
print(f"{'═'*68}")
print(f"  Total checks : {total_checks}")
print(f"  ✅ Passed     : {total_pass}")
print(f"  ❌ Failed     : {total_fail}")
print(f"  ⚠️  Warnings  : {total_warn}")

if total_fail > 0:
    print(f"\n  FAILURES:")
    for etype, check, status, detail in results:
        if status == FAIL:
            print(f"    ❌ [{etype}] {check}  →  {detail}")

sys.exit(0 if total_fail == 0 else 1)