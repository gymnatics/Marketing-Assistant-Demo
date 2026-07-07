"""Tests for Customer Analyst agent — tool call streaming + keyword fallback."""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from helpers import (
    load_agent_module,
    make_tool_call_chunks, make_empty_stream_chunks,
    MockAsyncStream,
)

agent = load_agent_module("customer-analyst")


# ===== Tool Call Streaming (mocked OpenAI SDK) =====

@pytest.mark.asyncio
class TestLlmSelectAndCallTool:
    async def test_tool_call_streaming_assembles_name_and_args(self):
        chunks = make_tool_call_chunks(
            "get_customers_by_tier",
            ['{"tier":', ' "platinum",', ' "limit": 10}']
        )
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))
        mock_mcp = AsyncMock(return_value=[{"customer_id": "VIP-001", "name": "Test", "tier": "platinum"}])

        original_client = agent._llm_client
        original_mcp = agent.call_mcp_tool
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            agent.call_mcp_tool = mock_mcp

            result, rtype = await agent._llm_select_and_call_tool(
                "Get platinum customers", target_audience="Platinum members", limit=10
            )
        finally:
            agent._llm_client = original_client
            agent.call_mcp_tool = original_mcp

        assert rtype == "customers"
        mock_mcp.assert_called_once()
        mcp_args = mock_mcp.call_args
        assert mcp_args[0][0] == "get_customers_by_tier"
        assert mcp_args[0][1]["tier"] == "platinum"

    async def test_no_tool_selected_triggers_keyword_fallback(self):
        chunks = make_empty_stream_chunks()
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))
        mock_mcp = AsyncMock(return_value=[{"customer_id": "VIP-001"}])

        original_client = agent._llm_client
        original_mcp = agent.call_mcp_tool
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            agent.call_mcp_tool = mock_mcp

            result, rtype = await agent._llm_select_and_call_tool(
                "Get platinum customers", target_audience="Platinum members", limit=50
            )
        finally:
            agent._llm_client = original_client
            agent.call_mcp_tool = original_mcp

        assert rtype == "customers"
        mcp_args = mock_mcp.call_args
        assert mcp_args[0][0] == "get_customers_by_tier"
        assert mcp_args[0][1]["tier"] == "platinum"

    async def test_prospect_fallback(self):
        chunks = make_empty_stream_chunks()
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))
        mock_mcp = AsyncMock(return_value=[])

        original_client = agent._llm_client
        original_mcp = agent.call_mcp_tool
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            agent.call_mcp_tool = mock_mcp

            _, rtype = await agent._llm_select_and_call_tool(
                "Get new members", target_audience="New members", limit=50
            )
        finally:
            agent._llm_client = original_client
            agent.call_mcp_tool = original_mcp

        assert rtype == "prospects"
        assert mock_mcp.call_args[0][0] == "get_prospects"


# ===== Keyword Fallback (pure logic, no LLM mock needed) =====

class TestKeywordFallback:
    """Test the keyword fallback logic by providing an empty LLM stream for each audience pattern."""

    @pytest.fixture
    def _setup_empty_stream(self):
        chunks = make_empty_stream_chunks()
        self.mock_create = AsyncMock(return_value=MockAsyncStream(chunks))
        self.mock_mcp = AsyncMock(return_value=[])
        self.original_client = agent._llm_client
        self.original_mcp = agent.call_mcp_tool
        agent._llm_client = MagicMock()
        agent._llm_client.chat.completions.create = self.mock_create
        agent.call_mcp_tool = self.mock_mcp
        yield
        agent._llm_client = self.original_client
        agent.call_mcp_tool = self.original_mcp

    @pytest.mark.asyncio
    @pytest.mark.parametrize("audience,expected_tool,expected_type", [
        ("New members", "get_prospects", "prospects"),
        ("Prospect list", "get_prospects", "prospects"),
        ("Platinum members", "get_customers_by_tier", "customers"),
        ("Diamond elite", "get_customers_by_tier", "customers"),
        ("Gold members", "get_customers_by_tier", "customers"),
        ("High spend whales", "get_high_spend_customers", "customers"),
        ("whale customers", "get_high_spend_customers", "customers"),
        ("All VIP customers", "get_all_vip_customers", "customers"),
        ("everyone", "get_all_vip_customers", "customers"),
    ])
    async def test_keyword_patterns(self, _setup_empty_stream, audience, expected_tool, expected_type):
        # Reset mock for each parametrize call since fixture creates one stream
        chunks = make_empty_stream_chunks()
        agent._llm_client.chat.completions.create = AsyncMock(return_value=MockAsyncStream(chunks))

        _, rtype = await agent._llm_select_and_call_tool(
            f"Retrieve {audience}", target_audience=audience, limit=50
        )
        assert rtype == expected_type
        assert self.mock_mcp.call_args[0][0] == expected_tool
