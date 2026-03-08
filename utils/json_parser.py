import json

def safe_parse_json(raw: str) -> dict:
    """
    1. Strip leading/trailing whitespace
    2. Strip ```json ... ``` or ``` ... ``` fences
    3. json.loads()
    4. On failure → raise ValueError with the raw string for debugging
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if len(lines) > 1:
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed[0] if len(parsed) > 0 else {}
        return parsed
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON. Error: {e}\nRaw String:\n{raw}")
