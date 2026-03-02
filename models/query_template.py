from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

class QueryTemplate(BaseModel):
    """
    Represents the output from a Sub-agent (QueryTemplate).
    """
    query: str = Field(..., description="The query to execute.")
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Parameters to be substituted in the query.")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata for the query.")
