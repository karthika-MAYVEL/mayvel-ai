# Ask Seyo — Inspection Agent Schema Reference

**Database:** `seyo-development`  
**Scope:** Inspection domain only — collections, fields, relationships, and query patterns relevant to the `inspection_agent`.  
**Schema Version:** 2.0  

> This file is the single source of truth injected into the `{SCHEMA}` placeholder for the Inspection Agent's system prompt. Do NOT include unrelated collections (workflows, dashboards, metrics, etc.).

---

## Tenancy & Soft-Delete Conventions

- `tenantId` — String. Always present. Use placeholder `"{tenantId}"`.
- `isDeleted` — Boolean. Always present on domain collections.
- **Default filter rule:** `{ tenantId: "{tenantId}", isDeleted: false }` unless the user explicitly asks for deleted/archived records.
- Status collections (`inspectionstatuses`, `taskstatuses`) do **NOT** carry `tenantId`.

---

## Relationship Chain (Inspection Domain)

```
checklists ──────────────────────────────────────────┐
      │                                               │
      ▼                                               ▼
inspections  →  inspectionstatuses (status lookup)   │
      │                                               │
      ▼                                               │
executions ──────────────────────────────────────────┘
      │               │                    │
      ▼               ▼                    ▼
inspectionobservations  responsehistories  tasks
                                            │
                                            ▼
                                       taskstatuses (status lookup)
                                       taskobservations
```

Cross-cutting:
- `users` — referenced by `createdBy` / `assignedTo` (String, NOT ObjectId)
- `tags` — referenced by `checklists.tagIds[]` and `inspections.tagIds[]`
- `schedules` — optionally linked to `inspections.scheduleId`

---

## Collections

---

### `inspections` *(primary collection)*

**Description:** Main inspection instances. Each inspection runs against one checklist template and tracks status, assignments, scheduling, and workflow.

| Field              | Type             | Description                                                      |
|--------------------|------------------|------------------------------------------------------------------|
| `_id`              | ObjectId         | Primary key                                                      |
| `__v`              | Number           | Mongoose version key (omit from projections)                     |
| `title`            | String           | Inspection name/title                                            |
| `checklistId`      | ObjectId         | → `checklists._id` — Checklist template used                     |
| `status`           | ObjectId         | → `inspectionstatuses._id` — Current status                      |
| `assignedTo`       | String, Null     | → `users.id` — User assigned to execute the inspection           |
| `createdBy`        | String           | → `users.id` — User who created the inspection                   |
| `workflowId`       | ObjectId, Null   | → `workflows._id` — Optional linked workflow                     |
| `scheduleId`       | ObjectId, Null   | → `schedules._id` — Optional schedule                            |
| `tagIds`           | Array            | → `tags._id[]` — Associated tag IDs                              |
| `tags`             | Array            | Denormalized tag data (available inline, no join needed)         |
| `executionTimings` | Array            | Array of timing objects (start/end per execution phase)          |
| `tenantId`         | String           | Multi-tenant identifier                                          |
| `isDeleted`        | Boolean          | Soft delete flag                                                 |
| `deletedAt`        | Date             | Soft delete timestamp                                            |
| `createdAt`        | Date             | Creation timestamp                                               |
| `updatedAt`        | Date             | Last update timestamp                                            |

**Key relationships:**
- Has many → `executions` (via `executions.inspectionId`)
- Has many → `tasks` (via `tasks.inspectionId`)
- Has many → `inspectionworkflowordermaps`
- Status resolved via `$lookup` on `inspectionstatuses` (field: `status`)

**Status field:** `status` (ObjectId → `inspectionstatuses._id`)  
**User fields:** `assignedTo` (default), `createdBy` (if creator intent)

---

### `inspectionstatuses` *(status lookup)*

**Description:** Lookup collection for all valid inspection status values.

| Field         | Type     | Description                          |
|---------------|----------|--------------------------------------|
| `_id`         | ObjectId | Primary key (matches `inspections.status`) |
| `displayName` | String   | Human-readable label, e.g. "In Progress" |
| `status`      | String   | Status code — use this for filtering  |
| `isDeleted`   | Boolean  | Soft delete flag                     |
| `createdAt`   | Date     | Creation timestamp                   |
| `updatedAt`   | Date     | Last update timestamp                |

**Valid `status` codes:**
| Code          | Display Name  | Meaning                        |
|---------------|---------------|--------------------------------|
| `yetToStart`  | Yet to Start  | Created but not begun          |
| `inProgress`  | In Progress   | Actively being executed        |
| `completed`   | Completed     | All executions done            |

