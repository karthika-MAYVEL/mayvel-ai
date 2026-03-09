from pydantic import BaseModel, Field, ConfigDict
from typing import List, Any, Dict, Optional

class GlobalSearchItem(BaseModel):
    """Represents a single search result item (maps to Dart GlobalSearchModel)."""
    id: str = Field(..., alias="_id", description="Unique identifier for the item")
    title: str = Field(..., description="Display title for the item")
    type: str = Field(..., description="The type of the item (e.g., 'checklist', 'inspection')")
    tags: List[str] = Field(default_factory=list, description="Tags associated with the item")
    
    tenant_id: str = Field(..., alias="tenantId", description="ID of the organization or tenant")
    created_by: str = Field(..., alias="createdBy", description="Identifier of the user who created the item")
    created_at: str = Field(..., alias="createdAt", description="ISO timestamp of creation")
    updated_at: str = Field(..., alias="updatedAt", description="ISO timestamp of last update")

    model_config = ConfigDict(populate_by_name=True)


class GlobalSearchMeta(BaseModel):
    """Execution metadata appended to the response for AI transparency and debugging."""
    llm_responses: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="The LLM generation output at each stage/level (e.g., T1 intent, T2 query generation)"
    )
    executed_mongo_query: Optional[Any] = Field(
        default=None, 
        description="The exact MongoDB query or aggregation pipeline that was executed on the database"
    )

    model_config = ConfigDict(populate_by_name=True)

class GlobalSearchData(BaseModel):
    """The nested payload inside the response 'data' field."""
    # Using alias "globalSearchResponse" for standard JSON camelCase output to frontend
    global_search_response: List[GlobalSearchItem] = Field(
        default_factory=list, 
        alias="globalSearchResponse", 
        description="Array of global search results"
    )
    
    model_config = ConfigDict(populate_by_name=True)

class GlobalSearchResponseWrapper(BaseModel):
    """The standard API response wrapper for Global Search."""
    success: bool = Field(default=True, description="Indicates if the request was successful")
    message: str = Field(default="Items retrieved successfully", description="Message describing the outcome")
    
    # The data field now contains the nested object
    data: GlobalSearchData = Field(..., description="Wrapper containing the search results payload")
    
    # Metadata containing token, LLM, and execution traces
    meta: Optional[GlobalSearchMeta] = Field(default=None, description="Metadata containing LLM traces and executed queries")
    
    total_results: int = Field(default=0, alias="totalResults", description="Total number of hits across all pages")

    model_config = ConfigDict(populate_by_name=True)
