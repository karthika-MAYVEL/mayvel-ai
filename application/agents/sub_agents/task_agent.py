from application.agents.sub_agents.domain_base_agent import DomainBaseAgent

class TaskGroupAgent(DomainBaseAgent):
    group_name = "TASK"
    
    def get_group_name(self) -> str:
        return self.group_name
