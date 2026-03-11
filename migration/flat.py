"""
FLAT SCHEMA BUILDER v3 — seyo-development  →  seyo-flat-claude
===============================================================
All field names validated against live DB scan (validation.py output).

FIXES vs v2:
  questions       sectionId now falls back to native source field (q.get("sectionId"))
                  — q_to_section map only covers ~882 of 10925; source has sectionId natively
  inspections     Added: workflowId, assignedToId (was missing), geoLocation, localInspectionId,
                  referenceId, referenceName, executionTimings
  tasks           Added: geoLocation, referenceId, referenceName, deletedAt
  executions      Added: geoLocation
  responsehistories  Added: scoreValue, minScore, maxScore, enforceImage,
                     enforceIssue, enforceObservation, responseColor
                     (ALL exist on source responsehistories — were missed in v2)
  inspectionobservations  Added: assignedToId+Name, geoLocation, responseId
  taskobservations  Added: geoLocation, deletedAt
  checklists      Added: localChecklistId
  activities      Removed non-existent: description, tagIds
                  Added: activeActivity, dependencyActivity
  workflows       Fixed: statusId → workflowstatuses lookup (was plain string — WRONG)
                  Removed non-existent: checklistIds, inspectionIds, assignedTo,
                  tagIds, onSuccess, onFailure, description
"""

from pymongo import MongoClient, UpdateOne
from bson import ObjectId
from datetime import datetime

# ── CONFIG ─────────────────────────────────────────────────────────────────
SOURCE_HOST  = "192.168.0.172"   # source: seyo-development
SOURCE_PORT  = 27017
SOURCE_DB    = "seyo-development"

TARGET_HOST  = "192.168.0.130"   # target: seyo-flat-claude
TARGET_PORT  = 27017
TARGET_DB    = "seyo-flat-claude"
BATCH_SIZE   = 500
# ───────────────────────────────────────────────────────────────────────────

source_client = MongoClient(f"mongodb://{SOURCE_HOST}:{SOURCE_PORT}/", serverSelectionTimeoutMS=10000)
target_client = MongoClient(f"mongodb://{TARGET_HOST}:{TARGET_PORT}/", serverSelectionTimeoutMS=10000)
source        = source_client[SOURCE_DB]
target        = target_client[TARGET_DB]

def oid(v):
    """Convert ObjectId or any value to string, return None for falsy."""
    return str(v) if v else None

def ts(v):
    """Convert datetime to ISO string."""
    return v.isoformat() if isinstance(v, datetime) else str(v) if v else None

def geo(doc):
    """Extract geoLocation sub-document as flat fields, safely."""
    g = doc.get("geoLocation") or {}
    if not isinstance(g, dict):
        return {}
    return {
        "geoLat":     g.get("latitude"),
        "geoLng":     g.get("longitude"),
        "geoAddress": g.get("address"),
    }

# ── LOOKUP TABLES (load fully into memory) ────────────────────────────────
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
# ✅ FIX: workflowstatuses is a real collection — statusId on workflows is an ObjectId
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
# Users — indexed by both string id (ABP id) and _id (ObjectId)
users_map = {
    u.get("id", str(u["_id"])): {
        "name":      u.get("name"),
        "email":     u.get("email"),
        "userName":  u.get("userName"),
        "mongoId":   str(u["_id"])
    }
    for u in source.users.find({})
}
users_by_mongoid = {
    str(u["_id"]): {
        "name":     u.get("name"),
        "email":    u.get("email"),
        "userName": u.get("userName"),
        "id":       u.get("id")
    }
    for u in source.users.find({})
}

def resolve_user(user_id_str):
    if not user_id_str: return {}
    u = users_map.get(str(user_id_str)) or users_by_mongoid.get(str(user_id_str))
    return u or {}

print(f"   ✅ inspectionStatuses:{len(inspection_statuses)}  taskStatuses:{len(task_statuses)}")
print(f"   ✅ activityStatuses:{len(activity_statuses)}  workflowStatuses:{len(workflow_statuses)}")
print(f"   ✅ responsetypes:{len(response_types)}  tags:{len(tags_map)}  users:{len(users_map)}")

