"""Unit tests for DatabricksServingChatOpenAI request payload."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.llm.chat_databricks_serving import DatabricksServingChatOpenAI


def test_request_payload_uses_max_tokens_not_max_completion_tokens():
    llm = DatabricksServingChatOpenAI(
        model="databricks-meta-llama-3-3-70b-instruct",
        api_key="test",
        base_url="https://example.cloud.databricks.com/serving-endpoints",
        max_tokens=100,
    )
    payload = llm._get_request_payload([HumanMessage(content="hi")])
    assert "max_completion_tokens" not in payload
    assert payload.get("max_tokens") == 100
