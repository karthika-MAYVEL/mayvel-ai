from pydantic import BaseModel, Field
from typing import List, Optional

class ChannelPlan(BaseModel):
    """
    Represents the Root Agent output (ChannelPlan).
    """
    intent: str = Field(..., description="The detected intent of the user query.")
    channels: List[str] = Field(default_factory=list, description="The channels to activate for the intent.")
    context: Optional[str] = Field(None, description="Context extracted for the plans.")