**Join pattern:**
```json
{
  "$lookup": {
    "from": "inspectionstatuses",
    "localField": "status",
    "foreignField": "_id",
    "as": "st"
  }
}
```
Then: `{ "$unwind": "$st" }` and filter `{ "st.isDeleted": { "$in": [false, null] } }`.  
Project as: `"statusName": "$st.displayName"`. Never expose `st._id` or raw `status` ObjectId.

---

### `checklists` *(referenced by inspections)*

**Description:** Checklist templates. An inspection is always linked to one checklist. Use for joins when the user asks about inspection names alongside checklist titles.

| Field         | Type     | Description                                   |
|---------------|----------|-----------------------------------------------|
| `_id`         | ObjectId | Primary key (matches `inspections.checklistId`) |
| `title`       | String   | Checklist name/title                          |
| `description` | String   | Checklist description                         |
| `isTemplate`  | Boolean  | True if this is a reusable template           |
| `isLibrary`   | Boolean  | True if stored in the library                 |
| `isLatest`    | Boolean  | Latest version flag                           |
| `createdBy`   | String   | → `users.id`                                  |
| `tagIds`      | Array    | → `tags._id[]`                                |
| `tags`        | Array    | Denormalized tag data                         |
| `tenantId`    | String   | Multi-tenant identifier                       |
| `isDeleted`   | Boolean  | Soft delete flag                              |
| `createdAt`   | Date     | Creation timestamp                            |
| `updatedAt`   | Date     | Last update timestamp                         |

**Join pattern (from inspections):**
```json
{
  "$lookup": {
    "from": "checklists",
    "localField": "checklistId",
    "foreignField": "_id",
    "as": "checklist"
  }
}
```

---

### `executions` *(inspection execution instances)*

**Description:** Each row is one question answered within an inspection run. Links inspections → checklists → questions.

| Field          | Type     | Description                                              |
|----------------|----------|----------------------------------------------------------|
| `_id`          | ObjectId | Primary key                                              |
| `inspectionId` | ObjectId | → `inspections._id`                                      |
| `checklistId`  | ObjectId | → `checklists._id`                                       |
| `questionId`   | ObjectId | → `questions._id` — The specific question being answered |
| `createdBy`    | String   | → `users.id` — User who executed                         |
| `tenantId`     | String   | Multi-tenant identifier                                  |
| `isDeleted`    | Boolean  | Soft delete flag                                         |
| `createdAt`    | Date     | Creation timestamp                                       |
| `updatedAt`    | Date     | Last update timestamp                                    |

**Relationships:**
- Has many → `inspectionobservations` (via `inspectionobservations.executionId`)
- Has many → `responsehistories` (via `responsehistories.executionId`)

---

### `inspectionobservations` *(issues raised during inspection)*

**Description:** Observations or issues recorded against a specific question during an execution. Can spawn tasks.

| Field             | Type          | Description                                          |
|-------------------|---------------|------------------------------------------------------|
| `_id`             | ObjectId      | Primary key                                          |
| `executionId`     | ObjectId      | → `executions._id`                                   |
| `questionId`      | ObjectId      | → `questions._id`                                    |
| `description`     | String        | Observation description / notes                      |
| `isIssue`         | Boolean       | True if flagged as an issue                          |
| `evidence`        | Boolean       | True if evidence is required                         |
| `hasAttachment`   | Boolean, Null | True if files are attached                           |
| `attachmentCount` | Number        | Number of attached files                             |
| `assignedTo`      | String        | → `users.id` — User assigned to resolve              |
| `createdBy`       | String        | → `users.id` — User who recorded the observation     |
| `tenantId`        | String        | Multi-tenant identifier                              |
| `isDeleted`       | Boolean       | Soft delete flag                                     |
| `createdAt`       | Date          | Creation timestamp                                   |
| `updatedAt`       | Date          | Last update timestamp                                |

---

### `tasks` *(action items raised from inspections)*

**Description:** Corrective action tasks linked to an inspection and optionally to an execution, question, or observation.

