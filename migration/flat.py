"""
FLAT SCHEMA BUILDER v3 — seyo-development  →  seyo-flat-claude
===============================================================
NATIVE TYPES EDITION — all fields stored with the SAME data type
as the source MongoDB document (ObjectId stays ObjectId, datetime
stays datetime, numbers stay numbers, booleans stay booleans).

CHANGES vs v3 (string-casting edition):
  _id             Stored as ObjectId  (was str)
  all *Id fields  Stored as ObjectId  (was str)
  tagIds          Stored as [ObjectId] (was [str])
  responseIds     Stored as [ObjectId] (was [str])
  checklistIds    Stored as [ObjectId] (was [str])
  inspectionIds   Stored as [ObjectId] (was [str])
  createdAt/updatedAt/deletedAt/reportDate  stored as datetime (was str)
  q_to_section    Maps ObjectId → ObjectId (was str → str)
  geo()           Returns float lat/lng as-is from source (was unchanged)
  resolve_obj_ids Returns [ObjectId] (was [str])
  All lookup dict keys remain str for Python dict speed; only the
  values WRITTEN to MongoDB are now native BSON types.
"""

from pymongo import MongoClient, UpdateOne
from bson import ObjectId
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────────────────────────────
SOURCE_HOST  = "192.168.0.172"
SOURCE_PORT  = 27017
SOURCE_DB    = "seyo-development"

TARGET_HOST  = "192.168.0.130"
TARGET_PORT  = 27017
TARGET_DB    = "seyo-flat-claude-v4"
BATCH_SIZE   = 5_000_000
# ───────────────────────────────────────────────────────────────────────────

source_client = MongoClient(f"mongodb://{SOURCE_HOST}:{SOURCE_PORT}/", serverSelectionTimeoutMS=10000)
target_client = MongoClient(f"mongodb://{TARGET_HOST}:{TARGET_PORT}/", serverSelectionTimeoutMS=10000)
source        = source_client[SOURCE_DB]
target        = target_client[TARGET_DB]


# ── HELPER: keep ObjectId as ObjectId, return None for falsy ─────────────
def to_oid(v):
    """
    Return v as an ObjectId if it isn't already, None for falsy values.
    If v is already an ObjectId, return it unchanged.
    If v is a 24-hex string, convert to ObjectId.
    Otherwise return None.
    """
    if not v:
        return None
    if isinstance(v, ObjectId):
        return v
    s = str(v)
    if len(s) == 24:
        try:
            return ObjectId(s)
        except Exception:
            pass
    return None  # non-OID strings (e.g. ABP GUIDs) should NOT be cast

def str_id(v):
    """String form of an ObjectId or any value — used ONLY for Python dict keys."""
    return str(v) if v else None

def geo(doc):
    """Extract geoLocation sub-document as flat fields with native float values."""
    g = doc.get("geoLocation") or {}
    if not isinstance(g, dict):
        return {}
    return {
        "geoLat":     g.get("latitude"),   # float or None — native
        "geoLng":     g.get("longitude"),  # float or None — native
        "geoAddress": g.get("address"),    # str or None
    }

def resolve_obj_ids(raw_list):
    """
    Normalise a list that may contain ObjectIds, dicts with _id, or plain strings.
    Returns a list of ObjectIds (not strings).
    """
    result = []
    for x in (raw_list or []):
        if not x:
            continue
        if isinstance(x, ObjectId):
            result.append(x)
        elif isinstance(x, dict):
            oid = to_oid(x.get("_id") or x.get("id"))
            if oid:
                result.append(oid)
        else:
            oid = to_oid(x)
            if oid:
                result.append(oid)
    return result


# ── LOOKUP TABLES (load fully into memory) ────────────────────────────────
# Keys are str(_id) for fast Python dict access.
# Values are plain Python dicts with display strings — not stored in Mongo.
print("📥 Loading lookup tables...")

