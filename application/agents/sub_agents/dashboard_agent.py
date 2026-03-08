from application.agents.sub_agents.domain_base_agent import DomainBaseAgent

class DashboardGroupAgent(DomainBaseAgent):
    group_name = "DASHBOARD"
    
    def get_group_name(self) -> str:
        return self.group_name
