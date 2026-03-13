"""
FLAT SCHEMA BUILDER v4 — seyo-development  →  seyo-flat-claude
===============================================================
KEY RULE: _id is passed through RAW (same ObjectId as source — no str conversion).
          FK fields (checklistId, inspectionId, etc.) also kept as raw ObjectId.
          str() is used ONLY for in-memory dict key lookups (status maps, user maps).
All field names validated against live DB scan output.
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
TARGET_DB    = "seyo-flat-claude-v3"
BATCH_SIZE   = 500000
# ───────────────────────────────────────────────────────────────────────────

source_client = MongoClient(f"mongodb://{SOURCE_HOST}:{SOURCE_PORT}/", serverSelectionTimeoutMS=10000)
target_client = MongoClient(f"mongodb://{TARGET_HOST}:{TARGET_PORT}/", serverSelectionTimeoutMS=10000)
source        = source_client[SOURCE_DB]
target        = target_client[TARGET_DB]

def sid(v):
    """String-ify for dict key lookup ONLY. Never use on stored _id or FK fields."""
    return str(v) if v else None

def ts(v):
    """Convert datetime to ISO string."""
    return v.isoformat() if isinstance(v, datetime) else str(v) if v else None

def geo(doc):
    """Flatten geoLocation sub-document."""
    g = doc.get("geoLocation") or {}
    if not isinstance(g, dict):
        return {}
    return {
        "geoLat":     g.get("latitude"),
        "geoLng":     g.get("longitude"),
        "geoAddress": g.get("address"),
    }

def resolve_obj_ids(raw_list):
    """
    Normalise a list that may contain ObjectIds, dicts with _id, or plain strings.
    Returns list of raw values (ObjectId or string) as-is — no conversion.
    """
    result = []
    for x in (raw_list or []):
        if not x:
            continue
        if isinstance(x, dict):
            v = x.get("_id") or x.get("id")
            if v: result.append(v)
        else:
            result.append(x)
    return result

# ── LOOKUP TABLES — keyed by str(_id) for dict access only ────────────────
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
users_map = {
    u.get("id", str(u["_id"])): {
        "name": u.get("name"), "email": u.get("email"), "userName": u.get("userName")
    }
    for u in source.users.find({})
}
users_by_mongoid = {
    str(u["_id"]): {
        "name": u.get("name"), "email": u.get("email"), "userName": u.get("userName")
    }
    for u in source.users.find({})
}

def resolve_user(user_id):
    """Resolve user by ABP string id or ObjectId string. Returns dict with name/email."""
    if not user_id: return {}
    u = users_map.get(str(user_id)) or users_by_mongoid.get(str(user_id))
    return u or {}

print(f"   ✅ statuses loaded  users:{len(users_map)}")

# ── SECTION/QUESTION ORDER MAP ─────────────────────────────────────────────
print("\n📐 Building question→section mapping from checklistmapordernumbers...")

q_to_section  = {}   # str(questionId) → raw sectionId ObjectId
q_order_map   = {}   # str(questionId) → orderNumber
sec_order_map = {}   # str(sectionId)  → orderNumber

for doc in source.checklistmapordernumbers.find({"isDeleted": {"$ne": True}}):
    for detail in doc.get("orderDetails", []):
        sec_raw = detail.get("sectionId")
        q_raw   = detail.get("questionId")
        order   = detail.get("orderNumber")
        sec_key = sid(sec_raw)
        q_key   = sid(q_raw)

        if sec_raw and q_raw:
            q_to_section[q_key]  = sec_raw          # keep raw ObjectId
            q_order_map[q_key]   = order
            sec_order_map[sec_key] = sec_order_map.get(sec_key, order)
        elif sec_raw and not q_raw:
            sec_order_map[sec_key] = order
            for nested in detail.get("orderDetails", []):
                nq_raw   = nested.get("questionId")
                nq_order = nested.get("orderNumber")
                if nq_raw:
                    q_to_section[sid(nq_raw)] = sec_raw  # keep raw ObjectId
                    q_order_map[sid(nq_raw)]  = nq_order
        elif q_raw and not sec_raw:
            q_order_map[q_key] = order

print(f"   ✅ {len(q_to_section)} questions mapped to sections")

def upsert_batch(collection, docs):
    if not docs: return
    ops = [UpdateOne({"_id": d["_id"]}, {"$set": d}, upsert=True) for d in docs]
    collection.bulk_write(ops, ordered=False)

# ══════════════════════════════════════════════════════════════════════════
# TABLE 1 — flat_checklists
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_checklists...")
batch = []
for c in source.checklists.find({}):
    tag_names = [tags_map.get(sid(t)) for t in c.get("tagIds", []) if t]
    creator   = resolve_user(c.get("createdBy"))
    batch.append({
        "_id":              c["_id"],               # ← raw ObjectId, unchanged
        "type":             "checklists",
        "title":            c.get("title"),
        "description":      c.get("description"),
        "version":          c.get("version"),
        "localChecklistId": c.get("localChecklistId"),
        "isTemplate":       c.get("isTemplate", False),
        "isLibrary":        c.get("isLibrary", False),
        "isLatest":         c.get("isLatest"),
        "tenantId":         c.get("tenantId"),
        "createdBy":        c.get("createdBy"),     # ← raw value (string userId)
        "createdByName":    creator.get("name"),
        "createdByEmail":   creator.get("email"),
        "deletedBy":        c.get("deletedBy"),
        "tagIds":           c.get("tagIds", []),    # ← raw ObjectId list
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_sections...")
batch = []
for s in source.sections.find({}):
    batch.append({
        "_id":         s["_id"],                    # ← raw ObjectId
        "type":        "sections",
        "checklistId": s.get("checklistId"),        # ← raw ObjectId
        "title":       s.get("title"),
        "description": s.get("description"),
        "isMandatory": s.get("isMandatory", False),
        "orderNumber": sec_order_map.get(sid(s["_id"])) or s.get("orderNumber"),
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_questions...")
batch = []
for q in source.questions.find({}):
    qkey    = sid(q["_id"])
    rt      = response_types.get(sid(q.get("responseType")), {})
    creator = resolve_user(q.get("createdBy"))
    # order-map section first, fall back to native sectionId from source
    resolved_section = q_to_section.get(qkey) or q.get("sectionId")
    batch.append({
        "_id":              q["_id"],               # ← raw ObjectId
        "type":             "questions",
        "checklistId":      q.get("checklistId"),   # ← raw ObjectId
        "sectionId":        resolved_section,       # ← raw ObjectId (from map or native)
        "questionText":     q.get("questionText"),
        "responseTypeId":   q.get("responseType"),  # ← raw ObjectId
        "responseTypeName": rt.get("displayName"),
        "responseTypeKey":  rt.get("type"),
        "orderNumber":      q_order_map.get(qkey) or q.get("orderNumber"),
        "allowMultiple":    q.get("allowMultiple", False),
        "isMandatory":      q.get("isMandatory", False),
        "tenantId":         q.get("tenantId"),
        "createdBy":      q.get("createdBy"),
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_response_options...")
batch = []
for r in source.responsevalues.find({}):
    creator = resolve_user(r.get("createdBy"))
    batch.append({
        "_id":                r["_id"],             # ← raw ObjectId
        "type":               "responsevalues",
        "questionId":         r.get("questionId"),  # ← raw ObjectId
        "responseValue":      r.get("responseValue"),
        "enableScore":        r.get("enableScore", False),
        "scoreValue":         r.get("scoreValue"),
        "enforceIssue":       r.get("enforceIssue", False),
        "enforceObservation": r.get("enforceObservation", False),
        "enforceImage":       r.get("enforceImage", False),
        "responseColor":      r.get("responseColor"),
        "version":            r.get("version"),
        "tenantId":           r.get("tenantId"),
        "createdBy":        r.get("createdBy"),
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_inspections...")
checklist_titles = {
    sid(c["_id"]): c.get("title")
    for c in source.checklists.find({}, {"title": 1})
}
batch = []
for i in source.inspections.find({}):
    status_obj = inspection_statuses.get(sid(i.get("status")), {})
    creator    = resolve_user(i.get("createdBy"))
    assigned   = resolve_user(i.get("assignedTo"))
    cl_id      = i.get("checklistId")
    tag_names  = [tags_map.get(sid(t)) for t in i.get("tagIds", []) if t]
    g          = geo(i)
    batch.append({
        "_id":                i["_id"],             # ← raw ObjectId
        "type":               "inspections",
        "title":              i.get("title"),
        "checklistId":        cl_id,                # ← raw ObjectId
        "checklistTitle":     checklist_titles.get(sid(cl_id)),
        "scheduleId":         i.get("scheduleId"),  # ← raw ObjectId
        "workflowId":         i.get("workflowId"),  # ← raw ObjectId
        "localInspectionId":  i.get("localInspectionId"),
        "referenceId":        i.get("referenceId"),
        "referenceName":      i.get("referenceName"),
        "executionTimings":   i.get("executionTimings"),
        "statusId":           i.get("status"),      # ← raw ObjectId (source field is "status")
        # "statusDisplayName":  status_obj.get("displayName"),
        "statusKey":          status_obj.get("status"),
        "tagIds":             i.get("tagIds", []),  # ← raw ObjectId list
        "tagNames":           [t for t in tag_names if t],
        "assignedTo":       i.get("assignedTo"),  # ← raw value
        "assignedToName":     assigned.get("name"),
        "assignedToEmail":    assigned.get("email"),
        "tenantId":           i.get("tenantId"),
        "createdBy":        i.get("createdBy"),
        "createdByName":      creator.get("name"),
        "createdByEmail":     creator.get("email"),
        **g,
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_executions...")
batch = []
for e in source.executions.find({}):
    qid     = e.get("questionId")
    creator = resolve_user(e.get("createdBy"))
    g       = geo(e)
    batch.append({
        "_id":           e["_id"],                  # ← raw ObjectId
        "type":          "executions",
        "inspectionId":  e.get("inspectionId"),     # ← raw ObjectId
        "checklistId":   e.get("checklistId"),      # ← raw ObjectId
        "questionId":    qid,                       # ← raw ObjectId
        "sectionId":     q_to_section.get(sid(qid)) or e.get("sectionId"),
        "tenantId":      e.get("tenantId"),
        "createdBy":   e.get("createdBy"),
        "createdByName": creator.get("name"),
        **g,
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_response_histories...")
batch = []
for rh in source.responsehistories.find({}):
    qid = rh.get("questionId")
    batch.append({
        "_id":                  rh["_id"],          # ← raw ObjectId
        "type":                 "responsehistories",
        "executionId":          rh.get("executionId"),   # ← raw ObjectId
        "questionId":           qid,                     # ← raw ObjectId
        "sectionId":            q_to_section.get(sid(qid)) or rh.get("sectionId"),
        "responseIds":          rh.get("responseIds") or [],    # ← raw ObjectId list
        "responseValues":       rh.get("responseValues") or [],
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_tasks...")
batch = []
for t in source.tasks.find({}):
    status_obj = task_statuses.get(sid(t.get("status")), {})
    assigned   = resolve_user(t.get("assignedTo"))
    creator    = resolve_user(t.get("createdBy"))
    qid        = t.get("questionId")
    tag_names  = [tags_map.get(sid(tid)) for tid in t.get("tagIds", []) if tid]
    g          = geo(t)
    batch.append({
        "_id":                t["_id"],             # ← raw ObjectId
        "type":               "tasks",
        "title":              t.get("title"),
        "description":        t.get("description"),
        "inspectionId":       t.get("inspectionId"),    # ← raw ObjectId
        "executionId":        t.get("executionId"),     # ← raw ObjectId
        "questionId":         qid,                      # ← raw ObjectId
        "sectionId":          q_to_section.get(sid(qid)) or t.get("sectionId"),
        "observationId":      t.get("observationId"),   # ← raw ObjectId
        "statusId":           t.get("status"),          # ← raw ObjectId (source field is "status")
        # "statusDisplayName":  status_obj.get("displayName"),
        "statusKey":          status_obj.get("status"),
        "tagIds":             t.get("tagIds", []),      # ← raw ObjectId list
        "tagNames":           [n for n in tag_names if n],
        "assignedTo":       t.get("assignedTo"),
        "assignedToName":     assigned.get("name"),
        "assignedToEmail":    assigned.get("email"),
        "createdBy":        t.get("createdBy"),
        "createdByName":      creator.get("name"),
        "tenantId":           t.get("tenantId"),
        "referenceId":        t.get("referenceId"),
        "referenceName":      t.get("referenceName"),
        "inspectionCompleted": t.get("inspectionCompleted", False),
        **g,
        "isDeleted":          t.get("isDeleted", False),
        "deletedAt":          ts(t.get("deletedAt")),
        "createdAt":          ts(t.get("createdAt")),
        "updatedAt":          ts(t.get("updatedAt")),
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
    qid     = o.get("questionId")
    creator = resolve_user(o.get("createdBy"))
    g       = geo(o)
    batch.append({
        "_id":             o["_id"],                # ← raw ObjectId
        "type":            "taskobservations",
        "taskId":          o.get("taskId"),         # ← raw ObjectId
        "executionId":     o.get("executionId"),    # ← raw ObjectId
        "questionId":      qid,                     # ← raw ObjectId
        "sectionId":       q_to_section.get(sid(qid)) or o.get("sectionId"),
        "observationId":   o.get("observationId"),  # ← raw ObjectId
        "description":     o.get("description"),
        "isIssue":         o.get("isIssue", False),
        "isResolved":      o.get("isResolved", False),
        "evidence":        o.get("evidence"),
        "hasAttachment":   o.get("hasAttachment", False),
        "attachmentCount": o.get("attachmentCount", 0),
        "createdBy":     o.get("createdBy"),
        "createdByName":   creator.get("name"),
        "tenantId":        o.get("tenantId"),
        **g,
        "isDeleted":       o.get("isDeleted", False),
        "deletedAt":       ts(o.get("deletedAt")),
        "createdAt":       ts(o.get("createdAt")),
        "updatedAt":       ts(o.get("updatedAt")),
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
    qid      = o.get("questionId")
    creator  = resolve_user(o.get("createdBy"))
    assigned = resolve_user(o.get("assignedTo"))
    g        = geo(o)
    batch.append({
        "_id":             o["_id"],                # ← raw ObjectId
        "type":            "inspectionobservations",
        "executionId":     o.get("executionId"),    # ← raw ObjectId
        "questionId":      qid,                     # ← raw ObjectId
        "sectionId":       q_to_section.get(sid(qid)) or o.get("sectionId"),
        "responseId":      o.get("responseId"),     # ← raw ObjectId
        "assignedTo":    o.get("assignedTo"),
        "assignedToName":  assigned.get("name"),
        "description":     o.get("description"),
        "isIssue":         o.get("isIssue", False),
        "evidence":        o.get("evidence"),
        "hasAttachment":   o.get("hasAttachment", False),
        "attachmentCount": o.get("attachmentCount", 0),
        "createdBy":     o.get("createdBy"),
        "createdByName":   creator.get("name"),
        "tenantId":        o.get("tenantId"),
        **g,
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_reports...")
inspection_lookup = {
    sid(i["_id"]): {
        "title":       i.get("title"),
        "statusId":    sid(i.get("status")),
        "checklistId": i.get("checklistId")
    }
    for i in source.inspections.find({}, {"title": 1, "status": 1, "checklistId": 1})
}
batch = []
for r in source.reports.find({}):
    ins_obj = inspection_lookup.get(sid(r.get("inspectionId")), {})
    s_obj   = inspection_statuses.get(ins_obj.get("statusId"), {})
    batch.append({
        "_id":                   r["_id"],              # ← raw ObjectId
        "type":                  "reports",
        "reportName":            r.get("reportName"),
        "reportNumber":          r.get("reportNumber"),
        "reportDate":            ts(r.get("reportDate")),
        "inspectionId":          r.get("inspectionId"), # ← raw ObjectId
        "inspectionTitle":       ins_obj.get("title"),
        "inspectionChecklistId": ins_obj.get("checklistId"),  # ← raw ObjectId
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_activities...")
batch = []
for a in source.activities.find({}):
    status_obj     = activity_statuses.get(sid(a.get("statusId")), {})
    assigned       = resolve_user(a.get("assignedTo"))
    creator        = resolve_user(a.get("createdBy"))
    checklist_ids  = resolve_obj_ids(a.get("checklists", []))
    inspection_ids = resolve_obj_ids(a.get("inspections", []))
    batch.append({
        "_id":                a["_id"],             # ← raw ObjectId
        "type":               "activities",
        "title":              a.get("title"),
        "tenantId":           a.get("tenantId"),
        "statusId":           a.get("statusId"),    # ← raw ObjectId
        # "statusDisplayName":  status_obj.get("displayName"),
        "statusKey":          status_obj.get("status"),
        "assignedTo":       a.get("assignedTo"),
        "assignedToName":     assigned.get("name"),
        "assignedToEmail":    assigned.get("email"),
        "workflowId":         a.get("workflowId"), # ← raw ObjectId
        "roleId":             a.get("roleId"),      # ← raw ObjectId
        "orderNumber":        a.get("orderNumber"),
        "checklistIds":       checklist_ids,        # ← raw ObjectId list
        "inspectionIds":      inspection_ids,       # ← raw ObjectId list
        "onSuccess":          a.get("onSuccess"),
        "onFailure":          a.get("onFailure"),
        "activeActivity":     a.get("activeActivity"),
        "dependencyActivity": a.get("dependencyActivity"),
        "createdBy":        a.get("createdBy"),
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
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_workflows...")
batch = []
for w in source.workflows.find({}):
    status_obj = workflow_statuses.get(sid(w.get("statusId")), {})
    creator    = resolve_user(w.get("createdBy"))
    batch.append({
        "_id":                w["_id"],             # ← raw ObjectId
        "type":               "workflows",
        "title":              w.get("title"),
        "tenantId":           w.get("tenantId"),
        "statusId":           w.get("statusId"),    # ← raw ObjectId
        # "statusDisplayName":  status_obj.get("displayName"),
        "statusKey":          status_obj.get("status"),
        "createdBy":        w.get("createdBy"),
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
# CONSOLIDATE → flat_entities
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
print(f"🎉 DONE  →  {TARGET_HOST}/{TARGET_DB}.{CONSOLIDATED}")
print("=" * 60)
print(f"   total docs: {target[CONSOLIDATED].count_documents({})}")

print("\n📊 Breakdown by type:")
for t in ["checklists","sections","questions","responsevalues","inspections",
          "executions","responsehistories","tasks","taskobservations",
          "inspectionobservations","reports","activities","workflows"]:
    print(f"   {t:<30} {target[CONSOLIDATED].count_documents({'type': t}):>6}")

print("\n📋 Diagnostics:")
print(f"   questions with sectionId     : {target[CONSOLIDATED].count_documents({'type':'questions','sectionId':{'$ne':None}})}")
print(f"   inspections with workflowId  : {target[CONSOLIDATED].count_documents({'type':'inspections','workflowId':{'$ne':None}})}")
print(f"   tasks with statusKey         : {target[CONSOLIDATED].count_documents({'type':'tasks','statusKey':{'$ne':None}})}")
print(f"   activities with statusKey    : {target[CONSOLIDATED].count_documents({'type':'activities','statusKey':{'$ne':None}})}")
print(f"   workflows with statusKey     : {target[CONSOLIDATED].count_documents({'type':'workflows','statusKey':{'$ne':None}})}")
print(f"   responsehistories w/ score   : {target[CONSOLIDATED].count_documents({'type':'responsehistories','scoreValue':{'$ne':None}})}")
print(f"   inspObs with assignedTo    : {target[CONSOLIDATED].count_documents({'type':'inspectionobservations','assignedTo':{'$ne':None}})}")

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
print("   ✅ Indexes created")