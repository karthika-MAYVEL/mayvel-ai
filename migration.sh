#!/bin/bash
set -e

# Create required directories
mkdir -p api/routes api/models application/services application/agents/sub_agents application/orchestrators infrastructure/database infrastructure/llm_sdk knowledge/prompts knowledge/schemas config utils tests

# 1. Presentation Layer
[ -f main.py ] && mv main.py api/main.py
[ -f api/routes/ask.py ] && mv api/routes/ask.py api/routes/search_router.py

# Move models into api/models
if [ -d models ] && [ "$(ls -A models)" ]; then
    mv models/* api/models/
    rmdir models || true
fi

# 2. Application Layer
[ -f application/search_service.py ] && mv application/search_service.py application/services/search_service.py
[ -f agents/root_agent.py ] && mv agents/root_agent.py application/agents/root_agent.py
[ -f agents/agent_registry.py ] && mv agents/agent_registry.py application/agents/agent_registry.py
[ -f agents/sub_agents/domain_base_agent.py ] && mv agents/sub_agents/domain_base_agent.py application/agents/sub_agents/domain_base_agent.py

if [ -d agents/sub_agents/groups ] && [ "$(ls -A agents/sub_agents/groups)" ]; then
    mv agents/sub_agents/groups/* application/agents/sub_agents/
fi

rm -rf agents || true

[ -f core/orchestrator.py ] && mv core/orchestrator.py application/orchestrators/query_orchestrator.py

# 3. Infrastructure Layer
[ -f infrastructure/database.py ] && mv infrastructure/database.py infrastructure/database/database.py
[ -f core/executor.py ] && mv core/executor.py infrastructure/database/executor.py

if [ -d llm_sdk ] && [ "$(ls -A llm_sdk)" ]; then
    mv llm_sdk/* infrastructure/llm_sdk/
    rmdir llm_sdk || true
fi

# 4. Utils, Configuration, and other files
[ -f core/logger.py ] && mv core/logger.py utils/logger.py
[ -f core/result_merger.py ] && mv core/result_merger.py utils/result_merger.py
[ -f core/query_assembler.py ] && mv core/query_assembler.py utils/query_assembler.py
[ -f core/time_resolver.py ] && mv core/time_resolver.py utils/time_resolver.py
[ -f core/placeholder_resolver.py ] && mv core/placeholder_resolver.py utils/placeholder_resolver.py

rm -rf core || true

# 5. Clean up old __pycache__ mapping issues via find
find . -type d -name "__pycache__" -exec rm -rf {} +

echo "Migration script completed."