# ══════════════════════════════════════════════════════════════════════════
# STEP 1 — Build section→question map from checklistmapordernumbers
# Used as a supplement/override to the native sectionId on questions.
# ══════════════════════════════════════════════════════════════════════════
print("\n📐 Building question→section mapping from checklistmapordernumbers...")

q_to_section  = {}   # questionId → sectionId str  (from order map)
q_order_map   = {}   # questionId → orderNumber
sec_order_map = {}   # sectionId  → orderNumber

for doc in source.checklistmapordernumbers.find({"isDeleted": {"$ne": True}}):
    for detail in doc.get("orderDetails", []):
        sec_id = oid(detail.get("sectionId"))
        q_id   = oid(detail.get("questionId"))
        order  = detail.get("orderNumber")

        if sec_id and q_id:                         # Format C — flat legacy
            q_to_section[q_id]    = sec_id
            q_order_map[q_id]     = order
            sec_order_map[sec_id] = sec_order_map.get(sec_id, order)
        elif sec_id and not q_id:                   # Format B — section + nested questions
            sec_order_map[sec_id] = order
            for nested in detail.get("orderDetails", []):
                nq_id    = oid(nested.get("questionId"))
                nq_order = nested.get("orderNumber")
                if nq_id:
                    q_to_section[nq_id] = sec_id
                    q_order_map[nq_id]  = nq_order
        elif q_id and not sec_id:                   # Format A — standalone question
            q_order_map[q_id] = order

print(f"   ✅ Mapped {len(q_to_section)} questions to sections via order map")
print(f"   ✅ Mapped {len(q_order_map)} question order numbers")

def upsert_batch(collection, docs, key="_id"):
    if not docs: return
    ops = [UpdateOne({key: d[key]}, {"$set": d}, upsert=True) for d in docs]
    collection.bulk_write(ops, ordered=False)

def resolve_obj_ids(raw_list):
    """Normalise a list that may contain ObjectIds, dicts with _id, or plain strings."""
    result = []
    for x in (raw_list or []):
        if not x:
            continue
        if isinstance(x, dict):
            result.append(oid(x.get("_id") or x.get("id")))
        else:
            result.append(oid(x))
    return [v for v in result if v]

