from datetime import datetime
from typing import Any

def _sanitize_doc(doc: Any) -> Any:
    """
    Recursively converts BSON types to JSON-serialisable Python types.
    Handles ObjectId, datetime, Decimal128, bytes, and nested dicts/lists.
    """
    try:
        from bson import ObjectId, Decimal128
        _HAS_BSON = True
    except ImportError:
        _HAS_BSON = False

    if isinstance(doc, dict):
        return {k: _sanitize_doc(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [_sanitize_doc(v) for v in doc]
    if isinstance(doc, datetime):
        return doc.isoformat()
    if isinstance(doc, bytes):
        import base64
        return base64.b64encode(doc).decode()
    if _HAS_BSON:
        if isinstance(doc, ObjectId):
            return str(doc)
        if isinstance(doc, Decimal128):
            return float(doc.to_decimal())
    return doc
