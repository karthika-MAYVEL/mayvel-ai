# agents/sub_agents/inspection_group_agent.py
# InspectionGroupAgent: T2 domain agent for the unified INSPECTION group.
# Owns the full inspection lifecycle:
#   inspection · checklist · section · question · execution ·
#   responseHistory · inspectionObservation · task · taskObservation · report
# Version: v1.1 (aligned to inspection_agent_v2.docx)

from application.agents.sub_agents.domain_base_agent import DomainBaseAgent


class InspectionGroupAgent(DomainBaseAgent):
    """
    T2 domain agent for the INSPECTION group.

    Handles the full inspection lifecycle in a single LLM call:
    - Content layer:  checklist, section, question
    - Assignment:     inspection
    - Execution:      execution (1 record per question), responseHistory, inspectionObservation
    - Resolution:     task, taskObservation
    - Artifact:       report

    Language routing (critical):
    - "issues" / "problems"    → task ROOT (P5a)
    - "observations" / "notes" → inspectionObservation ROOT (P5b)
    - "responses" / "answers"  → responseHistory ROOT + mandatory dedup (P4)
    - "overdue" / "schedule"   → inspection.scheduleDate filter (P2)

    Key constraints:
    - execution has NO assignedTo; scope via execution → inspection chain.
    - responseHistory ALWAYS requires the 3-stage mandatory dedup block.
    - scheduleDate exists on inspection ONLY — never on task.
    - task.status is a plain String; filter directly, no $lookup.
    - responseValues collection is out of scope — do not fetch it.

    Entity schemas, query patterns (P1–P6), dedup block, and critical
    mistakes are loaded from:
    prompts/sub_agents/groups/inspection.yaml
    """

    group_name = "INSPECTION"

    def get_group_name(self) -> str:
        return self.group_name
