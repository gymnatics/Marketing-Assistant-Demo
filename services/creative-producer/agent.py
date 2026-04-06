"""
Creative Producer Agent - Generates luxury marketing landing pages.

"Bones & Beauty" architecture:
- Bones: Professional HTML skeleton (base_template.html) with fixed structural CSS
- Beauty: LLM generates creative CSS + bilingual content
- Result: Always polished, always different
"""
import os
import sys
import json
import httpx

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import CAMPAIGN_THEMES, GenerateLandingPageInput, GenerateLandingPageOutput


CODE_MODEL_ENDPOINT = os.environ.get(
    "CODE_MODEL_ENDPOINT",
    "https://qwen25-coder-32b-fp8-0-marketing-assistant-demo.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com/v1"
)
CODE_MODEL_NAME = os.environ.get("CODE_MODEL_NAME", "qwen25-coder-32b-fp8")
EVENT_HUB_URL = os.environ.get("EVENT_HUB_URL", "http://event-hub:5001")
IMAGEGEN_MCP_URL = os.environ.get("IMAGEGEN_MCP_URL", "http://imagegen-mcp:8091")

BASE_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "base_template.html")

THEME_PRESET_NAMES = {
    "luxury_gold": "The Heritage Collection",
    "festive_red": "The Celebration Suite",
    "modern_black": "The Urban Retreat",
    "classic_casino": "The Grand Stakes",
}

SYSTEM_PROMPT = """You are a premier Digital Brand Architect specializing in high-conversion marketing for luxury hotels and ultra-exclusive resorts. Your expertise is "Visual Hospitality" — translating a physical five-star experience into a digital interface that feels as refined and welcoming as a grand lobby.

## Core Design Principles:
1. "The Check-In Impression": Your designs feel like a premium arrival experience. Expansive whitespace within sections, high-fidelity imagery, calm architectural order.
2. "Hospitality Typography": 'Manrope' for headlines with tight tracking. Body text airy and elegant — like a personalized welcome letter.
3. "Atmospheric Color Palettes": Use the provided CSS variables exclusively. Accents should feel metallic (gold/silver) or deep jewel (emerald/ruby).
4. "Imagery as the Main Course": The hero image is the narrative centerpiece. Use overlays, blend modes, and gradients to frame it cinematically.
5. "The Concierge CTA": Buttons are sharp-edged, high-contrast, premium language.
6. "Visual Hierarchy & Flow": Guide the eye from hero to CTA using clear grouping (related elements close together, distinct sections with breathing room), consistent visual patterns (cards should feel like a cohesive set, not individual designs), and strong figure-ground contrast (text must always "lift" from its background through overlays, shadows, or contrast).

## Theme Presets:
- "The Heritage Collection" (Luxury Gold): Deep midnight slate (#0F172A) backgrounds, classic gold (#D4AF37) accents, shimmer gold (#FDE047) hover states, warm and established.
- "The Celebration Suite" (Festive Red): Deep maroon (#450A0A) base, crimson (#C41E3A) primary, rich gold (#B8860B) accents. Sections alternate between maroon and darker crimson tones. Professional yet festive — elegant red and gold, NOT pink or blush.
- "The Urban Retreat" (Modern Minimal): Pure white (#FFFFFF) base, slate 50 (#F8FAFC) section separation, midnight black (#0F172A) buttons and branding. Maximum whitespace, architectural.
- "The Grand Stakes" (Classic Casino): Deep emerald baize (#064E3B), forest green (#065F46) depth layers, amber gold (#F59E0B) to suggest winning, cool silver (#D1D5DB) for interactive elements. Mint white (#F0FDF4) text.

## Technical Rules:
- You receive a fixed semantic HTML skeleton. Do NOT output any HTML tags.
- Output a <style> block to "paint" the brand onto the structure, PLUS a content block.
- Use CSS variables: var(--primary), var(--secondary), var(--accent), var(--bg), var(--text), var(--button-color), var(--button-text)
- Style these classes creatively: body, nav, .hero, .hero-overlay, .hero .badge, .offer, .benefits, .benefits-grid, .card, .story, .dates, .date-badge, .cta-section, .cta-btn, .qr-section, footer
- Be creative with: backgrounds (gradients, radial, conic, mesh), card hover effects (scale, glow, border-shimmer), @keyframes animations (shimmer, float, pulse, glow, gradient-shift), hero overlay blend modes, section transitions
- Every generation must look DIFFERENT — vary gradient directions, animation types, card treatments, section backgrounds
- Use the CSS variables as your palette foundation. Ensure strong contrast between text and backgrounds. Sections should have varied but cohesive backgrounds — alternate between deeper and lighter tones to create visual rhythm. No section should ever look unstyled or default.
- Every element must feel curated and intentional — no default-looking components.

## Output Format:
Return EXACTLY two sections separated by ---CONTENT---

First: a <style> block with your creative CSS (100-200 lines).
Then: ---CONTENT--- followed by key-value content lines.

Do NOT output anything else — no explanations, no HTML, no markdown fences."""


