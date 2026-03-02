import json

class QueryExecutor:
    def __init__(self, tenantId: str, userId: str):
        # We assume these are verified session values from a JWT
        self.tenantId = tenantId
        self.userId = userId

    def _replace_placeholders(self, item):
        """Recursively replace tenant and user placeholders."""
        if isinstance(item, dict):
            new_dict = {}
            for k, v in item.items():
                new_dict[k] = self._replace_placeholders(v)
            return new_dict
        elif isinstance(item, list):
            return [self._replace_placeholders(i) for i in item]
        elif isinstance(item, str):
            res = item.replace("{tenantId}", self.tenantId)
            res = res.replace("{userId}", self.userId)
            return res
        else:
            return item

    def _validate_and_sanitize(self, item):
        """
        Blocks forbidden operators ($where, $function).
        Additionally modifies $match stages to enforce isDeleted: false.
        """
        if isinstance(item, dict):
            new_dict = {}
            for k, v in item.items():
                if k in ["$where", "$function"]:
                    raise ValueError(f"Forbidden operator detected: {k}")
                
                # Enforce isDeleted: false in match stages
                if k == "$match":
                    match_stage = self._validate_and_sanitize(v)
                    if isinstance(match_stage, dict):
                        match_stage["isDeleted"] = False
                    new_dict[k] = match_stage
                else:
                    new_dict[k] = self._validate_and_sanitize(v)
            return new_dict
        elif isinstance(item, list):
            return [self._validate_and_sanitize(i) for i in item]
        else:
            return item

    def prepare_query(self, pipeline: list) -> list:
        """
        Takes a raw generated pipeline.
        1. Injects session values.
        2. Validates operators and enforces soft-deletion check.
        """
        try:
            # 1. Replace placeholders
            pipeline = self._replace_placeholders(pipeline)
            # 2. Validate and enforce safety
            pipeline = self._validate_and_sanitize(pipeline)
            return pipeline
        except Exception as e:
            print(f"Query preparation failed: {e}")
            raise e


