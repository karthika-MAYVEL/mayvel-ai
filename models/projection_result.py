# models/projection_result.py
# Pydantic model for a single projected result group (Projection Agent output).

from pydantic import BaseModel, Field
from typing import Any, Dict, List


class ProjectionResult(BaseModel):
    """
    Output of the Projection Agent for one entity type.

    @param entity_type: SEYO entity type e.g. 'inspection'
    @param count: Number of projected documents
    @param items: Projected result documents (cleaned for API exposure)
    """
    entity_type: str
    count: int = 0
    items: List[Dict[str, Any]] = Field(default_factory=list)