def load_base_template() -> str:
    with open(BASE_TEMPLATE_PATH, "r") as f:
        return f.read()


def parse_llm_output(raw: str) -> tuple[str, dict]:
    """Parse LLM output into (css_style_block, content_dict).

    Expected format:
        <style>...</style>
        ---CONTENT---
        KEY: value
        KEY: value
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3].strip()

    separator = "---CONTENT---"
    if separator not in raw:
        return raw, {}

    parts = raw.split(separator, 1)
    style_block = parts[0].strip()
    content_raw = parts[1].strip()

    content = {}
    for line in content_raw.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if not key or not value:
                continue
            content[key] = value

    return style_block, content


def merge_template(template: str, theme_config: dict, style_block: str, content: dict,
                   hero_image_url: str | None, hotel_name: str, start_date: str, end_date: str) -> str:
    """Merge the base template with theme vars, LLM style, and content."""
    html = template

    html = html.replace("THEME_PRIMARY", theme_config["primary_color"])
    html = html.replace("THEME_SECONDARY", theme_config["secondary_color"])
    html = html.replace("THEME_ACCENT", theme_config["accent_color"])
    html = html.replace("THEME_BG", theme_config.get("secondary_color", "#0a0a0a"))
    html = html.replace("THEME_TEXT", theme_config["text_color"])
    html = html.replace("THEME_BUTTON_COLOR", theme_config["button_color"])
    html = html.replace("THEME_BUTTON_TEXT", theme_config["button_text"])

    html = html.replace("LLM_STYLE_PLACEHOLDER", style_block)

    if hero_image_url:
        html = html.replace("HERO_IMAGE_PLACEHOLDER", hero_image_url)
    else:
        html = html.replace(
            "style=\"background-image: url('HERO_IMAGE_PLACEHOLDER');\"",
            "style=\"background: var(--bg);\""
        )

    html = html.replace("HOTEL_NAME", hotel_name)
    html = html.replace("DATE_START", start_date or "TBD")
    html = html.replace("DATE_END", end_date or "TBD")

    content_keys = [
        "HEADLINE", "SUBTITLE",
        "OFFER_TEXT",
        "BENEFIT_1_TITLE", "BENEFIT_1_DESC",
        "BENEFIT_2_TITLE", "BENEFIT_2_DESC",
        "BENEFIT_3_TITLE", "BENEFIT_3_DESC",
        "BENEFIT_4_TITLE", "BENEFIT_4_DESC",
        "STORY_TEXT",
    ]
    for key in content_keys:
        value = content.get(key, "")
        if value:
            html = html.replace(key, value)

    return html


async def generate_hero_image(campaign_name: str, hotel_name: str, theme: str, description: str = "") -> str | None:
    """Call Image Gen MCP to generate a hero banner image. Returns a public URL or None on failure."""
    try:
        from fastmcp import Client
        async with Client(f"{IMAGEGEN_MCP_URL}/mcp") as mcp_client:
            result = await mcp_client.call_tool("generate_campaign_image", {
                "campaign_name": campaign_name,
                "hotel_name": hotel_name,
                "theme": theme,
                "description": description,
                "width": 1024,
                "height": 576,
            })
            if result and result.content:
                import json as _json
                data = _json.loads(result.content[0].text)
                image_url = data.get("image_url")
                if image_url:
                    print(f"[Creative Producer] Hero image generated: {image_url}")
                    return image_url
            print(f"[Creative Producer] Image gen returned empty result")
            return None
    except Exception as e:
        print(f"[Creative Producer] Image gen error (non-fatal): {e}")
        return None


async def publish_event(campaign_id: str, event_type: str, agent: str, task: str, data: dict = None):
    """Publish event to Event Hub for UI updates."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{EVENT_HUB_URL}/events/{campaign_id}/publish",
                json={
                    "event_type": event_type,
                    "agent": agent,
                    "task": task,
                    "data": data or {}
                },
                timeout=5.0
            )
    except Exception as e:
        print(f"[Creative Producer] Failed to publish event: {e}")


async def stream_llm(system_prompt: str, user_prompt: str) -> str:
    """Stream a completion from Qwen Coder and return the full response text."""
    url = f"{CODE_MODEL_ENDPOINT}/chat/completions"
    headers = {"Content-Type": "application/json"}
    auth_token = os.environ.get("CODE_MODEL_TOKEN", "")
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    payload = {
        "model": CODE_MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.9,
        "max_tokens": 8000,
        "stream": True
    }

    result = ""
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                raise Exception(f"Model API error: {response.status_code} - {error_text}")

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                result += content
                    except json.JSONDecodeError:
                        continue
    return result


