"""Tests for Delivery Manager agent — email parser + mocked OpenAI streaming."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from helpers import (
    load_agent_module,
    make_content_chunks, make_empty_stream_chunks,
    MockAsyncStream,
)

agent = load_agent_module("delivery-manager")


# ===== parse_email_response =====

class TestParseEmailResponse:
    def test_normal_four_sections(self):
        raw = (
            "---ENGLISH_SUBJECT---\n"
            "Exclusive VIP Gala\n"
            "---ENGLISH_BODY---\n"
            "<h1>Dear {{customer_name}}</h1>\n"
            "<p>You are invited.</p>\n"
            "---CHINESE_SUBJECT---\n"
            "VIP 晚会\n"
            "---CHINESE_BODY---\n"
            "<h1>尊敬的 {{customer_name}}</h1>\n"
        )
        result = agent.parse_email_response(raw)
        assert result["email_subject_en"] == "Exclusive VIP Gala"
        assert "<h1>Dear" in result["email_body_en"]
        assert result["email_subject_zh"] == "VIP 晚会"
        assert "尊敬的" in result["email_body_zh"]

    def test_missing_chinese_sections(self):
        raw = (
            "---ENGLISH_SUBJECT---\n"
            "Test Subject\n"
            "---ENGLISH_BODY---\n"
            "<p>Body content</p>\n"
        )
        result = agent.parse_email_response(raw)
        assert result["email_subject_en"] == "Test Subject"
        assert result["email_body_en"] == "<p>Body content</p>"
        assert result["email_subject_zh"] == ""
        assert result["email_body_zh"] == ""

    def test_empty_input(self):
        result = agent.parse_email_response("")
        assert result["email_subject_en"] == ""
        assert result["email_body_en"] == ""
        assert result["email_subject_zh"] == ""
        assert result["email_body_zh"] == ""

    def test_multiline_html_body(self):
        raw = (
            "---ENGLISH_SUBJECT---\n"
            "Welcome\n"
            "---ENGLISH_BODY---\n"
            "<h1>Hello</h1>\n"
            "<p>Line 1</p>\n"
            "<p>Line 2</p>\n"
            '<a href="{{campaign_link}}">Click</a>\n'
            "---CHINESE_SUBJECT---\n"
            "欢迎\n"
        )
        result = agent.parse_email_response(raw)
        assert "<h1>Hello</h1>" in result["email_body_en"]
        assert "<p>Line 2</p>" in result["email_body_en"]
        assert "{{campaign_link}}" in result["email_body_en"]

    def test_whitespace_between_sections(self):
        raw = (
            "\n\n---ENGLISH_SUBJECT---\n"
            "  Subject With Spaces  \n"
            "\n"
            "---ENGLISH_BODY---\n"
            "  <p>Body</p>  \n"
        )
        result = agent.parse_email_response(raw)
        assert result["email_subject_en"] == "Subject With Spaces"
        assert "<p>Body</p>" in result["email_body_en"]


# ===== generate_email_with_streaming (mocked OpenAI SDK) =====

@pytest.mark.asyncio
class TestGenerateEmailWithStreaming:
    async def test_streaming_produces_parsed_email(self):
        email_text = (
            "---ENGLISH_SUBJECT---\n"
            "Grand Opening\n"
            "---ENGLISH_BODY---\n"
            "<p>Welcome to our event.</p>\n"
            "---CHINESE_SUBJECT---\n"
            "盛大开幕\n"
            "---CHINESE_BODY---\n"
            "<p>欢迎参加。</p>\n"
        )
        # Split into realistic streaming chunks
        chunks = make_content_chunks([email_text[:40], email_text[40:80], email_text[80:]])
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.generate_email_with_streaming(
                campaign_name="Grand Opening",
                campaign_description="A luxury event",
                hotel_name="Simon Casino Resort",
                campaign_url="https://example.com",
                target_audience="Platinum members",
                start_date="2026-06-01",
                end_date="2026-06-30",
            )
        finally:
            agent._llm_client = original_client

        assert result["email_subject_en"] == "Grand Opening"
        assert "<p>Welcome" in result["email_body_en"]
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["stream"] is True
        assert call_kwargs["temperature"] == 0.7

    async def test_empty_stream_returns_empty_fields(self):
        chunks = make_empty_stream_chunks()
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.generate_email_with_streaming(
                campaign_name="Test",
                campaign_description="Test",
                hotel_name="Hotel",
                campaign_url="https://example.com",
                target_audience="All",
                start_date="2026-01-01",
                end_date="2026-01-31",
            )
        finally:
            agent._llm_client = original_client

        assert result["email_subject_en"] == ""
        assert result["email_body_en"] == ""
