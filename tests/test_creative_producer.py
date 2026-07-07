"""Tests for Creative Producer agent — pure parsers + mocked OpenAI streaming."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from helpers import (
    load_agent_module,
    make_content_chunks, make_empty_stream_chunks,
    MockAsyncStream, SAMPLE_THEME_CONFIG,
)

agent = load_agent_module("creative-producer")


# ===== parse_llm_output =====

class TestParseLlmOutput:
    def test_normal_input(self):
        raw = "<style>.hero{color:red}</style>\n---CONTENT---\nHEADLINE: Gala Night\nSUBTITLE: Exclusive Event"
        style, content = agent.parse_llm_output(raw)
        assert "<style>" in style
        assert content["HEADLINE"] == "Gala Night"
        assert content["SUBTITLE"] == "Exclusive Event"

    def test_markdown_fences_stripped(self):
        raw = "```css\n<style>.hero{}</style>\n---CONTENT---\nHEADLINE: Test\n```"
        style, content = agent.parse_llm_output(raw)
        assert style.startswith("<style>")
        assert content["HEADLINE"] == "Test"

    def test_missing_separator(self):
        raw = "<style>.hero{color:blue}</style>"
        style, content = agent.parse_llm_output(raw)
        assert style == raw
        assert content == {}

    def test_empty_value_skipped(self):
        raw = "<style>x</style>\n---CONTENT---\nHEADLINE: Good\nBADKEY: \nSUBTITLE: Also Good"
        _, content = agent.parse_llm_output(raw)
        assert "HEADLINE" in content
        assert "SUBTITLE" in content
        assert "BADKEY" not in content

    def test_whitespace_handling(self):
        raw = "  \n<style>x</style>\n\n---CONTENT---\n  HEADLINE:   Spaces Preserved  \n"
        style, content = agent.parse_llm_output(raw)
        assert style == "<style>x</style>"
        assert content["HEADLINE"] == "Spaces Preserved"

    def test_empty_input(self):
        style, content = agent.parse_llm_output("")
        assert style == ""
        assert content == {}

    def test_content_with_colons_in_value(self):
        raw = "<style>x</style>\n---CONTENT---\nHEADLINE: Time: 8PM - VIP Only"
        _, content = agent.parse_llm_output(raw)
        assert content["HEADLINE"] == "Time: 8PM - VIP Only"


# ===== merge_template =====

class TestMergeTemplate:
    TEMPLATE = (
        '<div style="--primary: THEME_PRIMARY; --secondary: THEME_SECONDARY; '
        '--accent: THEME_ACCENT; --bg: THEME_BG; --text: THEME_TEXT; '
        '--button-color: THEME_BUTTON_COLOR; --button-text: THEME_BUTTON_TEXT;">'
        'LLM_STYLE_PLACEHOLDER'
        '<img style="background-image: url(\'HERO_IMAGE_PLACEHOLDER\');" />'
        '<h1>HEADLINE</h1><p>SUBTITLE</p>'
        '<span>HOTEL_NAME</span><span>DATE_START - DATE_END</span>'
        '</div>'
    )

    def test_theme_colors_replaced(self):
        html = agent.merge_template(
            self.TEMPLATE, SAMPLE_THEME_CONFIG, "<style>test</style>",
            {}, None, "Test Hotel", "2026-01-01", "2026-01-31"
        )
        assert "#0F172A" in html
        assert "#D4AF37" in html
        assert "THEME_PRIMARY" not in html

    def test_hero_image_url_substituted(self):
        html = agent.merge_template(
            self.TEMPLATE, SAMPLE_THEME_CONFIG, "",
            {}, "https://img.example.com/hero.png", "Hotel", "2026-01-01", "2026-01-31"
        )
        assert "https://img.example.com/hero.png" in html
        assert "HERO_IMAGE_PLACEHOLDER" not in html

    def test_hero_image_none_fallback(self):
        html = agent.merge_template(
            self.TEMPLATE, SAMPLE_THEME_CONFIG, "",
            {}, None, "Hotel", "2026-01-01", "2026-01-31"
        )
        assert "var(--bg)" in html

    def test_content_keys_substituted(self):
        content = {"HEADLINE": "Grand Opening", "SUBTITLE": "VIP Only"}
        html = agent.merge_template(
            self.TEMPLATE, SAMPLE_THEME_CONFIG, "",
            content, None, "Hotel", "2026-01-01", "2026-01-31"
        )
        assert "Grand Opening" in html
        assert "VIP Only" in html

    def test_none_dates_become_tbd(self):
        html = agent.merge_template(
            self.TEMPLATE, SAMPLE_THEME_CONFIG, "",
            {}, None, "Hotel", None, None
        )
        assert "TBD" in html
        assert "DATE_START" not in html

    def test_llm_style_placeholder_replaced(self):
        html = agent.merge_template(
            self.TEMPLATE, SAMPLE_THEME_CONFIG, "<style>.custom{}</style>",
            {}, None, "Hotel", "2026-01-01", "2026-01-31"
        )
        assert "<style>.custom{}</style>" in html
        assert "LLM_STYLE_PLACEHOLDER" not in html


# ===== stream_llm (mocked OpenAI SDK) =====

@pytest.mark.asyncio
class TestStreamLlm:
    async def test_streaming_accumulates_content(self):
        chunks = make_content_chunks(["Hello", " World", "!"])
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.stream_llm("system prompt", "user prompt")
        finally:
            agent._llm_client = original_client

        assert result == "Hello World!"
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["stream"] is True
        assert call_kwargs["temperature"] == 0.9
        assert call_kwargs["max_tokens"] == 8000

    async def test_empty_stream_returns_empty_string(self):
        chunks = make_empty_stream_chunks()
        mock_create = AsyncMock(return_value=MockAsyncStream(chunks))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            result = await agent.stream_llm("system", "user")
        finally:
            agent._llm_client = original_client

        assert result == ""

    async def test_api_error_propagates(self):
        from openai import APIConnectionError
        mock_create = AsyncMock(side_effect=APIConnectionError(request=None))

        original_client = agent._llm_client
        try:
            agent._llm_client = MagicMock()
            agent._llm_client.chat.completions.create = mock_create
            with pytest.raises(APIConnectionError):
                await agent.stream_llm("system", "user")
        finally:
            agent._llm_client = original_client