| Field                 | Type         | Description                                            |
|-----------------------|--------------|--------------------------------------------------------|
| `_id`                 | ObjectId     | Primary key                                            |
| `title`               | String       | Task name/title                                        |
| `description`         | String       | Task details                                           |
| `inspectionId`        | ObjectId     | → `inspections._id` — Source inspection                |
| `executionId`         | ObjectId     | → `executions._id` — Source execution                  |
| `observationId`       | ObjectId     | → `observations._id` — Source observation              |
| `questionId`          | ObjectId     | → `questions._id` — Related question                   |
| `status`              | ObjectId     | → `taskstatuses._id` — Current task status             |
| `assignedTo`          | String, Null | → `users.id`                                           |
| `createdBy`           | String       | → `users.id`                                           |
| `referenceId`         | String       | Auto-generated human-readable reference (e.g. T-0023) |
| `referenceName`       | String       | Human-readable reference label                         |
| `inspectionCompleted` | Boolean      | True if the parent inspection is complete              |
| `tagIds`              | Array        | → `tags._id[]`                                         |
| `tenantId`            | String       | Multi-tenant identifier                                |
| `isDeleted`           | Boolean      | Soft delete flag                                       |
| `createdAt`           | Date         | Creation timestamp                                     |
| `updatedAt`           | Date         | Last update timestamp                                  |

**Status field:** `status` (ObjectId → `taskstatuses._id`)

---

### `taskstatuses` *(status lookup for tasks)*

**Description:** Lookup collection for task status values.

| Field         | Type     | Description                          |
|---------------|----------|--------------------------------------|
| `_id`         | ObjectId | Primary key (matches `tasks.status`) |
| `displayName` | String   | Human-readable label                 |
| `status`      | String   | Status code — use this for filtering |
| `isDeleted`   | Boolean  | Soft delete flag                     |
| `createdAt`   | Date     | Creation timestamp                   |
| `updatedAt`   | Date     | Last update timestamp                |

**Valid `status` codes:**
| Code         | Display Name | Meaning                   |
|--------------|--------------|---------------------------|
| `yetToStart` | Yet to Start | Task created, not started |
| `inProgress` | In Progress  | Being worked on           |
| `completed`  | Completed    | Resolved/done             |

**Join pattern (from tasks):**
```json
{
  "$lookup": {
    "from": "taskstatuses",
    "localField": "status",
    "foreignField": "_id",
    "as": "st"
  }
}
```

---

### `taskobservations` *(follow-up notes on tasks)*

**Description:** Observations attached to tasks (follow-up commentary, evidence).

| Field             | Type         | Description                            |
|-------------------|--------------|----------------------------------------|
| `_id`             | ObjectId     | Primary key                            |
| `taskId`          | ObjectId     | → `tasks._id`                          |
| `executionId`     | ObjectId     | → `executions._id`                     |
| `observationId`   | ObjectId     | → `observations._id`                   |
| `questionId`      | ObjectId     | → `questions._id`                      |
| `description`     | String       | Observation notes                      |
| `evidence`        | Boolean      | Evidence required flag                 |
| `hasAttachment`   | Boolean      | Attachment present flag                |
| `attachmentCount` | Number, Null | Number of attachments                  |
| `createdBy`       | String       | → `users.id`                           |
| `tenantId`        | String       | Multi-tenant identifier                |
| `isDeleted`       | Boolean      | Soft delete flag                       |
| `createdAt`       | Date         | Creation timestamp                     |
| `updatedAt`       | Date         | Last update timestamp                  |

---

### `responsehistories` *(answers recorded per execution)*

**Description:** Stores the actual answers submitted for each question in an execution.

| Field          | Type     | Description                                         |
|----------------|----------|-----------------------------------------------------|
| `_id`          | ObjectId | Primary key                                         |
| `executionId`  | ObjectId | → `executions._id`                                  |
| `inspectionId` | ObjectId | → `inspections._id`                                 |
| `checklistId`  | ObjectId | → `checklists._id`                                  |
| `questionId`   | ObjectId | → `questions._id`                                   |
| `responseValues` | Array  | → `responsevalues._id[]` — Selected response values |
| `tenantId`     | String   | Multi-tenant identifier                             |
| `isDeleted`    | Boolean  | Soft delete flag                                    |
| `createdAt`    | Date     | Creation timestamp                                  |
| `updatedAt`    | Date     | Last update timestamp                               |

---

### `inspectioncounters` *(utility — reference ID generation)*

**Description:** Generates sequential inspection reference IDs per tenant per year. Read-only utility; rarely queried directly by the agent.

| Field      | Type     | Description               |
|------------|----------|---------------------------|
| `_id`      | ObjectId | Primary key               |
| `tenantId` | String   | Multi-tenant identifier   |
| `year`     | Number   | Year for the counter      |
| `seq`      | Number   | Current sequence number   |

---

### `inspectionworkflowordermaps` *(workflow activity ordering per inspection)*

**Description:** Maps the ordered list of workflow activities for a specific inspection instance.

