from pydantic import BaseModel, Field
from typing import Any, Dict, Optional

class ProjectionResult(BaseModel):
    """
    Represents the output from a Projection Agent.
    """
    shaped_response: Any = Field(..., description="The shaped response data.")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata associated with the projection.")
