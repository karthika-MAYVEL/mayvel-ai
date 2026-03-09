import pytest
from unittest.mock import MagicMock

from presentation.models.routing_decision import RoutingDecision
from presentation.models.query_template import QueryTemplate
from application.agents.sub_agents.inspection_agent import InspectionGroupAgent
from application.agents.sub_agents.task_agent import TaskGroupAgent
from application.agents.sub_agents.workflow_agent import WorkflowGroupAgent
from application.agents.sub_agents.dashboard_agent import DashboardGroupAgent
from application.agents.agent_registry import get_group_agent

class TestGroupAgentRegistry:
    def should_return_inspection_agent_for_inspection_group(self):
        agent = get_group_agent("INSPECTION")
        assert isinstance(agent, InspectionGroupAgent)
        assert agent.get_group_name() == "INSPECTION"

    def should_return_task_agent_for_task_group(self):
        agent = get_group_agent("TASK")
        assert isinstance(agent, TaskGroupAgent)
        assert agent.get_group_name() == "TASK"

    def should_return_workflow_agent_for_workflow_group(self):
        agent = get_group_agent("WORKFLOW")
        assert isinstance(agent, WorkflowGroupAgent)
        assert agent.get_group_name() == "WORKFLOW"

    def should_return_dashboard_agent_for_dashboard_group(self):
        agent = get_group_agent("DASHBOARD")
        assert isinstance(agent, DashboardGroupAgent)
        assert agent.get_group_name() == "DASHBOARD"

    def should_raise_value_error_for_unknown_group(self):
        with pytest.raises(ValueError):
            get_group_agent("UNKNOWN")

class TestPromptLoading:
    def should_load_inspection_prompt(self):
        agent = InspectionGroupAgent()
        prompt = agent._load_prompt("INSPECTION")
        assert "ROLE DECLARATION" in prompt

    def should_load_task_prompt(self):
        agent = TaskGroupAgent()
        prompt = agent._load_prompt("TASK")
        assert "ROLE DECLARATION" in prompt



class TestInspectionAgentGenerate:
    _VALID_RESPONSE = """{
        "query_type": "aggregate",
        "entity_type": "inspection",
        "pipeline": [
            {"$match": {"type": "inspection", "tenantId": "{tenantId}",
                         "assignedTo": "{userId}", "isDeleted": false}},
            {"$project": {"_id": 0, "inspectionId": "$_id"}}
        ],
        "userfield": "assignedTo",
        "placeholders_used": ["tenantId", "userId"],
        "explanation": "List inspections assigned to user."
    }"""

    @pytest.mark.asyncio
    async def should_return_query_template_from_valid_llm_json(self):
        routing = RoutingDecision(
            primary_group="INSPECTION",
            user_scoped=True,
            entity_hint="inspection",
        )
        agent = InspectionGroupAgent()
        agent._llm = MagicMock()
        agent._llm.client = True
        agent._llm.generate_json = MagicMock(return_value=self._VALID_RESPONSE)

        template = await agent.generate(
            routing=routing,
            user_query="Show my inspections",
            tenant_id="t1",
            user_id="u1",
        )

        assert template.query_type == "aggregate"
        assert template.entity_type == "inspection"
        assert template.userfield == "assignedTo"
