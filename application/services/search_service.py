from application.orchestrator import SearchOrchestrator
from application.middleware.executor import QueryExecutor
from application.services.synthesizer import ResponseSynthesizer
from infrastructure.database.mongo import DatabaseConnector
from core.logger import get_app_logger

logger = get_app_logger("service.search")

class SearchService:
    """
    The orchestrating service that defines the step-by-step implementation
    of the agentic approach, from the Root Agent all the way to DB execution
    and response synthesis.
    """
    def __init__(self, tenantId: str, userId: str):
        self.tenantId = tenantId
        self.userId = userId
        self.orchestrator = SearchOrchestrator()
        self.executor = QueryExecutor(tenantId=tenantId, userId=userId)
        self.synthesizer = ResponseSynthesizer()

    async def process_query(self, query: str):
        """
        Executes the full conversational search workflow.
        """
        logger.info(f"Starting Search workflow process for query: '{query}'")
        db = DatabaseConnector.get_db()
        
        # Step 1: Orchestrate - Root Agent Planning & Sub-Agent Query Generation
        routing_result = await self.orchestrator.execute_search(query, db=db, executor=self.executor)
        
        if not routing_result["queries"] and not routing_result["messages"]:
            logger.warning(f"Orchestrator returned empty result for query: '{query}'")
            raise ValueError("Could not formulate a query for the given request.")
        
        logger.info(f"Routing intent '{routing_result['intent']}' selected. Found {len(routing_result['queries'])} queries to execute.")

        # Step 2: Ensure Execution Safety & Run Queries
        final_results = {}
        for idx, q_info in enumerate(routing_result["queries"]):
            collection = q_info["collection"]
            raw_pipeline = q_info["pipeline"]
            
            # Sanitize the query
            safe_pipeline = self.executor.prepare_query(raw_pipeline)
            
            # Execute natively on async MongoDB
            logger.info(f"Executing MongoDB pipeline on collection '{collection}'")
            cursor = db[collection].aggregate(safe_pipeline)
            db_res = await cursor.to_list(length=100)
            logger.info(f"Pipeline executed. Fetched {len(db_res)} documents from '{collection}'.")
            
            # Format Object IDs to strings for LLM synthesis serialization
            for doc in db_res:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                    
            final_results[f"query_{idx}_{collection}"] = db_res

        # Step 3: Package Context for the LLM Synthesizer
        synthesis_payload = {
            "intent": routing_result["intent"],
            "router_messages": routing_result["messages"],
            "results": final_results
        }
        
        # Step 4: Return Stream Generator
        return self.synthesizer.synthesize_stream(query, synthesis_payload)
