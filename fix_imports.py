import os
import re

replacements = [
    (r"from models(\.| )", r"from api.models\1"),
    (r"import api.models as models\b", r"import api.models as models"),
    (r"from core\.logger", r"from utils.logger"),
    (r"from core\.result_merger", r"from utils.result_merger"),
    (r"from core\.query_assembler", r"from utils.query_assembler"),
    (r"from core\.time_resolver", r"from utils.time_resolver"),
    (r"from core\.placeholder_resolver", r"from utils.placeholder_resolver"),
    (r"from core\.executor", r"from infrastructure.database.executor"),
    (r"from infrastructure\.database ", r"from infrastructure.database.database "),
    (r"from infrastructure.llm_sdk", r"from infrastructure.llm_sdk"),
    (r"import infrastructure.llm_sdk as llm_sdk\b", r"import infrastructure.llm_sdk as llm_sdk"),
    (r"from agents\.sub_agents", r"from application.agents.sub_agents"),
    (r"from agents\.agent_registry", r"from application.agents.agent_registry"),
    (r"from agents\.root_agent", r"from application.agents.root_agent"),
    (r"from core\.orchestrator", r"from application.orchestrators.query_orchestrator"),
    (r"from application\.search_service", r"from application.services.search_service"),
    (r"from application.orchestrators.query_orchestrator ", r"from application.orchestrators.query_orchestrator "), # Some possible fallback
]

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    new_content = content
    for old, new in replacements:
        new_content = re.sub(old, new, new_content)

    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for root, _, files in os.walk('.'):
    if '.git' in root or 'venv' in root or '__pycache__' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))

