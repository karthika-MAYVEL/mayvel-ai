async def _run_pipeline(db: Any, pipeline: list) -> list:
    """
    Runs an aggregation pipeline against MongoDB.

    Returns sanitized documents suitable for JSON serialization.
    """

    from utils.sanitizer import _sanitize_doc

    if db is None:
        logger.warning("No DB connection — returning empty results (offline mode).")
        return []

    try:
        cursor = db[_COLLECTION].aggregate(pipeline)

        # Fetch all results from cursor
        raw_docs = await cursor.to_list(length=None)

        return [_sanitize_doc(doc) for doc in raw_docs]

    except Exception as exc:
        logger.error(f"Mongo pipeline execution failed: {exc}")
        raise