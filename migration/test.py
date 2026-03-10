

# ───────────────────────────────────────────────────────────────────────────
"""
FLAT SCHEMA BUILDER — seyo-development
=======================================
Source-of-truth for section→question mapping: checklistmapordernumbers
Logic reverse-engineered from ChecklistService.js

Flat tables produced:
  1. flat_checklists
  2. flat_sections
  3. flat_questions
  4. flat_response_options
  5. flat_inspections
  6. flat_executions
  7. flat_response_histories
  8. flat_tasks
  9. flat_task_observations
 10. flat_inspection_observations
 11. flat_reports
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
TARGET_DB    = "seyo-flat-claude-v1"
BATCH_SIZE   = 500
# ───────────────────────────────────────────────────────────────────────────

source_client = MongoClient(f"mongodb://{SOURCE_HOST}:{SOURCE_PORT}/", serverSelectionTimeoutMS=5000)
target_client = MongoClient(f"mongodb://{TARGET_HOST}:{TARGET_PORT}/", serverSelectionTimeoutMS=5000)
source        = source_client[SOURCE_DB]
target        = target_client[TARGET_DB]

def oid(v):
    return str(v) if v else None

def ts(v):
    return v.isoformat() if isinstance(v, datetime) else str(v) if v else None

# ── LOOKUP TABLES (small, load fully into memory) ─────────────────────────
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
        "name": u.get("name"), "email": u.get("email"),
        "userName": u.get("userName"), "mongoId": str(u["_id"])
    }
    for u in source.users.find({})
}
# also index by _id string for fallback
users_by_mongoid = {
    str(u["_id"]): {
        "name": u.get("name"), "email": u.get("email"),
        "userName": u.get("userName"), "id": u.get("id")
    }
    for u in source.users.find({})
}

def resolve_user(user_id_str):
    if not user_id_str: return {}
    u = users_map.get(user_id_str) or users_by_mongoid.get(user_id_str)
    return u or {}

print(f"   ✅ inspectionStatuses:{len(inspection_statuses)}  taskStatuses:{len(task_statuses)}")
print(f"   ✅ responsetypes:{len(response_types)}  tags:{len(tags_map)}  users:{len(users_map)}")

# ══════════════════════════════════════════════════════════════════════════
# STEP 1 — Build section→question map from checklistmapordernumbers
# Logic from ChecklistService.getOrderNumbersForChecklist() and
#            constructSequentialOrderMap()
#
# orderDetails entries can be:
#   A) { questionId, orderNumber }                    → standalone question
#   B) { sectionId, orderNumber,
#         orderDetails: [{ questionId, orderNumber }] } → section + its questions
#   C) { sectionId, questionId, orderNumber }         → legacy flat format
# ══════════════════════════════════════════════════════════════════════════
print("\n📐 Building question→section mapping from checklistmapordernumbers...")

# Maps:  question_id_str → { sectionId, questionOrderInSection, sectionOrderNumber }
# Maps:  section_id_str  → { orderNumber }
q_to_section   = {}   # questionId → sectionId str
q_order_map    = {}   # questionId → orderNumber
sec_order_map  = {}   # sectionId  → orderNumber

for doc in source.checklistmapordernumbers.find({"isDeleted": {"$ne": True}}):
    for detail in doc.get("orderDetails", []):
        sec_id = oid(detail.get("sectionId"))
        q_id   = oid(detail.get("questionId"))
        order  = detail.get("orderNumber")

        if sec_id and q_id:
            # Format C — legacy flat: question directly under section
            q_to_section[q_id]  = sec_id
            q_order_map[q_id]   = order
            sec_order_map[sec_id] = sec_order_map.get(sec_id, order)

        elif sec_id and not q_id:
            # Format B — section entry; questions are nested in orderDetails
            sec_order_map[sec_id] = order
            for nested in detail.get("orderDetails", []):
                nq_id    = oid(nested.get("questionId"))
                nq_order = nested.get("orderNumber")
                if nq_id:
                    q_to_section[nq_id] = sec_id
                    q_order_map[nq_id]  = nq_order

        elif q_id and not sec_id:
            # Format A — standalone question
            q_order_map[q_id] = order

print(f"   ✅ Mapped {len(q_to_section)} questions to sections")
print(f"   ✅ Mapped {len(q_order_map)} question order numbers")
print(f"   ✅ Mapped {len(sec_order_map)} section order numbers")

def upsert_batch(collection, docs, key="_id"):
    if not docs: return
    ops = [
        UpdateOne({key: d[key]}, {"$set": d}, upsert=True)
        for d in docs
    ]
    collection.bulk_write(ops, ordered=False)

# ══════════════════════════════════════════════════════════════════════════
# TABLE 1 — flat_checklists
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_checklists...")
batch = []
for c in source.checklists.find({}):
    cid = str(c["_id"])
    tag_names = [tags_map.get(str(t)) for t in c.get("tagIds", []) if t]
    creator   = resolve_user(c.get("createdBy", ""))
    batch.append({
        "_id":             cid,
        "type":            "checklists",
        "title":           c.get("title"),
        "description":     c.get("description"),
        "version":         c.get("version"),
        "isTemplate":      c.get("isTemplate", False),
        "isLibrary":       c.get("isLibrary", False),
        "isLatest":        c.get("isLatest"),
        "tenantId":        c.get("tenantId"),
        "createdById":     c.get("createdBy"),
        "createdByName":   creator.get("name"),
        "createdByEmail":  creator.get("email"),
        "tagIds":          [str(t) for t in c.get("tagIds", []) if t],
        "tagNames":        [t for t in tag_names if t],
        "isDeleted":       c.get("isDeleted", False),
        "deletedAt":       ts(c.get("deletedAt")),
        "createdAt":       ts(c.get("createdAt")),
        "updatedAt":       ts(c.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_checklists, batch)
        batch = []
upsert_batch(target.flat_checklists, batch)
print(f"   ✅ flat_checklists: {target.flat_checklists.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 2 — flat_sections
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_sections...")
batch = []
for s in source.sections.find({}):
    sid = str(s["_id"])
    batch.append({
        "_id":           sid,
        "type":          "sections",
        "checklistId":   oid(s.get("checklistId")),
        "title":         s.get("title"),
        "description":   s.get("description"),
        "isMandatory":   s.get("isMandatory", False),
        "orderNumber":   sec_order_map.get(sid) or s.get("orderNumber"),
        "version":       s.get("version"),
        "isDeleted":     s.get("isDeleted", False),
        "deletedAt":     ts(s.get("deletedAt")),
        "createdAt":     ts(s.get("createdAt")),
        "updatedAt":     ts(s.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_sections, batch)
        batch = []
upsert_batch(target.flat_sections, batch)
print(f"   ✅ flat_sections: {target.flat_sections.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 3 — flat_questions
# (sectionId injected from q_to_section map, orderNumber from q_order_map)
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_questions...")
batch = []
for q in source.questions.find({}):
    qid = str(q["_id"])
    rt  = response_types.get(oid(q.get("responseType")), {})
    creator = resolve_user(q.get("createdBy", ""))
    batch.append({
        "_id":                  qid,
        "type":                 "questions",
        "checklistId":          oid(q.get("checklistId")),
        "sectionId":            q_to_section.get(qid),          # ← resolved
        "questionText":         q.get("questionText"),
        "responseTypeId":       oid(q.get("responseType")),
        "responseTypeName":     rt.get("displayName"),          # ← resolved
        "responseTypeKey":      rt.get("type"),                 # ← resolved
        "orderNumber":          q_order_map.get(qid) or q.get("orderNumber"),  # ← resolved
        "allowMultiple":        q.get("allowMultiple", False),
        "isMandatory":          q.get("isMandatory", False),
        "tenantId":             q.get("tenantId"),
        "createdById":          q.get("createdBy"),
        "createdByName":        creator.get("name"),
        "version":              q.get("version"),
        "isDeleted":            q.get("isDeleted", False),
        "deletedAt":            ts(q.get("deletedAt")),
        "createdAt":            ts(q.get("createdAt")),
        "updatedAt":            ts(q.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_questions, batch)
        batch = []
upsert_batch(target.flat_questions, batch)
print(f"   ✅ flat_questions: {target.flat_questions.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 4 — flat_response_options
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_response_options...")
batch = []
for r in source.responsevalues.find({}):
    batch.append({
        "_id":                  str(r["_id"]),
        "type":                 "responsevalues",
        "questionId":           oid(r.get("questionId")),
        "responseValue":        r.get("responseValue"),
        "enableScore":          r.get("enableScore", False),
        "scoreValue":           r.get("scoreValue"),
        "enforceIssue":         r.get("enforceIssue", False),
        "enforceObservation":   r.get("enforceObservation", False),
        "enforceImage":         r.get("enforceImage", False),
        "responseColor":        r.get("responseColor"),
        "version":              r.get("version"),
        "isDeleted":            r.get("isDeleted", False),
        "deletedAt":            ts(r.get("deletedAt")),
        "createdAt":            ts(r.get("createdAt")),
        "updatedAt":            ts(r.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_response_options, batch)
        batch = []
upsert_batch(target.flat_response_options, batch)
print(f"   ✅ flat_response_options: {target.flat_response_options.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 5 — flat_inspections
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_inspections...")
# Pre-load checklist titles for joining
checklist_titles = {
    str(c["_id"]): c.get("title")
    for c in source.checklists.find({}, {"title": 1})
}
batch = []
for i in source.inspections.find({}):
    status_id  = oid(i.get("status"))
    status_obj = inspection_statuses.get(status_id, {})
    creator    = resolve_user(i.get("createdBy", ""))
    cl_id      = oid(i.get("checklistId"))
    tag_names  = [tags_map.get(str(t)) for t in i.get("tagIds", []) if t]
    batch.append({
        "_id":                  str(i["_id"]),
        "type":                 "inspections",
        "title":                i.get("title"),
        "checklistId":          cl_id,
        "checklistTitle":       checklist_titles.get(cl_id),   # ← resolved
        "scheduleId":           oid(i.get("scheduleId")),
        "statusId":             status_id,
        "statusDisplayName":    status_obj.get("displayName"), # ← resolved
        "statusKey":            status_obj.get("status"),      # ← resolved
        "tagIds":               [str(t) for t in i.get("tagIds", []) if t],
        "tagNames":             [t for t in tag_names if t],
        "tenantId":             i.get("tenantId"),
        "createdById":          i.get("createdBy"),
        "createdByName":        creator.get("name"),
        "createdByEmail":       creator.get("email"),
        "isDeleted":            i.get("isDeleted", False),
        "deletedAt":            ts(i.get("deletedAt")),
        "createdAt":            ts(i.get("createdAt")),
        "updatedAt":            ts(i.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_inspections, batch)
        batch = []
upsert_batch(target.flat_inspections, batch)
print(f"   ✅ flat_inspections: {target.flat_inspections.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 6 — flat_executions
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_executions...")
batch = []
for e in source.executions.find({}):
    qid     = oid(e.get("questionId"))
    creator = resolve_user(e.get("createdBy", ""))
    batch.append({
        "_id":              str(e["_id"]),
        "type":             "executions",
        "inspectionId":     oid(e.get("inspectionId")),
        "checklistId":      oid(e.get("checklistId")),
        "questionId":       qid,
        "sectionId":        q_to_section.get(qid),             # ← resolved
        "tenantId":         e.get("tenantId"),
        "createdById":      e.get("createdBy"),
        "createdByName":    creator.get("name"),
        "isDeleted":        e.get("isDeleted", False),
        "createdAt":        ts(e.get("createdAt")),
        "updatedAt":        ts(e.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_executions, batch)
        batch = []
upsert_batch(target.flat_executions, batch)
print(f"   ✅ flat_executions: {target.flat_executions.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 7 — flat_response_histories
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_response_histories...")
batch = []
for rh in source.responsehistories.find({}):
    qid = oid(rh.get("questionId"))
    batch.append({
        "_id":              str(rh["_id"]),
        "type":             "responsehistories",
        "executionId":      oid(rh.get("executionId")),
        "questionId":       qid,
        "sectionId":        q_to_section.get(qid),             # ← resolved
        "responseIds":      [oid(r) for r in (rh.get("responseIds") or [])],
        "responseValues":   rh.get("responseValues") or [],
        "isDeleted":        rh.get("isDeleted", False),
        "createdAt":        ts(rh.get("createdAt")),
        "updatedAt":        ts(rh.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_response_histories, batch)
        batch = []
upsert_batch(target.flat_response_histories, batch)
print(f"   ✅ flat_response_histories: {target.flat_response_histories.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 8 — flat_tasks
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
    batch.append({
        "_id":                  str(t["_id"]),
        "type":                 "tasks",
        "title":                t.get("title"),
        "description":          t.get("description"),
        "inspectionId":         oid(t.get("inspectionId")),
        "executionId":          oid(t.get("executionId")),
        "questionId":           qid,
        "sectionId":            q_to_section.get(qid),         # ← resolved
        "observationId":        oid(t.get("observationId")),
        "statusId":             status_id,
        "statusDisplayName":    status_obj.get("displayName"), # ← resolved
        "statusKey":            status_obj.get("status"),      # ← resolved
        "tagIds":               [str(tid) for tid in t.get("tagIds", []) if tid],
        "tagNames":             [n for n in tag_names if n],
        "assignedToId":         t.get("assignedTo"),
        "assignedToName":       assigned.get("name"),
        "assignedToEmail":      assigned.get("email"),
        "createdById":          t.get("createdBy"),
        "createdByName":        creator.get("name"),
        "tenantId":             t.get("tenantId"),
        "inspectionCompleted":  t.get("inspectionCompleted", False),
        "isDeleted":            t.get("isDeleted", False),
        "createdAt":            ts(t.get("createdAt")),
        "updatedAt":            ts(t.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_tasks, batch)
        batch = []
upsert_batch(target.flat_tasks, batch)
print(f"   ✅ flat_tasks: {target.flat_tasks.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 9 — flat_task_observations
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_task_observations...")
batch = []
for o in source.taskobservations.find({}):
    qid     = oid(o.get("questionId"))
    creator = resolve_user(o.get("createdBy", ""))
    batch.append({
        "_id":              str(o["_id"]),
        "type":             "taskobservations",
        "taskId":           oid(o.get("taskId")),
        "executionId":      oid(o.get("executionId")),
        "questionId":       qid,
        "sectionId":        q_to_section.get(qid),             # ← resolved
        "description":      o.get("description"),
        "isIssue":          o.get("isIssue", False),
        "evidence":         o.get("evidence", False),
        "hasAttachment":    o.get("hasAttachment", False),
        "attachmentCount":  o.get("attachmentCount", 0),
        "isResolved":       o.get("isResolved", False),
        "createdById":      o.get("createdBy"),
        "createdByName":    creator.get("name"),
        "tenantId":         o.get("tenantId"),
        "isDeleted":        o.get("isDeleted", False),
        "createdAt":        ts(o.get("createdAt")),
        "updatedAt":        ts(o.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_task_observations, batch)
        batch = []
upsert_batch(target.flat_task_observations, batch)
print(f"   ✅ flat_task_observations: {target.flat_task_observations.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 10 — flat_inspection_observations
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_inspection_observations...")
batch = []
for o in source.inspectionobservations.find({}):
    qid     = oid(o.get("questionId"))
    creator = resolve_user(o.get("createdBy", ""))
    batch.append({
        "_id":              str(o["_id"]),
        "type":             "inspectionobservations",
        "executionId":      oid(o.get("executionId")),
        "questionId":       qid,
        "sectionId":        q_to_section.get(qid),             # ← resolved
        "description":      o.get("description"),
        "isIssue":          o.get("isIssue", False),
        "evidence":         o.get("evidence", False),
        "hasAttachment":    o.get("hasAttachment", False),
        "attachmentCount":  o.get("attachmentCount", 0),
        "createdById":      o.get("createdBy"),
        "createdByName":    creator.get("name"),
        "tenantId":         o.get("tenantId"),
        "isDeleted":        o.get("isDeleted", False),
        "createdAt":        ts(o.get("createdAt")),
        "updatedAt":        ts(o.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_inspection_observations, batch)
        batch = []
upsert_batch(target.flat_inspection_observations, batch)
print(f"   ✅ flat_inspection_observations: {target.flat_inspection_observations.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# TABLE 11 — flat_reports
# ══════════════════════════════════════════════════════════════════════════
print("\n🗂  Building flat_reports...")
inspection_docs = {
    str(i["_id"]): {
        "title": i.get("title"),
        "statusId": oid(i.get("status")),
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
        "_id":                      str(r["_id"]),
        "type":                     "reports",
        "reportName":               r.get("reportName"),
        "reportNumber":             r.get("reportNumber"),
        "reportDate":               ts(r.get("reportDate")),
        "inspectionId":             ins_id,
        "inspectionTitle":          ins_obj.get("title"),           # ← resolved
        "inspectionChecklistId":    ins_obj.get("checklistId"),     # ← resolved
        "inspectionStatusName":     s_obj.get("displayName"),       # ← resolved
        "tenantId":                 r.get("tenantId"),
        "isDeleted":                r.get("isDeleted", False),
        "inspectionUpdatedAt":      ts(r.get("inspectionUpdatedAt")),
        "createdAt":                ts(r.get("createdAt")),
        "updatedAt":                ts(r.get("updatedAt")),
    })
    if len(batch) >= BATCH_SIZE:
        upsert_batch(target.flat_reports, batch)
        batch = []
upsert_batch(target.flat_reports, batch)
print(f"   ✅ flat_reports: {target.flat_reports.count_documents({})} docs")

# ══════════════════════════════════════════════════════════════════════════
# STEP FINAL — Consolidate all flat collections into ONE collection
# ══════════════════════════════════════════════════════════════════════════
FLAT_COLLECTIONS = [
    "flat_checklists", "flat_sections", "flat_questions",
    "flat_response_options", "flat_inspections", "flat_executions",
    "flat_response_histories", "flat_tasks",
    "flat_task_observations", "flat_inspection_observations", "flat_reports"
]

CONSOLIDATED = "flat_entities"

print("\n🔀 Consolidating all flat collections → flat_entities...")
target[CONSOLIDATED].drop()   # fresh start on every run

total_inserted = 0
for col_name in FLAT_COLLECTIONS:
    docs = list(target[col_name].find({}))
    if docs:
        # Strip MongoDB's internal _id to avoid conflicts since _id is already a string
        target[CONSOLIDATED].insert_many(docs, ordered=False)
        total_inserted += len(docs)
        print(f"   ✅ {col_name:<35} → {len(docs):>6} docs merged")

print("\n" + "=" * 60)
print(f"🎉 FLAT SCHEMA BUILD COMPLETE → {TARGET_HOST}/{TARGET_DB}")
print("=" * 60)
print(f"   {'flat_entities (consolidated)':<35} {target[CONSOLIDATED].count_documents({}):>6} docs")

print("\n📋 Diagnostic checks:")
print(f"   Questions with sectionId resolved : {target[CONSOLIDATED].count_documents({'type': 'questions', 'sectionId': {'$ne': None}})}")
print(f"   Questions without sectionId       : {target[CONSOLIDATED].count_documents({'type': 'questions', 'sectionId': None})}")
print(f"   Executions with sectionId resolved: {target[CONSOLIDATED].count_documents({'type': 'executions', 'sectionId': {'$ne': None}})}")
print(f"   Tasks with status resolved        : {target[CONSOLIDATED].count_documents({'type': 'tasks', 'statusDisplayName': {'$ne': None}})}")
print(f"   Inspections with status resolved  : {target[CONSOLIDATED].count_documents({'type': 'inspections', 'statusDisplayName': {'$ne': None}})}")

print("\n📊 Breakdown by type inside flat_entities:")
for type_val in ["checklists","sections","questions","responsevalues","inspections",
                 "executions","responsehistories","tasks","taskobservations",
                 "inspectionobservations","reports"]:
    count = target[CONSOLIDATED].count_documents({"type": type_val})
    print(f"   type={type_val:<30} {count:>6} docs")

# ── Create indexes for fast type-based filtering ──────────────────────────
print("\n🔧 Creating indexes on flat_entities...")
target[CONSOLIDATED].create_index("type")
target[CONSOLIDATED].create_index([("type", 1), ("tenantId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("isDeleted", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("checklistId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("inspectionId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("questionId", 1)])
target[CONSOLIDATED].create_index([("type", 1), ("sectionId", 1)])
print("   ✅ Indexes created")