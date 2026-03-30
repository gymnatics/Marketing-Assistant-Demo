"""
Creative Producer Agent - Pure business logic for generating luxury marketing landing pages.

Uses Qwen2.5-Coder-32B-FP8 model for HTML/CSS/JS generation.
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
CODE_MODEL_TOKEN = os.environ.get("CODE_MODEL_TOKEN", "")
EVENT_HUB_URL = os.environ.get("EVENT_HUB_URL", "http://event-hub:5001")


CODER_SYSTEM_PROMPT = """You are a world-class UI/UX Designer and Frontend Engineer specializing in "The Editorial Architect" aesthetic — a design style that prioritizes high-end typography, sophisticated whitespace, and a luxury brand feel. Your goal is to generate high-fidelity, responsive HTML/CSS for marketing landing pages that cater to C-suite executives.

## Visual Identity Principles:
1. **Typography First**: Use 'Manrope' as the primary typeface via Google Fonts CDN. Headlines should be bold, high-contrast, and have tight letter-spacing. Body text should be airy and legible with 'Inter' font.
2. **The Power of Negative Space**: Use generous margins and padding to create a sense of exclusivity and focus. Never cram content.
3. **Controlled Color Palette**: Use the provided theme colors. Accents should be used sparingly for high impact.
4. **Imagery as Architecture**: Use CSS gradients and geometric patterns to create sophisticated visual depth. Include subtle parallax or scale-in effects.
5. **Interactive Precision**: Buttons should have slightly rounded corners. Use subtle hover states (opacity changes, slight tonal shifts, scale transforms) rather than heavy shadows.

## Structural Requirements:
- **Sticky Navigation**: A slim, translucent top bar with the hotel/casino name and a primary CTA button.
- **Hero Section**: A powerful "Editorial Headline" with the campaign name, followed by a concise value proposition. Use an animated gradient or geometric pattern background.
- **Narrative Flow**: Use single-column text blocks for the campaign philosophy and multi-column grids for details/benefits.
- **Social Proof/Exclusivity**: A dedicated section for "Invitation Tiers" or "Limited Availability" to create urgency and prestige.
- **QR Code Section**: Include a QR code for mobile access using: <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://example.com" alt="QR Code">
- **Footer**: Hotel/casino branding with contact information.

## Theme Presets (Apply based on the theme provided):
- **Luxury Gold**: Slate-950 background, Amber-500/600 accents, warm gold tones throughout.
- **Festive Red**: Deep Maroon/Dark Red backgrounds, Silver/White accents, festive yet professional luxury.
- **Modern Black**: Pure Black/Slate-950 backgrounds, Neutral Gray/White accents, ultra-minimalist.
- **Classic Casino**: Deep Forest Green/Emerald backgrounds, Gold accents, traditional high-stakes elegance.

