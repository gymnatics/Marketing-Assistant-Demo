"""Tests for Policy Guardian agent — APPROVED/REJECTED/think-strip/fail-open."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from helpers import load_agent_module, make_completion

agent = load_agent_module("policy-guardian")


@pytest.mark.asyncio
class TestValidatePolicy:
    async def test_approved_response(self):
        mock_create = AsyncMock(return_value=make_completion("APPROVED"))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.validate_policy("VIP Gala", "Exclusive black-tie event for platinum members")
        finally:
            agent._llm_client = original_client

        assert result["approved"] is True
        assert result["reason"] == ""

    async def test_rejected_response(self):
        mock_create = AsyncMock(return_value=make_completion("REJECTED: Unrealistic discount exceeding 50%"))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.validate_policy("99% Off Everything", "99% off all rooms")
        finally:
            agent._llm_client = original_client

        assert result["approved"] is False
        assert "Unrealistic discount" in result["reason"]

    async def test_rejected_without_reason(self):
        mock_create = AsyncMock(return_value=make_completion("REJECTED"))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.validate_policy("Bad Campaign", "Something bad")
        finally:
            agent._llm_client = original_client

        assert result["approved"] is False
        assert result["reason"] == "Campaign policy violation"

    async def test_think_tags_stripped(self):
        response_with_think = "<think>Let me analyze this...</think>\nAPPROVED"
        mock_create = AsyncMock(return_value=make_completion(response_with_think))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.validate_policy("Spa Weekend", "Complimentary spa with 2-night stay")
        finally:
            agent._llm_client = original_client

        assert result["approved"] is True

    async def test_think_tags_with_rejection(self):
        response_with_think = "<think>This violates policy rule 1</think>\nREJECTED: Discount too high at 80%"
        mock_create = AsyncMock(return_value=make_completion(response_with_think))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.validate_policy("Mega Sale", "80% off everything")
        finally:
            agent._llm_client = original_client

        assert result["approved"] is False
        assert "80%" in result["reason"]

    async def test_llm_error_fails_open(self):
        mock_create = AsyncMock(side_effect=Exception("Connection refused"))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.validate_policy("Test", "Test description")
        finally:
            agent._llm_client = original_client

        assert result["approved"] is True
        assert result["reason"] == ""

    async def test_timeout_error_fails_open(self):
        from openai import APITimeoutError
        mock_create = AsyncMock(side_effect=APITimeoutError(request=None))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.validate_policy("Test", "Test description")
        finally:
            agent._llm_client = original_client

        assert result["approved"] is True

    async def test_case_insensitive_rejected(self):
        mock_create = AsyncMock(return_value=make_completion("rejected: Bad language"))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.validate_policy("Test", "Test")
        finally:
            agent._llm_client = original_client

        assert result["approved"] is False

    async def test_non_streaming_call_params(self):
        mock_create = AsyncMock(return_value=make_completion("APPROVED"))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            await agent.validate_policy("Test", "Test")
        finally:
            agent._llm_client = original_client

        call_kwargs = mock_create.call_args.kwargs
        assert "stream" not in call_kwargs or call_kwargs.get("stream") is not True
        assert call_kwargs["temperature"] == 0.1
        assert call_kwargs["max_tokens"] == 300
