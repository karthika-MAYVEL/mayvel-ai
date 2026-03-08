from application.agents.sub_agents.domain_base_agent import DomainBaseAgent

class WorkflowGroupAgent(DomainBaseAgent):
    group_name = "WORKFLOW"
    
    def get_group_name(self) -> str:
        return self.group_name
