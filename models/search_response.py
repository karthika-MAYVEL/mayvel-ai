from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

class SearchResponse(BaseModel):
    """
    Search response payload (Pydantic: results, metadata, coverage)
    """
    results: List[Any] = Field(default_factory=list, description="The list of results matching the query.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata associated with the search response.")
    coverage: Optional[Dict[str, Any]] = Field(None, description="Information about the coverage of the search.")