inspection_statuses = {
    str(s["_id"]): {"displayName": s.get("displayName"), "status": s.get("status")}
    for s in source.inspectionstatuses.find({})
}
task_statuses = {
    str(s["_id"]): {"displayName": s.get("displayName"), "status": s.get("status")}
    for s in source.taskstatuses.find({})
}
activity_statuses = {
    str(s["_id"]): {"displayName": s.get("displayName"), "status": s.get("status")}
    for s in source.activitystatuses.find({})
}
workflow_statuses = {
    str(s["_id"]): {"displayName": s.get("displayName"), "status": s.get("status")}
    for s in source.workflowstatuses.find({})
}
response_types = {
    str(s["_id"]): {"displayName": s.get("displayName"), "type": s.get("type")}
    for s in source.responsetypes.find({})
}
tags_map = {
    str(t["_id"]): t.get("displayName")
    for t in source.tags.find({})
}

# Users — indexed by both ABP string id and MongoDB _id string
users_map = {
    u.get("id", str(u["_id"])): {
        "name":      u.get("name"),
        "email":     u.get("email"),
        "userName":  u.get("userName"),
        "mongoId":   str(u["_id"]),
    }
    for u in source.users.find({})
}
users_by_mongoid = {
    str(u["_id"]): {
        "name":     u.get("name"),
        "email":    u.get("email"),
        "userName": u.get("userName"),
        "id":       u.get("id"),
    }
    for u in source.users.find({})
}

def resolve_user(user_id_val):
    """
    Look up display info for a user.
    user_id_val may be an ObjectId, a 24-hex string OID, or an ABP GUID string.
    Returns a dict with name/email/userName (or empty dict).
    """
    if not user_id_val:
        return {}
    s = str(user_id_val)
    return users_map.get(s) or users_by_mongoid.get(s) or {}

print(f"   ✅ inspectionStatuses:{len(inspection_statuses)}  taskStatuses:{len(task_statuses)}")
print(f"   ✅ activityStatuses:{len(activity_statuses)}  workflowStatuses:{len(workflow_statuses)}")
print(f"   ✅ responsetypes:{len(response_types)}  tags:{len(tags_map)}  users:{len(users_map)}")


# ══════════════════════════════════════════════════════════════════════════
# STEP 1 — Build question→section map from checklistmapordernumbers
#
# Map: ObjectId(questionId) → ObjectId(sectionId)
# Also captures order numbers for questions and sections.
# ══════════════════════════════════════════════════════════════════════════
print("\n📐 Building question→section mapping from checklistmapordernumbers...")

q_to_section  = {}   # ObjectId → ObjectId  (question → section)
q_order_map   = {}   # str(questionId) → orderNumber (int/None)
sec_order_map = {}   # str(sectionId)  → orderNumber (int/None)

for doc in source.checklistmapordernumbers.find({"isDeleted": {"$ne": True}}):
    for detail in doc.get("orderDetails", []):
        sec_oid = to_oid(detail.get("sectionId"))
        q_oid   = to_oid(detail.get("questionId"))
        order   = detail.get("orderNumber")

        if sec_oid and q_oid:                         # Format C — flat legacy
            q_to_section[q_oid]           = sec_oid
            q_order_map[str(q_oid)]       = order
            sec_key = str(sec_oid)
            sec_order_map.setdefault(sec_key, order)

        elif sec_oid and not q_oid:                   # Format B — section + nested questions
            sec_key = str(sec_oid)
            sec_order_map.setdefault(sec_key, order)
            for nested in detail.get("orderDetails", []):
                nq_oid   = to_oid(nested.get("questionId"))
                nq_order = nested.get("orderNumber")
                if nq_oid:
                    q_to_section[nq_oid]     = sec_oid
                    q_order_map[str(nq_oid)] = nq_order

        elif q_oid and not sec_oid:                   # Format A — standalone question
            q_order_map[str(q_oid)] = order

print(f"   ✅ Mapped {len(q_to_section)} questions to sections via order map")
print(f"   ✅ Mapped {len(q_order_map)} question order numbers")


# ── UPSERT HELPER ─────────────────────────────────────────────────────────
def upsert_batch(collection, docs, key="_id"):
    if not docs:
        return
    ops = [UpdateOne({key: d[key]}, {"$set": d}, upsert=True) for d in docs]
    collection.bulk_write(ops, ordered=False)


