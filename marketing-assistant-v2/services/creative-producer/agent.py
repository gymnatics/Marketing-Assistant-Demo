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


CODER_SYSTEM_PROMPT = """You are an expert frontend developer specializing in luxury marketing landing pages for high-end casinos and resorts in Macau.

Your task is to generate a complete, responsive, single-page HTML file with embedded CSS and JavaScript for a marketing campaign. The result must feel luxurious, exclusive, and visually impressive.

## Design Requirements:
1. Create a visually stunning, mobile-responsive landing page that feels luxurious and exclusive
2. Use the provided color scheme consistently throughout with elegant gradients
3. Include smooth CSS animations, hover effects, and scroll-triggered fade-ins
4. Use modern CSS features: flexbox, grid, CSS variables, backdrop-filter
5. Add a prominent, animated call-to-action button with hover glow effects
6. Include a QR code section using: <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://example.com" alt="QR Code" style="width:160px;height:160px;border-radius:12px;">
7. Support both English and Chinese text with elegant bilingual typography
8. Use Google Fonts (e.g., Playfair Display for headings, Inter for body)
9. Include subtle background effects: animated gradients, particle effects, or geometric patterns
10. Add decorative elements: gold borders, subtle shadows, glass-morphism cards

## Page Sections (in order):
1. Hero section with campaign headline, tagline, and a stunning animated gradient/pattern background
2. Campaign details section explaining the offer with elegant typography and icons
3. Benefits/features section with visual cards (use CSS icons or Unicode symbols)
4. Campaign dates prominently displayed with a countdown-style design
5. Call-to-action section with a prominent, animated button
6. QR code section for mobile access
7. Footer with hotel/casino branding and contact info

## Technical Requirements:
- Single HTML file with embedded <style> and <script> tags
- NO external dependencies except Google Fonts CDN
- Mobile-first responsive design with media queries
- Smooth scroll behavior
- CSS @keyframes animations for hero background and element entrances
- High contrast for readability
- Minimum 800 lines of well-structured HTML/CSS/JS

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

    user_prompt = f"""Create a visually impressive luxury marketing landing page with the following details:

## Campaign Information:
- **Campaign Name:** {campaign_name}
- **Description:** {campaign_description}
- **Hotel/Casino:** {hotel_name}
- **Theme:** {theme_config['name']}{date_info}

## Color Scheme (use consistently with gradients):
- Primary Color: {theme_config['primary_color']}
- Secondary Color: {theme_config['secondary_color']}
- Accent Color: {theme_config['accent_color']}
- Background Color: {theme_config['background']}
- Text Color: {theme_config['text_color']}
- Button Color: {theme_config['button_color']}
- Button Text Color: {theme_config['button_text']}

## Page Sections to Create:
1. Hero section with campaign headline, a compelling tagline, and a stunning animated gradient background using the primary and secondary colors
2. Campaign details section explaining the offer with elegant typography and decorative dividers
3. Display the campaign dates prominently: **{start_date} to {end_date}** — style these as an eye-catching banner or countdown-style element
4. Benefits/features section with 3-4 visual cards (use Unicode icons like ★ ◆ ♠ ♦ or CSS-drawn icons)
5. Call-to-action section with a large, animated button with hover glow effects
6. QR code section with: <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://example.com" alt="QR Code" style="width:160px;height:160px;border-radius:12px;">
7. Footer with {hotel_name} branding, address, and a "Contact Us" link

## Language:
- Primary text in English with elegant luxury copywriting
- Include Chinese (中文) translations for key headings and the CTA
- Hotel name: {hotel_name}

## Style Notes:
- Make it feel like a 5-star resort invitation — luxurious, exclusive, premium
- Use CSS animations: fade-ins on scroll, animated gradient backgrounds, hover transforms
- Glass-morphism cards with backdrop-filter where appropriate
- Gold/metallic accents if the theme supports it
- Minimum 800 lines of polished HTML/CSS/JS

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