# ══════════════════════════════════════════════════════════════════════════
# TABLE 1 — flat_checklists
# Source fields: title, description, version, isTemplate, isLibrary, isLatest,
#               tenantId, createdBy, deletedBy, tagIds, isDeleted, deletedAt,
#               localChecklistId, createdAt, updatedAt
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_checklists...")
batch = []
for c in source.checklists.find({}):
    cid       = str(c["_id"])
    tag_names = [tags_map.get(str(t)) for t in c.get("tagIds", []) if t]
    creator   = resolve_user(c.get("createdBy", ""))
    batch.append({
        "_id":              cid,
        "type":             "checklists",
        "title":            c.get("title"),
        "description":      c.get("description"),
        "version":          c.get("version"),
        "localChecklistId": c.get("localChecklistId"),  # ✅ FIX: was missing
        "isTemplate":       c.get("isTemplate", False),
        "isLibrary":        c.get("isLibrary", False),
        "isLatest":         c.get("isLatest"),
        "tenantId":         c.get("tenantId"),
        "createdById":      c.get("createdBy"),
        "createdByName":    creator.get("name"),
        "createdByEmail":   creator.get("email"),
        "deletedBy":        c.get("deletedBy"),
        "tagIds":           [str(t) for t in c.get("tagIds", []) if t],
        "tagNames":         [t for t in tag_names if t],
        "isDeleted":        c.get("isDeleted", False),
        "deletedAt":        ts(c.get("deletedAt")),
        "createdAt":        ts(c.get("createdAt")),
        "updatedAt":        ts(c.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_checklists, batch); batch = []
upsert_batch(target.flat_checklists, batch)
print(f"   ✅ flat_checklists: {target.flat_checklists.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 2 — flat_sections
# Source fields: checklistId, title, description, isMandatory, orderNumber,
#               version, deletedAt, isDeleted, createdAt, updatedAt
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_sections...")
batch = []
for s in source.sections.find({}):
    sid = str(s["_id"])
    batch.append({
        "_id":         sid,
        "type":        "sections",
        "checklistId": oid(s.get("checklistId")),
        "title":       s.get("title"),
        "description": s.get("description"),
        "isMandatory": s.get("isMandatory", False),
        "orderNumber": sec_order_map.get(sid) or s.get("orderNumber"),
        "version":     s.get("version"),
        "isDeleted":   s.get("isDeleted", False),
        "deletedAt":   ts(s.get("deletedAt")),
        "createdAt":   ts(s.get("createdAt")),
        "updatedAt":   ts(s.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_sections, batch); batch = []
upsert_batch(target.flat_sections, batch)
print(f"   ✅ flat_sections: {target.flat_sections.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 3 — flat_questions
# Source fields: checklistId, sectionId (native!), questionText, responseType,
#               allowMultiple, isMandatory, orderNumber, version, tenantId,
#               createdBy, deletedAt, isDeleted, createdAt, updatedAt
# NOTE: source questions DO have sectionId natively.
#       q_to_section map supplements/overrides where available (~882 docs).
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_questions...")
batch = []
for q in source.questions.find({}):
    qid     = str(q["_id"])
    rt      = response_types.get(oid(q.get("responseType")), {})
    creator = resolve_user(q.get("createdBy", ""))
    # ✅ FIX: use order-map sectionId first, fall back to native sectionId
    resolved_section = q_to_section.get(qid) or oid(q.get("sectionId"))
    batch.append({
        "_id":              qid,
        "type":             "questions",
        "checklistId":      oid(q.get("checklistId")),
        "sectionId":        resolved_section,
        "questionText":     q.get("questionText"),
        "responseTypeId":   oid(q.get("responseType")),
        "responseTypeName": rt.get("displayName"),
        "responseTypeKey":  rt.get("type"),
        "orderNumber":      q_order_map.get(qid) or q.get("orderNumber"),
        "allowMultiple":    q.get("allowMultiple", False),
        "isMandatory":      q.get("isMandatory", False),
        "tenantId":         q.get("tenantId"),
        "createdById":      q.get("createdBy"),
        "createdByName":    creator.get("name"),
        "version":          q.get("version"),
        "isDeleted":        q.get("isDeleted", False),
        "deletedAt":        ts(q.get("deletedAt")),
        "createdAt":        ts(q.get("createdAt")),
        "updatedAt":        ts(q.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_questions, batch); batch = []
upsert_batch(target.flat_questions, batch)
print(f"   ✅ flat_questions: {target.flat_questions.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 4 — flat_response_options
# Source fields: questionId, responseValue, enableScore, scoreValue,
#               enforceIssue, enforceObservation, enforceImage, responseColor,
#               version, tenantId, createdBy, deletedAt, isDeleted, createdAt, updatedAt
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_response_options...")
batch = []
for r in source.responsevalues.find({}):
    creator = resolve_user(r.get("createdBy", ""))
    batch.append({
        "_id":                str(r["_id"]),
        "type":               "responsevalues",
        "questionId":         oid(r.get("questionId")),
        "responseValue":      r.get("responseValue"),
        "enableScore":        r.get("enableScore", False),
        "scoreValue":         r.get("scoreValue"),
        "enforceIssue":       r.get("enforceIssue", False),
        "enforceObservation": r.get("enforceObservation", False),
        "enforceImage":       r.get("enforceImage", False),
        "responseColor":      r.get("responseColor"),
        "version":            r.get("version"),
        "tenantId":           r.get("tenantId"),
        "createdById":        r.get("createdBy"),
        "createdByName":      creator.get("name"),
        "isDeleted":          r.get("isDeleted", False),
        "deletedAt":          ts(r.get("deletedAt")),
        "createdAt":          ts(r.get("createdAt")),
        "updatedAt":          ts(r.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_response_options, batch); batch = []
upsert_batch(target.flat_response_options, batch)
print(f"   ✅ flat_response_options: {target.flat_response_options.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 5 — flat_inspections
# Source fields: title, assignedTo, checklistId, scheduleId, workflowId,
#               status (ObjectId→inspectionstatuses), tagIds, tenantId,
#               createdBy, geoLocation, localInspectionId, referenceId,
#               referenceName, executionTimings, deletedAt, isDeleted, createdAt, updatedAt
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_inspections...")
checklist_titles = {
    str(c["_id"]): c.get("title")
    for c in source.checklists.find({}, {"title": 1})
}
batch = []
for i in source.inspections.find({}):
    status_id  = oid(i.get("status"))
    status_obj = inspection_statuses.get(status_id, {})
    creator    = resolve_user(i.get("createdBy", ""))
    assigned   = resolve_user(i.get("assignedTo", ""))
    cl_id      = oid(i.get("checklistId"))
    tag_names  = [tags_map.get(str(t)) for t in i.get("tagIds", []) if t]
    g          = geo(i)
    batch.append({
        "_id":                str(i["_id"]),
        "type":               "inspections",
        "title":              i.get("title"),
        "checklistId":        cl_id,
        "checklistTitle":     checklist_titles.get(cl_id),
        "scheduleId":         oid(i.get("scheduleId")),
        "workflowId":         oid(i.get("workflowId")),      # ✅ FIX: was missing
        "localInspectionId":  i.get("localInspectionId"),    # ✅ FIX: was missing
        "referenceId":        i.get("referenceId"),          # ✅ FIX: was missing
        "referenceName":      i.get("referenceName"),        # ✅ FIX: was missing
        "executionTimings":   i.get("executionTimings"),     # ✅ FIX: was missing
        "statusId":           status_id,
        "statusDisplayName":  status_obj.get("displayName"),
        "statusKey":          status_obj.get("status"),
        "tagIds":             [str(t) for t in i.get("tagIds", []) if t],
        "tagNames":           [t for t in tag_names if t],
        "assignedToId":       i.get("assignedTo"),           # ✅ FIX: was missing entirely
        "assignedToName":     assigned.get("name"),
        "assignedToEmail":    assigned.get("email"),
        "tenantId":           i.get("tenantId"),
        "createdById":        i.get("createdBy"),
        "createdByName":      creator.get("name"),
        "createdByEmail":     creator.get("email"),
        **g,                                                 # ✅ FIX: geoLat, geoLng, geoAddress
        "isDeleted":          i.get("isDeleted", False),
        "deletedAt":          ts(i.get("deletedAt")),
        "createdAt":          ts(i.get("createdAt")),
        "updatedAt":          ts(i.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_inspections, batch); batch = []
upsert_batch(target.flat_inspections, batch)
print(f"   ✅ flat_inspections: {target.flat_inspections.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 6 — flat_executions
# Source fields: inspectionId, checklistId, questionId, tenantId, createdBy,
#               geoLocation, isDeleted, createdAt, updatedAt
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_executions...")
batch = []
for e in source.executions.find({}):
    qid     = oid(e.get("questionId"))
    creator = resolve_user(e.get("createdBy", ""))
    g       = geo(e)
    batch.append({
        "_id":           str(e["_id"]),
        "type":          "executions",
        "inspectionId":  oid(e.get("inspectionId")),
        "checklistId":   oid(e.get("checklistId")),
        "questionId":    qid,
        "sectionId":     q_to_section.get(qid) or oid(e.get("sectionId")),
        "tenantId":      e.get("tenantId"),
        "createdById":   e.get("createdBy"),
        "createdByName": creator.get("name"),
        **g,                                                 # ✅ FIX: geoLat, geoLng, geoAddress
        "isDeleted":     e.get("isDeleted", False),
        "createdAt":     ts(e.get("createdAt")),
        "updatedAt":     ts(e.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_executions, batch); batch = []
upsert_batch(target.flat_executions, batch)
print(f"   ✅ flat_executions: {target.flat_executions.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 7 — flat_response_histories
# Source fields: executionId, questionId, responseIds[], responseValues[],
#               scoreValue, minScore, maxScore, enforceImage, enforceIssue,
#               enforceObservation, responseColor, isDeleted, createdAt, updatedAt
# ✅ FIX: scoreValue, minScore, maxScore, enforce*, responseColor all exist on
#         responsehistories in source — were completely missing in v2.
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_response_histories...")
batch = []
for rh in source.responsehistories.find({}):
    qid = oid(rh.get("questionId"))
    batch.append({
        "_id":                  str(rh["_id"]),
        "type":                 "responsehistories",
        "executionId":          oid(rh.get("executionId")),
        "questionId":           qid,
        "sectionId":            q_to_section.get(qid) or oid(rh.get("sectionId")),
        "responseIds":          [oid(r) for r in (rh.get("responseIds") or [])],
        "responseValues":       rh.get("responseValues") or [],
        # ✅ FIX: all score/enforce fields exist on responsehistories in source
        "scoreValue":           rh.get("scoreValue"),
        "minScore":             rh.get("minScore"),
        "maxScore":             rh.get("maxScore"),
        "enforceImage":         rh.get("enforceImage", False),
        "enforceIssue":         rh.get("enforceIssue", False),
        "enforceObservation":   rh.get("enforceObservation", False),
        "responseColor":        rh.get("responseColor"),
        "isDeleted":            rh.get("isDeleted", False),
        "createdAt":            ts(rh.get("createdAt")),
        "updatedAt":            ts(rh.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_response_histories, batch); batch = []
upsert_batch(target.flat_response_histories, batch)
print(f"   ✅ flat_response_histories: {target.flat_response_histories.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 8 — flat_tasks
# Source fields: title, description, assignedTo, inspectionId, executionId,
#               questionId, observationId, status (ObjectId→taskstatuses),
#               tagIds, tenantId, createdBy, geoLocation, referenceId,
#               referenceName, inspectionCompleted, deletedAt, isDeleted,
#               createdAt, updatedAt
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_tasks...")
batch = []
for t in source.tasks.find({}):
    status_id  = oid(t.get("status"))
    status_obj = task_statuses.get(status_id, {})
    assigned   = resolve_user(t.get("assignedTo", ""))
    creator    = resolve_user(t.get("createdBy", ""))
    qid        = oid(t.get("questionId"))
    tag_names  = [tags_map.get(str(tid)) for tid in t.get("tagIds", []) if tid]
    g          = geo(t)
    batch.append({
        "_id":                str(t["_id"]),
        "type":               "tasks",
        "title":              t.get("title"),
        "description":        t.get("description"),
        "inspectionId":       oid(t.get("inspectionId")),
        "executionId":        oid(t.get("executionId")),
        "questionId":         qid,
        "sectionId":          q_to_section.get(qid) or oid(t.get("sectionId")),
        "observationId":      oid(t.get("observationId")),
        "statusId":           status_id,
        "statusDisplayName":  status_obj.get("displayName"),
        "statusKey":          status_obj.get("status"),
        "tagIds":             [str(tid) for tid in t.get("tagIds", []) if tid],
        "tagNames":           [n for n in tag_names if n],
        "assignedToId":       t.get("assignedTo"),
        "assignedToName":     assigned.get("name"),
        "assignedToEmail":    assigned.get("email"),
        "createdById":        t.get("createdBy"),
        "createdByName":      creator.get("name"),
        "tenantId":           t.get("tenantId"),
        "referenceId":        t.get("referenceId"),          # ✅ FIX: was missing
        "referenceName":      t.get("referenceName"),        # ✅ FIX: was missing
        "inspectionCompleted": t.get("inspectionCompleted", False),
        **g,                                                 # ✅ FIX: geoLat, geoLng, geoAddress
        "isDeleted":          t.get("isDeleted", False),
        "deletedAt":          ts(t.get("deletedAt")),        # ✅ FIX: was missing
        "createdAt":          ts(t.get("createdAt")),
        "updatedAt":          ts(t.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_tasks, batch); batch = []
upsert_batch(target.flat_tasks, batch)
print(f"   ✅ flat_tasks: {target.flat_tasks.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 9 — flat_task_observations
# Source fields: taskId, executionId, questionId, observationId, description,
#               isIssue, isResolved, evidence, hasAttachment, attachmentCount,
#               geoLocation, tenantId, createdBy, deletedAt, isDeleted,
#               createdAt, updatedAt
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_task_observations...")
batch = []
for o in source.taskobservations.find({}):
    qid     = oid(o.get("questionId"))
    creator = resolve_user(o.get("createdBy", ""))
    g       = geo(o)
    batch.append({
        "_id":             str(o["_id"]),
        "type":            "taskobservations",
        "taskId":          oid(o.get("taskId")),
        "executionId":     oid(o.get("executionId")),
        "questionId":      qid,
        "sectionId":       q_to_section.get(qid) or oid(o.get("sectionId")),
        "observationId":   oid(o.get("observationId")),
        "description":     o.get("description"),
        "isIssue":         o.get("isIssue", False),
        "isResolved":      o.get("isResolved", False),
        "evidence":        o.get("evidence"),
        "hasAttachment":   o.get("hasAttachment", False),
        "attachmentCount": o.get("attachmentCount", 0),
        "createdById":     o.get("createdBy"),
        "createdByName":   creator.get("name"),
        "tenantId":        o.get("tenantId"),
        **g,                                                 # ✅ FIX: geoLat, geoLng, geoAddress
        "isDeleted":       o.get("isDeleted", False),
        "deletedAt":       ts(o.get("deletedAt")),          # ✅ FIX: was missing
        "createdAt":       ts(o.get("createdAt")),
        "updatedAt":       ts(o.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_task_observations, batch); batch = []
upsert_batch(target.flat_task_observations, batch)
print(f"   ✅ flat_task_observations: {target.flat_task_observations.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 10 — flat_inspection_observations
# Source fields: executionId, questionId, assignedTo, responseId (singular),
#               description, isIssue, evidence, hasAttachment, attachmentCount,
#               geoLocation, tenantId, createdBy, isDeleted, createdAt, updatedAt
# ✅ FIX: assignedTo, geoLocation, responseId all exist in source — were missing
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_inspection_observations...")
batch = []
for o in source.inspectionobservations.find({}):
    qid      = oid(o.get("questionId"))
    creator  = resolve_user(o.get("createdBy", ""))
    assigned = resolve_user(o.get("assignedTo", ""))
    g        = geo(o)
    batch.append({
        "_id":             str(o["_id"]),
        "type":            "inspectionobservations",
        "executionId":     oid(o.get("executionId")),
        "questionId":      qid,
        "sectionId":       q_to_section.get(qid) or oid(o.get("sectionId")),
        "responseId":      oid(o.get("responseId")),         # ✅ FIX: singular ref, was missing
        "assignedToId":    o.get("assignedTo"),              # ✅ FIX: was missing
        "assignedToName":  assigned.get("name"),             # ✅ FIX: was missing
        "description":     o.get("description"),
        "isIssue":         o.get("isIssue", False),
        "evidence":        o.get("evidence"),
        "hasAttachment":   o.get("hasAttachment", False),
        "attachmentCount": o.get("attachmentCount", 0),
        "createdById":     o.get("createdBy"),
        "createdByName":   creator.get("name"),
        "tenantId":        o.get("tenantId"),
        **g,                                                 # ✅ FIX: geoLat, geoLng, geoAddress
        "isDeleted":       o.get("isDeleted", False),
        "createdAt":       ts(o.get("createdAt")),
        "updatedAt":       ts(o.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_inspection_observations, batch); batch = []
upsert_batch(target.flat_inspection_observations, batch)
print(f"   ✅ flat_inspection_observations: {target.flat_inspection_observations.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 11 — flat_reports
# Source fields: inspectionId, reportName, reportNumber, reportDate,
#               tenantId, isDeleted, inspectionUpdatedAt, createdAt, updatedAt
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_reports...")
inspection_docs = {
    str(i["_id"]): {
        "title":       i.get("title"),
        "statusId":    oid(i.get("status")),
        "checklistId": oid(i.get("checklistId"))
    }
    for i in source.inspections.find({}, {"title": 1, "status": 1, "checklistId": 1})
}
batch = []
for r in source.reports.find({}):
    ins_id  = oid(r.get("inspectionId"))
    ins_obj = inspection_docs.get(ins_id, {})
    s_obj   = inspection_statuses.get(ins_obj.get("statusId"), {})
    batch.append({
        "_id":                   str(r["_id"]),
        "type":                  "reports",
        "reportName":            r.get("reportName"),
        "reportNumber":          r.get("reportNumber"),
        "reportDate":            ts(r.get("reportDate")),
        "inspectionId":          ins_id,
        "inspectionTitle":       ins_obj.get("title"),
        "inspectionChecklistId": ins_obj.get("checklistId"),
        "inspectionStatusName":  s_obj.get("displayName"),
        "tenantId":              r.get("tenantId"),
        "isDeleted":             r.get("isDeleted", False),
        "inspectionUpdatedAt":   ts(r.get("inspectionUpdatedAt")),
        "createdAt":             ts(r.get("createdAt")),
        "updatedAt":             ts(r.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_reports, batch); batch = []
upsert_batch(target.flat_reports, batch)
print(f"   ✅ flat_reports: {target.flat_reports.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 12 — flat_activities
# Source fields: title, assignedTo, checklists[], inspections[], statusId,
#               workflowId, roleId, orderNumber, onSuccess, onFailure,
#               activeActivity, dependencyActivity, tenantId, createdBy,
#               deletedAt, isDeleted, createdAt, updatedAt
# ✅ FIX vs v2: removed non-existent description, tagIds
#               added activeActivity, dependencyActivity
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_activities...")
batch = []
for a in source.activities.find({}):
    status_id  = oid(a.get("statusId"))
    status_obj = activity_statuses.get(status_id, {})
    assigned   = resolve_user(a.get("assignedTo", ""))
    creator    = resolve_user(a.get("createdBy", ""))
    # checklists[] and inspections[] are ObjectId arrays or dicts
    checklist_ids  = resolve_obj_ids(a.get("checklists", []))
    inspection_ids = resolve_obj_ids(a.get("inspections", []))
    batch.append({
        "_id":                str(a["_id"]),
        "type":               "activities",
        "title":              a.get("title"),
        "tenantId":           a.get("tenantId"),
        "statusId":           status_id,
        "statusDisplayName":  status_obj.get("displayName"),
        "statusKey":          status_obj.get("status"),
        "assignedToId":       a.get("assignedTo"),
        "assignedToName":     assigned.get("name"),
        "assignedToEmail":    assigned.get("email"),
        "workflowId":         oid(a.get("workflowId")),
        "roleId":             oid(a.get("roleId")),
        "orderNumber":        a.get("orderNumber"),
        "checklistIds":       checklist_ids,
        "inspectionIds":      inspection_ids,
        "onSuccess":          a.get("onSuccess"),
        "onFailure":          a.get("onFailure"),
        "activeActivity":     a.get("activeActivity"),       # ✅ FIX: was missing
        "dependencyActivity": a.get("dependencyActivity"),   # ✅ FIX: was missing
        "createdById":        a.get("createdBy"),
        "createdByName":      creator.get("name"),
        "createdByEmail":     creator.get("email"),
        "isDeleted":          a.get("isDeleted", False),
        "deletedAt":          ts(a.get("deletedAt")),
        "createdAt":          ts(a.get("createdAt")),
        "updatedAt":          ts(a.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_activities, batch); batch = []
upsert_batch(target.flat_activities, batch)
print(f"   ✅ flat_activities: {target.flat_activities.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 13 — flat_workflows
# Source fields: title, statusId (ObjectId→workflowstatuses!), tenantId,
#               createdBy, deletedAt, isDeleted, createdAt, updatedAt
# ✅ FIX vs v2: statusId is an ObjectId → workflowstatuses (NOT a plain string!)
#               removed non-existent: assignedTo, checklistIds, inspectionIds,
#               tagIds, onSuccess, onFailure, description
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_workflows...")
batch = []
for w in source.workflows.find({}):
    status_id  = oid(w.get("statusId"))                      # ✅ FIX: field is statusId
    status_obj = workflow_statuses.get(status_id, {})        # ✅ FIX: lookup workflowstatuses
    creator    = resolve_user(w.get("createdBy", ""))
    batch.append({
        "_id":                str(w["_id"]),
        "type":               "workflows",
        "title":              w.get("title"),
        "tenantId":           w.get("tenantId"),
        "statusId":           status_id,
        "statusDisplayName":  status_obj.get("displayName"),  # ✅ FIX: resolved from workflowstatuses
        "statusKey":          status_obj.get("status"),       # ✅ FIX: resolved from workflowstatuses
        "createdById":        w.get("createdBy"),
        "createdByName":      creator.get("name"),
        "createdByEmail":     creator.get("email"),
        "isDeleted":          w.get("isDeleted", False),
        "deletedAt":          ts(w.get("deletedAt")),
        "createdAt":          ts(w.get("createdAt")),
        "updatedAt":          ts(w.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_workflows, batch); batch = []
upsert_batch(target.flat_workflows, batch)
print(f"   ✅ flat_workflows: {target.flat_workflows.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# STEP FINAL — Consolidate all flat collections into ONE collection
# ══════════════════════════════════════════════════════════════════════════
FLAT_COLLECTIONS = [
    "flat_checklists", "flat_sections", "flat_questions",
    "flat_response_options", "flat_inspections", "flat_executions",
    "flat_response_histories", "flat_tasks",
    "flat_task_observations", "flat_inspection_observations",
    "flat_reports", "flat_activities", "flat_workflows",
]

CONSOLIDATED = "flat_entities"

print("\n🔀 Consolidating all flat collections → flat_entities...")
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

print("\n📋 Diagnostic checks:")
print(f"   Questions with sectionId        : {target[CONSOLIDATED].count_documents({'type': 'questions', 'sectionId': {'$ne': None}})}")
print(f"   Questions without sectionId     : {target[CONSOLIDATED].count_documents({'type': 'questions', 'sectionId': None})}")
print(f"   Inspections with assignedToId   : {target[CONSOLIDATED].count_documents({'type': 'inspections', 'assignedToId': {'$ne': None}})}")
print(f"   Inspections with workflowId     : {target[CONSOLIDATED].count_documents({'type': 'inspections', 'workflowId': {'$ne': None}})}")
print(f"   Tasks with status resolved      : {target[CONSOLIDATED].count_documents({'type': 'tasks', 'statusDisplayName': {'$ne': None}})}")
print(f"   Inspections with status resolved: {target[CONSOLIDATED].count_documents({'type': 'inspections', 'statusDisplayName': {'$ne': None}})}")
print(f"   Activities with status resolved : {target[CONSOLIDATED].count_documents({'type': 'activities', 'statusDisplayName': {'$ne': None}})}")
print(f"   Workflows with status resolved  : {target[CONSOLIDATED].count_documents({'type': 'workflows', 'statusDisplayName': {'$ne': None}})}")
print(f"   ResponseHistories with scoreValue: {target[CONSOLIDATED].count_documents({'type': 'responsehistories', 'scoreValue': {'$ne': None}})}")
print(f"   InspObs with assignedToId       : {target[CONSOLIDATED].count_documents({'type': 'inspectionobservations', 'assignedToId': {'$ne': None}})}")

print("\n📊 Breakdown by type:")
for type_val in ["checklists","sections","questions","responsevalues","inspections",
                 "executions","responsehistories","tasks","taskobservations",
                 "inspectionobservations","reports","activities","workflows"]:
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
target[CONSOLIDATED].create_index([("type", 1), ("assignedToId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("executionId", 1)])
print("   ✅ Indexes created")