async def generate_html_with_streaming(
    campaign_name: str,
    campaign_description: str,
    hotel_name: str,
    theme: str,
    start_date: str,
    end_date: str,
    hero_image_url: str | None = None
) -> str:
    """Generate landing page by merging skeleton template with LLM-generated CSS + content."""

    theme_config = CAMPAIGN_THEMES.get(theme, CAMPAIGN_THEMES["luxury_gold"])
    preset_name = THEME_PRESET_NAMES.get(theme, "The Heritage Collection")

    hero_note = ""
    if hero_image_url:
        hero_note = "\nThe hero section has an AI-generated background image — make it feel cinematic with overlays (rgba or gradient) and blend modes."

    user_prompt = f"""Design a "{preset_name}" visual experience for "{campaign_name}" at {hotel_name}.

Color palette:
- Primary: {theme_config['primary_color']}
- Secondary: {theme_config['secondary_color']}
- Accent: {theme_config['accent_color']}
- Background: {theme_config.get('secondary_color', '#0a0a0a')}
- Text: {theme_config['text_color']}
- Button: {theme_config['button_color']} on {theme_config['button_text']}

Campaign story: {campaign_description}
Period: {start_date} to {end_date}
{hero_note}
Make the benefit cards feel luxurious (glassmorphism, gradient borders, frosted glass, or subtle depth).
Add at least 2 @keyframes animations (e.g., shimmer on CTA, float on cards, gradient shift on hero, pulse on badge).

Output format — provide BOTH sections:

<style>
... your creative CSS here ...
</style>
---CONTENT---
HEADLINE: (proofread/polished campaign name — fix typos, proper capitalization)
SUBTITLE: (short tagline, e.g., "An Invitation to Indulgence")
OFFER_TEXT: (1-2 sentence exclusive offer description, luxury editorial tone)
BENEFIT_1_TITLE: (short benefit name, e.g., "Luxury Suite Upgrade")
BENEFIT_1_DESC: (1 sentence benefit description)
BENEFIT_2_TITLE: (different benefit)
BENEFIT_2_DESC: (1 sentence)
BENEFIT_3_TITLE: (different benefit)
BENEFIT_3_DESC: (1 sentence)
BENEFIT_4_TITLE: (different benefit)
BENEFIT_4_DESC: (1 sentence)
STORY_TEXT: (2-3 sentences about the campaign experience, luxury editorial tone)

ALL content must be in English only. Do NOT include any Chinese text."""

    raw_response = await stream_llm(SYSTEM_PROMPT, user_prompt)

    # Fallback: if LLM returned full HTML instead of style+content, use it directly
    if "<!DOCTYPE" in raw_response or "<html" in raw_response:
        print("[Creative Producer] Fallback: LLM returned full HTML, using directly")
        html = raw_response.strip()
        if html.startswith("```html"):
            html = html[7:]
        if html.startswith("```"):
            html = html[3:]
        if html.endswith("```"):
            html = html[:-3]
        if hero_image_url and "HERO_IMAGE_PLACEHOLDER" in html:
            html = html.replace("HERO_IMAGE_PLACEHOLDER", hero_image_url)
        return html

    style_block, content = parse_llm_output(raw_response)
    print(f"[Creative Producer] Parsed LLM output: {len(style_block)} chars CSS, {len(content)} content keys")

    template = load_base_template()
    html = merge_template(
        template=template,
        theme_config=theme_config,
        style_block=style_block,
        content=content,
        hero_image_url=hero_image_url,
        hotel_name=hotel_name,
        start_date=start_date,
        end_date=end_date,
    )

    return html


class CreativeProducerAgent:
    """Pure business logic for the Creative Producer agent."""

    async def generate(self, params: dict) -> dict:
        campaign_id = params.get("campaign_id", "unknown")

        await publish_event(
            campaign_id=campaign_id,
            event_type="agent_started",
            agent="Creative Producer",
            task="Creating campaign visuals..."
        )

        try:
            hero_image_url = await generate_hero_image(
                campaign_name=params["campaign_name"],
                hotel_name=params["hotel_name"],
                theme=params["theme"],
                description=params["campaign_description"],
            )

            if hero_image_url:
                await publish_event(
                    campaign_id=campaign_id,
                    event_type="agent_completed",
                    agent="Creative Producer",
                    task="Campaign visuals ready",
                    data={"image_url": hero_image_url}
                )
            else:
                await publish_event(
                    campaign_id=campaign_id,
                    event_type="workflow_status",
                    agent="Creative Producer",
                    task="Applying theme design..."
                )

            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_started",
                agent="Creative Producer",
                task="Designing your landing page..."
            )

            html = await generate_html_with_streaming(
                campaign_name=params["campaign_name"],
                campaign_description=params["campaign_description"],
                hotel_name=params["hotel_name"],
                theme=params["theme"],
                start_date=params["start_date"],
                end_date=params["end_date"],
                hero_image_url=hero_image_url,
            )

            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_completed",
                agent="Creative Producer",
                task="Landing page ready",
                data={"html_length": len(html)}
            )

            return {"html": html, "hero_image_url": hero_image_url, "status": "success"}

        except Exception as e:
            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_error",
                agent="Creative Producer",
                task="Design generation failed",
                data={"error": str(e)}
            )

            return {"html": "", "hero_image_url": None, "status": "error", "error": str(e)}