# ══════════════════════════════════════════════════════════════════════════
# TABLE 1 — flat_checklists
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_checklists...")
batch = []
for c in source.checklists.find({}):
    tag_names = [tags_map.get(str(t)) for t in c.get("tagIds", []) if t]
    creator   = resolve_user(c.get("createdBy"))
    batch.append({
        "_id":              c["_id"],                          # ObjectId
        "type":             "checklists",
        "title":            c.get("title"),
        "description":      c.get("description"),
        "version":          c.get("version"),
        "localChecklistId": c.get("localChecklistId"),
        "isTemplate":       c.get("isTemplate", False),
        "isLibrary":        c.get("isLibrary", False),
        "isLatest":         c.get("isLatest"),
        "tenantId":         c.get("tenantId"),
        "createdBy":        c.get("createdBy"),                # raw (ABP str or OID)
        "createdByName":    creator.get("name"),
        "createdByEmail":   creator.get("email"),
        "deletedBy":        c.get("deletedBy"),                # raw
        "tagIds":           [t for t in c.get("tagIds", []) if t],   # [ObjectId]
        "tagNames":         [t for t in tag_names if t],
        "isDeleted":        c.get("isDeleted", False),
        "deletedAt":        c.get("deletedAt"),                # datetime or None
        "createdAt":        c.get("createdAt"),                # datetime or None
        "updatedAt":        c.get("updatedAt"),                # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_checklists, batch); batch = []
upsert_batch(target.flat_checklists, batch)
print(f"   ✅ flat_checklists: {target.flat_checklists.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 2 — flat_sections
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_sections...")
batch = []
for s in source.sections.find({}):
    sid = s["_id"]
    batch.append({
        "_id":         sid,                                     # ObjectId
        "type":        "sections",
        "checklistId": to_oid(s.get("checklistId")),           # ObjectId
        "title":       s.get("title"),
        "description": s.get("description"),
        "isMandatory": s.get("isMandatory", False),
        "orderNumber": sec_order_map.get(str(sid)) or s.get("orderNumber"),
        "version":     s.get("version"),
        "isDeleted":   s.get("isDeleted", False),
        "deletedAt":   s.get("deletedAt"),                     # datetime or None
        "createdAt":   s.get("createdAt"),                     # datetime or None
        "updatedAt":   s.get("updatedAt"),                     # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_sections, batch); batch = []
upsert_batch(target.flat_sections, batch)
print(f"   ✅ flat_sections: {target.flat_sections.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 3 — flat_questions
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_questions...")
batch = []
for q in source.questions.find({}):
    qid     = q["_id"]                                         # ObjectId
    rt      = response_types.get(str_id(q.get("responseType")), {})
    creator = resolve_user(q.get("createdBy"))
    # Use order-map sectionId first, fall back to native sectionId on question doc
    resolved_section = q_to_section.get(qid) or to_oid(q.get("sectionId"))
    batch.append({
        "_id":              qid,                               # ObjectId
        "type":             "questions",
        "checklistId":      to_oid(q.get("checklistId")),     # ObjectId
        "sectionId":        resolved_section,                  # ObjectId
        "questionText":     q.get("questionText"),
        "responseTypeId":   to_oid(q.get("responseType")),    # ObjectId
        "responseTypeName": rt.get("displayName"),
        "responseTypeKey":  rt.get("type"),
        "orderNumber":      q_order_map.get(str(qid)) or q.get("orderNumber"),
        "allowMultiple":    q.get("allowMultiple", False),
        "isMandatory":      q.get("isMandatory", False),
        "tenantId":         q.get("tenantId"),
        "createdBy":        q.get("createdBy"),                # raw
        "createdByName":    creator.get("name"),
        "version":          q.get("version"),
        "isDeleted":        q.get("isDeleted", False),
        "deletedAt":        q.get("deletedAt"),                # datetime or None
        "createdAt":        q.get("createdAt"),                # datetime or None
        "updatedAt":        q.get("updatedAt"),                # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_questions, batch); batch = []
upsert_batch(target.flat_questions, batch)
print(f"   ✅ flat_questions: {target.flat_questions.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 4 — flat_response_options
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_response_options...")
batch = []
for r in source.responsevalues.find({}):
    creator = resolve_user(r.get("createdBy"))
    batch.append({
        "_id":                r["_id"],                        # ObjectId
        "type":               "responsevalues",
        "questionId":         to_oid(r.get("questionId")),    # ObjectId
        "responseValue":      r.get("responseValue"),
        "enableScore":        r.get("enableScore", False),
        "scoreValue":         r.get("scoreValue"),             # numeric — native
        "enforceIssue":       r.get("enforceIssue", False),
        "enforceObservation": r.get("enforceObservation", False),
        "enforceImage":       r.get("enforceImage", False),
        "responseColor":      r.get("responseColor"),
        "version":            r.get("version"),
        "tenantId":           r.get("tenantId"),
        "createdBy":          r.get("createdBy"),              # raw
        "createdByName":      creator.get("name"),
        "isDeleted":          r.get("isDeleted", False),
        "deletedAt":          r.get("deletedAt"),              # datetime or None
        "createdAt":          r.get("createdAt"),              # datetime or None
        "updatedAt":          r.get("updatedAt"),              # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_response_options, batch); batch = []
upsert_batch(target.flat_response_options, batch)
print(f"   ✅ flat_response_options: {target.flat_response_options.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 5 — flat_inspections
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_inspections...")
checklist_titles = {
    str(c["_id"]): c.get("title")
    for c in source.checklists.find({}, {"title": 1})
}
batch = []
for i in source.inspections.find({}):
    status_raw = i.get("status")                               # ObjectId in source
    status_obj = inspection_statuses.get(str_id(status_raw), {})
    creator    = resolve_user(i.get("createdBy"))
    assigned   = resolve_user(i.get("assignedTo"))
    cl_id      = to_oid(i.get("checklistId"))
    tag_names  = [tags_map.get(str(t)) for t in i.get("tagIds", []) if t]
    g          = geo(i)
    batch.append({
        "_id":               i["_id"],                         # ObjectId
        "type":              "inspections",
        "title":             i.get("title"),
        "checklistId":       cl_id,                            # ObjectId
        "checklistTitle":    checklist_titles.get(str_id(cl_id)),
        "scheduleId":        to_oid(i.get("scheduleId")),      # ObjectId
        "workflowId":        to_oid(i.get("workflowId")),      # ObjectId
        "localInspectionId": i.get("localInspectionId"),
        "referenceId":       i.get("referenceId"),
        "referenceName":     i.get("referenceName"),
        "executionTimings":  i.get("executionTimings"),        # sub-doc — native
        "statusId":          status_raw,                       # ObjectId (raw from source)
        "statusKey":         status_obj.get("status"),
        "tagIds":            [t for t in i.get("tagIds", []) if t],   # [ObjectId]
        "tagNames":          [t for t in tag_names if t],
        "assignedTo":        i.get("assignedTo"),              # raw (ABP str or OID)
        "assignedToName":    assigned.get("name"),
        "assignedToEmail":   assigned.get("email"),
        "tenantId":          i.get("tenantId"),
        "createdBy":         i.get("createdBy"),               # raw
        "createdByName":     creator.get("name"),
        "createdByEmail":    creator.get("email"),
        **g,
        "isDeleted":         i.get("isDeleted", False),
        "deletedAt":         i.get("deletedAt"),               # datetime or None
        "createdAt":         i.get("createdAt"),               # datetime or None
        "updatedAt":         i.get("updatedAt"),               # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_inspections, batch); batch = []
upsert_batch(target.flat_inspections, batch)
print(f"   ✅ flat_inspections: {target.flat_inspections.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 6 — flat_executions
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_executions...")
batch = []
for e in source.executions.find({}):
    q_oid   = to_oid(e.get("questionId"))
    creator = resolve_user(e.get("createdBy"))
    g       = geo(e)
    batch.append({
        "_id":           e["_id"],                             # ObjectId
        "type":          "executions",
        "inspectionId":  to_oid(e.get("inspectionId")),        # ObjectId
        "checklistId":   to_oid(e.get("checklistId")),         # ObjectId
        "questionId":    q_oid,                                # ObjectId
        "sectionId":     q_to_section.get(q_oid) or to_oid(e.get("sectionId")),  # ObjectId
        "tenantId":      e.get("tenantId"),
        "createdBy":     e.get("createdBy"),                   # raw
        "createdByName": creator.get("name"),
        **g,
        "isDeleted":     e.get("isDeleted", False),
        "createdAt":     e.get("createdAt"),                   # datetime or None
        "updatedAt":     e.get("updatedAt"),                   # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_executions, batch); batch = []
upsert_batch(target.flat_executions, batch)
print(f"   ✅ flat_executions: {target.flat_executions.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 7 — flat_response_histories
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_response_histories...")
batch = []
for rh in source.responsehistories.find({}):
    q_oid = to_oid(rh.get("questionId"))
    batch.append({
        "_id":                rh["_id"],                       # ObjectId
        "type":               "responsehistories",
        "executionId":        to_oid(rh.get("executionId")),   # ObjectId
        "questionId":         q_oid,                           # ObjectId
        "sectionId":          q_to_section.get(q_oid) or to_oid(rh.get("sectionId")),  # ObjectId
        "responseIds":        [to_oid(r) for r in (rh.get("responseIds") or []) if r],  # [ObjectId]
        "responseValues":     rh.get("responseValues") or [],  # list — native
        "scoreValue":         rh.get("scoreValue"),            # numeric — native
        "minScore":           rh.get("minScore"),              # numeric — native
        "maxScore":           rh.get("maxScore"),              # numeric — native
        "enforceImage":       rh.get("enforceImage", False),
        "enforceIssue":       rh.get("enforceIssue", False),
        "enforceObservation": rh.get("enforceObservation", False),
        "responseColor":      rh.get("responseColor"),
        "isDeleted":          rh.get("isDeleted", False),
        "createdAt":          rh.get("createdAt"),             # datetime or None
        "updatedAt":          rh.get("updatedAt"),             # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_response_histories, batch); batch = []
upsert_batch(target.flat_response_histories, batch)
print(f"   ✅ flat_response_histories: {target.flat_response_histories.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 8 — flat_tasks
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_tasks...")
batch = []
for t in source.tasks.find({}):
    status_raw = t.get("status")                               # ObjectId in source
    status_obj = task_statuses.get(str_id(status_raw), {})
    assigned   = resolve_user(t.get("assignedTo"))
    creator    = resolve_user(t.get("createdBy"))
    q_oid      = to_oid(t.get("questionId"))
    tag_names  = [tags_map.get(str(tid)) for tid in t.get("tagIds", []) if tid]
    g          = geo(t)
    batch.append({
        "_id":                t["_id"],                        # ObjectId
        "type":               "tasks",
        "title":              t.get("title"),
        "description":        t.get("description"),
        "inspectionId":       to_oid(t.get("inspectionId")),   # ObjectId
        "executionId":        to_oid(t.get("executionId")),    # ObjectId
        "questionId":         q_oid,                           # ObjectId
        "sectionId":          q_to_section.get(q_oid) or to_oid(t.get("sectionId")),  # ObjectId
        "observationId":      to_oid(t.get("observationId")),  # ObjectId
        "statusId":           status_raw,                      # ObjectId (raw)
        "statusKey":          status_obj.get("status"),
        "tagIds":             [tid for tid in t.get("tagIds", []) if tid],  # [ObjectId]
        "tagNames":           [n for n in tag_names if n],
        "assignedTo":         t.get("assignedTo"),             # raw (ABP str or OID)
        "assignedToName":     assigned.get("name"),
        "assignedToEmail":    assigned.get("email"),
        "createdBy":          t.get("createdBy"),              # raw
        "createdByName":      creator.get("name"),
        "tenantId":           t.get("tenantId"),
        "referenceId":        t.get("referenceId"),
        "referenceName":      t.get("referenceName"),
        "inspectionCompleted": t.get("inspectionCompleted", False),
        **g,
        "isDeleted":          t.get("isDeleted", False),
        "deletedAt":          t.get("deletedAt"),              # datetime or None
        "createdAt":          t.get("createdAt"),              # datetime or None
        "updatedAt":          t.get("updatedAt"),              # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_tasks, batch); batch = []
upsert_batch(target.flat_tasks, batch)
print(f"   ✅ flat_tasks: {target.flat_tasks.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 9 — flat_task_observations
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_task_observations...")
batch = []
for o in source.taskobservations.find({}):
    q_oid   = to_oid(o.get("questionId"))
    creator = resolve_user(o.get("createdBy"))
    g       = geo(o)
    batch.append({
        "_id":             o["_id"],                           # ObjectId
        "type":            "taskobservations",
        "taskId":          to_oid(o.get("taskId")),            # ObjectId
        "executionId":     to_oid(o.get("executionId")),       # ObjectId
        "questionId":      q_oid,                              # ObjectId
        "sectionId":       q_to_section.get(q_oid) or to_oid(o.get("sectionId")),  # ObjectId
        "observationId":   to_oid(o.get("observationId")),     # ObjectId
        "description":     o.get("description"),
        "isIssue":         o.get("isIssue", False),
        "isResolved":      o.get("isResolved", False),
        "evidence":        o.get("evidence"),
        "hasAttachment":   o.get("hasAttachment", False),
        "attachmentCount": o.get("attachmentCount", 0),        # int — native
        "createdBy":       o.get("createdBy"),                 # raw
        "createdByName":   creator.get("name"),
        "tenantId":        o.get("tenantId"),
        **g,
        "isDeleted":       o.get("isDeleted", False),
        "deletedAt":       o.get("deletedAt"),                 # datetime or None
        "createdAt":       o.get("createdAt"),                 # datetime or None
        "updatedAt":       o.get("updatedAt"),                 # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_task_observations, batch); batch = []
upsert_batch(target.flat_task_observations, batch)
print(f"   ✅ flat_task_observations: {target.flat_task_observations.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 10 — flat_inspection_observations
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_inspection_observations...")
batch = []
for o in source.inspectionobservations.find({}):
    q_oid    = to_oid(o.get("questionId"))
    creator  = resolve_user(o.get("createdBy"))
    assigned = resolve_user(o.get("assignedTo"))
    g        = geo(o)
    batch.append({
        "_id":             o["_id"],                           # ObjectId
        "type":            "inspectionobservations",
        "executionId":     to_oid(o.get("executionId")),       # ObjectId
        "questionId":      q_oid,                              # ObjectId
        "sectionId":       q_to_section.get(q_oid) or to_oid(o.get("sectionId")),  # ObjectId
        "responseId":      to_oid(o.get("responseId")),        # ObjectId (singular)
        "assignedTo":      o.get("assignedTo"),                # raw (ABP str or OID)
        "assignedToName":  assigned.get("name"),
        "description":     o.get("description"),
        "isIssue":         o.get("isIssue", False),
        "evidence":        o.get("evidence"),
        "hasAttachment":   o.get("hasAttachment", False),
        "attachmentCount": o.get("attachmentCount", 0),        # int — native
        "createdBy":       o.get("createdBy"),                 # raw
        "createdByName":   creator.get("name"),
        "tenantId":        o.get("tenantId"),
        **g,
        "isDeleted":       o.get("isDeleted", False),
        "createdAt":       o.get("createdAt"),                 # datetime or None
        "updatedAt":       o.get("updatedAt"),                 # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_inspection_observations, batch); batch = []
upsert_batch(target.flat_inspection_observations, batch)
print(f"   ✅ flat_inspection_observations: {target.flat_inspection_observations.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 11 — flat_reports
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_reports...")
inspection_docs = {
    str(i["_id"]): {
        "title":       i.get("title"),
        "statusRaw":   i.get("status"),            # ObjectId
        "checklistId": to_oid(i.get("checklistId")),
    }
    for i in source.inspections.find({}, {"title": 1, "status": 1, "checklistId": 1})
}
batch = []
for r in source.reports.find({}):
    ins_id  = str_id(r.get("inspectionId"))
    ins_obj = inspection_docs.get(ins_id, {})
    s_obj   = inspection_statuses.get(str_id(ins_obj.get("statusRaw")), {})
    batch.append({
        "_id":                   r["_id"],                     # ObjectId
        "type":                  "reports",
        "reportName":            r.get("reportName"),
        "reportNumber":          r.get("reportNumber"),
        "reportDate":            r.get("reportDate"),          # datetime — native
        "inspectionId":          to_oid(r.get("inspectionId")),  # ObjectId
        "inspectionTitle":       ins_obj.get("title"),
        "inspectionChecklistId": ins_obj.get("checklistId"),   # ObjectId
        "inspectionStatusName":  s_obj.get("displayName"),
        "tenantId":              r.get("tenantId"),
        "isDeleted":             r.get("isDeleted", False),
        "inspectionUpdatedAt":   r.get("inspectionUpdatedAt"), # datetime — native
        "createdAt":             r.get("createdAt"),           # datetime — native
        "updatedAt":             r.get("updatedAt"),           # datetime — native
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_reports, batch); batch = []
upsert_batch(target.flat_reports, batch)
print(f"   ✅ flat_reports: {target.flat_reports.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 12 — flat_activities
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_activities...")
batch = []
for a in source.activities.find({}):
    status_raw = to_oid(a.get("statusId"))
    status_obj = activity_statuses.get(str_id(status_raw), {})
    assigned   = resolve_user(a.get("assignedTo"))
    creator    = resolve_user(a.get("createdBy"))
    checklist_ids  = resolve_obj_ids(a.get("checklists", []))    # [ObjectId]
    inspection_ids = resolve_obj_ids(a.get("inspections", []))   # [ObjectId]
    batch.append({
        "_id":                a["_id"],                        # ObjectId
        "type":               "activities",
        "title":              a.get("title"),
        "tenantId":           a.get("tenantId"),
        "statusId":           status_raw,                      # ObjectId
        "statusKey":          status_obj.get("status"),
        "assignedTo":         a.get("assignedTo"),             # raw (ABP str or OID)
        "assignedToName":     assigned.get("name"),
        "assignedToEmail":    assigned.get("email"),
        "workflowId":         to_oid(a.get("workflowId")),     # ObjectId
        "roleId":             to_oid(a.get("roleId")),         # ObjectId
        "orderNumber":        a.get("orderNumber"),            # numeric — native
        "checklistIds":       checklist_ids,                   # [ObjectId]
        "inspectionIds":      inspection_ids,                  # [ObjectId]
        "onSuccess":          a.get("onSuccess"),
        "onFailure":          a.get("onFailure"),
        "activeActivity":     a.get("activeActivity"),
        "dependencyActivity": a.get("dependencyActivity"),
        "createdBy":          a.get("createdBy"),              # raw
        "createdByName":      creator.get("name"),
        "createdByEmail":     creator.get("email"),
        "isDeleted":          a.get("isDeleted", False),
        "deletedAt":          a.get("deletedAt"),              # datetime or None
        "createdAt":          a.get("createdAt"),              # datetime or None
        "updatedAt":          a.get("updatedAt"),              # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_activities, batch); batch = []
upsert_batch(target.flat_activities, batch)
print(f"   ✅ flat_activities: {target.flat_activities.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# TABLE 13 — flat_workflows
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_workflows...")
batch = []
for w in source.workflows.find({}):
    status_raw = to_oid(w.get("statusId"))
    status_obj = workflow_statuses.get(str_id(status_raw), {})
    creator    = resolve_user(w.get("createdBy"))
    batch.append({
        "_id":           w["_id"],                             # ObjectId
        "type":          "workflows",
        "title":         w.get("title"),
        "tenantId":      w.get("tenantId"),
        "statusId":      status_raw,                           # ObjectId
        "statusKey":     status_obj.get("status"),
        "createdBy":     w.get("createdBy"),                   # raw
        "createdByName": creator.get("name"),
        "createdByEmail": creator.get("email"),
        "isDeleted":     w.get("isDeleted", False),
        "deletedAt":     w.get("deletedAt"),                   # datetime or None
        "createdAt":     w.get("createdAt"),                   # datetime or None
        "updatedAt":     w.get("updatedAt"),                   # datetime or None
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_workflows, batch); batch = []
upsert_batch(target.flat_workflows, batch)
print(f"   ✅ flat_workflows: {target.flat_workflows.count_documents({})} docs")


# ══════════════════════════════════════════════════════════════════════════
# FINAL — Consolidate all flat collections into flat_entities
# ══════════════════════════════════════════════════════════════════════════
FLAT_COLLECTIONS = [
    "flat_checklists", "flat_sections", "flat_questions",
    "flat_response_options", "flat_inspections", "flat_executions",
    "flat_response_histories", "flat_tasks",
    "flat_task_observations", "flat_inspection_observations",
    "flat_reports", "flat_activities", "flat_workflows",
]

CONSOLIDATED = "flat_entities"

print(f"\n🔀 Consolidating all flat collections → {CONSOLIDATED}...")
target[CONSOLIDATED].drop()

for col_name in FLAT_COLLECTIONS:
    docs = list(target[col_name].find({}))
    if docs:
        target[CONSOLIDATED].insert_many(docs, ordered=False)
        print(f"   ✅ {col_name:<35} → {len(docs):>6} docs merged")

print("\n" + "=" * 60)
print(f"🎉 FLAT SCHEMA BUILD COMPLETE → {TARGET_HOST}/{TARGET_DB}")
print("=" * 60)
print(f"   {'flat_entities (consolidated)':<35} {target[CONSOLIDATED].count_documents({}):>6} docs")

print("\n📋 Diagnostic checks (type-aware):")
print(f"   Questions with sectionId (OID)      : {target[CONSOLIDATED].count_documents({'type': 'questions', 'sectionId': {'$type': 'objectId'}})}")
print(f"   Questions without sectionId         : {target[CONSOLIDATED].count_documents({'type': 'questions', 'sectionId': None})}")
print(f"   Inspections with assignedTo         : {target[CONSOLIDATED].count_documents({'type': 'inspections', 'assignedTo': {'$ne': None}})}")
print(f"   Inspections with workflowId (OID)   : {target[CONSOLIDATED].count_documents({'type': 'inspections', 'workflowId': {'$type': 'objectId'}})}")
print(f"   Inspections with statusId (OID)     : {target[CONSOLIDATED].count_documents({'type': 'inspections', 'statusId': {'$type': 'objectId'}})}")
print(f"   Tasks with statusId (OID)           : {target[CONSOLIDATED].count_documents({'type': 'tasks', 'statusId': {'$type': 'objectId'}})}")
print(f"   Activities with statusId (OID)      : {target[CONSOLIDATED].count_documents({'type': 'activities', 'statusId': {'$type': 'objectId'}})}")
print(f"   Workflows with statusId (OID)       : {target[CONSOLIDATED].count_documents({'type': 'workflows', 'statusId': {'$type': 'objectId'}})}")
print(f"   ResponseHistories with scoreValue   : {target[CONSOLIDATED].count_documents({'type': 'responsehistories', 'scoreValue': {'$ne': None}})}")
print(f"   InspObs with assignedTo             : {target[CONSOLIDATED].count_documents({'type': 'inspectionobservations', 'assignedTo': {'$ne': None}})}")
print(f"   Docs with datetime createdAt        : {target[CONSOLIDATED].count_documents({'createdAt': {'$type': 'date'}})}")
print(f"   Docs with OID _id                   : {target[CONSOLIDATED].count_documents({'_id': {'$type': 'objectId'}})}")

print("\n📊 Breakdown by type:")
for type_val in ["checklists", "sections", "questions", "responsevalues", "inspections",
                 "executions", "responsehistories", "tasks", "taskobservations",
                 "inspectionobservations", "reports", "activities", "workflows"]:
    count = target[CONSOLIDATED].count_documents({"type": type_val})
    print(f"   type={type_val:<30} {count:>6} docs")

print("\n🔧 Creating indexes on flat_entities...")
target[CONSOLIDATED].create_index("type")
target[CONSOLIDATED].create_index([("type", 1), ("tenantId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("isDeleted", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("checklistId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("inspectionId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("questionId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("sectionId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("workflowId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("assignedTo", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("executionId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("statusId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("createdAt", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("updatedAt", 1)])
print("   ✅ Indexes created")