## Technical Constraints:
- Single self-contained HTML file with embedded <style> and <script> tags.
- Use Tailwind CSS via CDN (https://cdn.tailwindcss.com) for all styling.
- Include Google Fonts CDN for Manrope and Inter.
- Ensure all sections are fully responsive with mobile-first design.
- Use Semantic HTML5 tags.
- Include CSS animations: fade-ins on scroll, animated gradient backgrounds, hover transforms.
- Support both English and Chinese text.

## Output Format:
Return ONLY the complete HTML code, starting with <!DOCTYPE html> and ending with </html>.
Do not include any explanations, comments outside the code, or markdown code blocks."""


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


async def generate_html_with_streaming(
    campaign_name: str,
    campaign_description: str,
    hotel_name: str,
    theme: str,
    start_date: str,
    end_date: str
) -> str:
    """Generate landing page HTML using streaming to avoid timeout."""

    theme_config = CAMPAIGN_THEMES.get(theme, CAMPAIGN_THEMES["luxury_gold"])

    date_info = ""
    if start_date and end_date:
        date_info = f"\n- Campaign Period: {start_date} to {end_date}"

    user_prompt = f"""Create an Editorial Architect-style landing page for a luxury casino marketing campaign.

## Campaign Details:
- **Campaign Name:** {campaign_name}
- **Description:** {campaign_description}
- **Hotel/Casino:** {hotel_name}
- **Selected Theme:** {theme_config['name']}{date_info}

## Theme Colors:
- Primary: {theme_config['primary_color']}
- Secondary: {theme_config['secondary_color']}
- Accent: {theme_config['accent_color']}
- Background: {theme_config['background']}
- Text: {theme_config['text_color']}
- Button: {theme_config['button_color']}
- Button Text: {theme_config['button_text']}

## Required Sections:
1. **Sticky Nav** — translucent top bar with "{hotel_name}" branding and a "Request Access" CTA button
2. **Hero Section** — Large editorial headline with "{campaign_name}" and a compelling one-line value proposition beneath. Use an animated gradient or geometric pattern background with the theme colors.
3. **The Offer** — Single-column narrative block explaining the campaign: {campaign_description}. Use generous whitespace and elegant typography.
4. **Campaign Dates** — Display **{start_date} to {end_date}** prominently as an exclusive "Limited Window" banner or countdown-style element.
5. **Curated Benefits** — Multi-column grid (3-4 cards) highlighting key benefits. Use subtle icons or decorative elements.
6. **Invitation Tier / Exclusivity** — A section conveying urgency and prestige (e.g., "Limited to Select Members", "By Invitation Only").
7. **Call to Action** — Large, prominent CTA button with hover animation.
8. **QR Code** — Mobile access section with: <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://example.com" alt="QR Code">
9. **Footer** — {hotel_name} branding, address line, and contact link.

## Language:
- Primary text in English with luxury editorial copywriting
- Include Chinese (中文) translations for the hero headline and CTA button
- Use the ACTUAL campaign dates ({start_date} to {end_date}), never placeholders

Generate the complete HTML file now:"""

    url = f"{CODE_MODEL_ENDPOINT}/chat/completions"
    headers = {
        "Content-Type": "application/json"
    }
    if CODE_MODEL_TOKEN:
        headers["Authorization"] = f"Bearer {CODE_MODEL_TOKEN}"

    payload = {
        "model": CODE_MODEL_NAME,
        "messages": [
            {"role": "system", "content": CODER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 8000,
        "stream": True
    }

    html_content = ""

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
                                html_content += content
                    except json.JSONDecodeError:
                        continue

    if html_content.startswith("```html"):
        html_content = html_content[7:]
    if html_content.startswith("```"):
        html_content = html_content[3:]
    if html_content.endswith("```"):
        html_content = html_content[:-3]

    return html_content.strip()


class CreativeProducerAgent:
    """Pure business logic for the Creative Producer agent."""

    async def generate(self, params: dict) -> dict:
        """Generate a landing page from campaign parameters.

        Args:
            params: dict with keys campaign_id, campaign_name, campaign_description,
                    hotel_name, theme, start_date, end_date

        Returns:
            dict with keys html, status, and optionally error
        """
        campaign_id = params.get("campaign_id", "unknown")

        await publish_event(
            campaign_id=campaign_id,
            event_type="agent_started",
            agent="Creative Producer",
            task="Generating landing page"
        )

        try:
            html = await generate_html_with_streaming(
                campaign_name=params["campaign_name"],
                campaign_description=params["campaign_description"],
                hotel_name=params["hotel_name"],
                theme=params["theme"],
                start_date=params["start_date"],
                end_date=params["end_date"]
            )

            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_completed",
                agent="Creative Producer",
                task="Landing page generated",
                data={"html_length": len(html)}
            )

            return {"html": html, "status": "success"}

        except Exception as e:
            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_error",
                agent="Creative Producer",
                task="Generation failed",
                data={"error": str(e)}
            )

            return {"html": "", "status": "error", "error": str(e)}
