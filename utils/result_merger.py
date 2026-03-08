from typing import Any, List

class ResultMerger:
    """
    Merges results from multiple channels/sub-agents into a unified projection structure.
    """
    @classmethod
    def merge(cls, results_list: List[Any]) -> Any:
        # Simple placeholder for merging logic.
        merged = []
        for res in results_list:
            if isinstance(res, list):
                merged.extend(res)
            else:
                merged.append(res)
        return merged
