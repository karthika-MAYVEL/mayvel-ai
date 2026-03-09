import pytest
from presentation.models.global_search_response import (
    GlobalSearchItem,
    GlobalSearchMeta,
    GlobalSearchData,
    GlobalSearchResponseWrapper,
)

def test_global_search_response_serialization_matches_frontend_contract():
    """
    Tests that the Pydantic models serialize exactly into the format expected by the frontend.
    Specifically checks for _id mapping, camelCase field names, and nested data structure.
    """
    # 1. Create a dummy search item
    item = GlobalSearchItem(
        id="64abcdef1234567890",
        title="Monthly Safety Inspection",
        type="inspection",
        tags=["safety", "urgent"],
        tenant_id="org-789",
        created_by="user-456",
        created_at="2023-10-01T10:00:00.000Z",
        updated_at="2023-10-05T14:30:00.000Z"
    )

    # 2. Create the meta block
    meta = GlobalSearchMeta(
        llm_responses=[
            {"stage": "T1_Router", "intent": "search_inspections"}
        ],
        executed_mongo_query=[
            {"$match": {"tenantId": "org-789", "tags": "safety"}}
        ]
    )

    # 3. Create the nested data block
    data_block = GlobalSearchData(
        global_search_response=[item]
    )

    # 4. Create the final response wrapper
    response = GlobalSearchResponseWrapper(
        success=True,
        message="Analyzed 1 results",
        total_results=1,
        data=data_block,
        meta=meta
    )

    # Act
    # model_dump(by_alias=True) ensures variables like tenant_id are rendered as tenantId
    json_data = response.model_dump(by_alias=True)

    # Assert Root Fields
    assert json_data["success"] is True
    assert json_data["message"] == "Analyzed 1 results"
    assert json_data["totalResults"] == 1
    
    # Assert Nested Data Block
    assert "data" in json_data
    assert "globalSearchResponse" in json_data["data"]
    items_array = json_data["data"]["globalSearchResponse"]
    assert len(items_array) == 1
    
    # Assert Item Fields (Checking camelCase and _id contract)
    serialized_item = items_array[0]
    assert serialized_item["_id"] == "64abcdef1234567890"  # Critical: Must be _id, not id
    assert serialized_item["title"] == "Monthly Safety Inspection"
    assert serialized_item["type"] == "inspection"
    assert serialized_item["tags"] == ["safety", "urgent"]
    assert serialized_item["tenantId"] == "org-789"
    assert serialized_item["createdBy"] == "user-456"
    assert serialized_item["createdAt"] == "2023-10-01T10:00:00.000Z"
    assert serialized_item["updatedAt"] == "2023-10-05T14:30:00.000Z"

    # Assert Meta Block
    assert "meta" in json_data
    assert len(json_data["meta"]["llm_responses"]) == 1
    assert json_data["meta"]["llm_responses"][0]["stage"] == "T1_Router"
    assert "$match" in json_data["meta"]["executed_mongo_query"][0]