| Field          | Type     | Description                              |
|----------------|----------|------------------------------------------|
| `_id`          | ObjectId | Primary key                              |
| `inspectionId` | ObjectId | → `inspections._id`                      |
| `workflowId`   | ObjectId | → `workflows._id`                        |
| `activities`   | Array    | → `activities._id[]` — Ordered activity list |
| `isDeleted`    | Boolean  | Soft delete flag                         |
| `createdAt`    | Date     | Creation timestamp                       |
| `updatedAt`    | Date     | Last update timestamp                    |

---

## Field Rules Summary

| Rule | Detail |
|------|--------|
| `users.id` is a **String**, not ObjectId | Always join `assignedTo`/`createdBy` → `users.id` (String equality) |
| Status join always needs `$unwind` | After `$lookup` on status collection, always `$unwind` |
| Filter status docs | `{ "st.isDeleted": { "$in": [false, null] } }` |
| Filter by status | Use `st.status` (code) preferred over `st.displayName` |
| Never expose raw status ObjectId | Always project `statusName: "$st.displayName"` |
| `tags` available inline on `inspections` | No join needed for tag display; `tagIds` needed for tag filtering |
| `executionTimings` is an array of objects | Do not attempt to flatten unless specifically queried |

---

## Common Query Patterns

### Get Inspection with Status + Checklist Title
```javascript
db.inspections.aggregate([
  { $match: { tenantId: "{tenantId}", assignedTo: "{userId}", isDeleted: false } },
  { $lookup: { from: "inspectionstatuses", localField: "status", foreignField: "_id", as: "st" } },
  { $unwind: { path: "$st", preserveNullAndEmptyArrays: true } },
  { $match: { "st.isDeleted": { $in: [false, null] } } },
  { $lookup: { from: "checklists", localField: "checklistId", foreignField: "_id", as: "checklist" } },
  { $unwind: { path: "$checklist", preserveNullAndEmptyArrays: true } },
  {
    $project: {
      _id: 0,
      inspectionId: "$_id",
      title: 1,
      createdAt: 1,
      statusName: "$st.displayName",
      checklistTitle: "$checklist.title"
    }
  }
])
```

### Get Inspections with a Specific Status
```javascript
db.inspections.aggregate([
  { $match: { tenantId: "{tenantId}", assignedTo: "{userId}", isDeleted: false } },
  { $lookup: { from: "inspectionstatuses", localField: "status", foreignField: "_id", as: "st" } },
  { $unwind: "$st" },
  { $match: { "st.isDeleted": { $in: [false, null] }, "st.status": "inProgress" } },
  { $project: { _id: 0, inspectionId: "$_id", title: 1, createdAt: 1, statusName: "$st.displayName" } }
])
```

### Get Tasks for an Inspection
```javascript
db.tasks.aggregate([
  { $match: { tenantId: "{tenantId}", inspectionId: <ObjectId>, isDeleted: false } },
  { $lookup: { from: "taskstatuses", localField: "status", foreignField: "_id", as: "st" } },
  { $unwind: { path: "$st", preserveNullAndEmptyArrays: true } },
  { $match: { "st.isDeleted": { $in: [false, null] } } },
  {
    $project: {
      _id: 0,
      taskId: "$_id",
      title: 1,
      referenceId: 1,
      createdAt: 1,
      statusName: "$st.displayName"
    }
  }
])
```

### Get Observations for an Inspection (via Executions)
```javascript
db.inspectionobservations.aggregate([
  { $match: { tenantId: "{tenantId}", isDeleted: false } },
  {
    $lookup: {
      from: "executions",
      localField: "executionId",
      foreignField: "_id",
      as: "execution"
    }
  },
  { $unwind: "$execution" },
  { $match: { "execution.inspectionId": <ObjectId> } },
  {
    $project: {
      _id: 0,
      observationId: "$_id",
      description: 1,
      isIssue: 1,
      hasAttachment: 1,
      createdAt: 1
    }
  }
])
```

---

## Index Reference (for query planning)

```javascript
// Core tenant + soft delete
{ tenantId: 1, isDeleted: 1 }

// inspections
{ "inspections.checklistId": 1 }
{ "inspections.status": 1 }
{ "inspections.assignedTo": 1, isDeleted: 1 }
{ "inspections.createdBy": 1 }
{ "inspections.createdAt": 1 }

// executions
{ "executions.inspectionId": 1 }
{ "executions.checklistId": 1 }
{ "executions.questionId": 1 }

// tasks
{ "tasks.inspectionId": 1 }
{ "tasks.status": 1 }
{ "tasks.assignedTo": 1, isDeleted: 1 }

// inspectionobservations
{ "inspectionobservations.executionId": 1 }
{ "inspectionobservations.questionId": 1 }
```

---

*End of Inspection Agent Schema Reference*
