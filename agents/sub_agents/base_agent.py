from abc import ABC, abstractmethod

class BaseSubAgent(ABC):
    """
    Abstract Base class for all sub-agents.
    """
    @abstractmethod
    def generate_query(self, user_query: str, context: dict = None) -> str:
        """
        Takes the user query and context, generating a JSON MongoDB pipeline.
        """
        pass
