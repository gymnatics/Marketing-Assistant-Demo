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
IMAGEGEN_MCP_URL = os.environ.get("IMAGEGEN_MCP_URL", "http://imagegen-mcp:8091")


CODER_SYSTEM_PROMPT = """You are a world-class Creative Director who builds luxury marketing landing pages. Your pages are visually stunning, with bold typography, smooth animations, and a premium feel.

## STRICT STRUCTURE (follow this exact section order):

1. **Sticky Nav** — Translucent top bar with hotel name on the left + "Book Now 立即预订" CTA button on the right. Use `overflow: visible`, `padding: 0 2rem`, and ensure the button has `white-space: nowrap` so it is NEVER cut off.
2. **Hero Section** (100vh) — Full-viewport with massive headline, value proposition, and Chinese translation. Include `{{GREETING}}` (e.g., "Dear John" or "尊敬的张伟") and a `{{CUSTOMER_TIER_BADGE}}` badge (e.g., "Platinum VIP") prominently in the hero so the visitor immediately feels recognized. If a hero image URL is provided, use it as background-image with a dark overlay. Otherwise use an animated gradient.
3. **Personalized Offer** — "{{CUSTOMER_FIRST_NAME}}, as a {{CUSTOMER_TIER_BADGE}}, you have exclusive access to..." — this section introduces what benefits the customer gets. It comes BEFORE the benefits grid to set the context.
4. **Benefits Grid** — 3-4 cards in a responsive grid showing the specific benefits mentioned in the offer above. Use glassmorphism (backdrop-filter: blur, semi-transparent backgrounds, subtle borders)
5. **Campaign Story** — Centered text block explaining the campaign/offer with generous padding
6. **Campaign Dates** — Prominent date display as a styled banner or badge ("Limited Window" urgency)
7. **CTA Section** — Large animated "Book Now 立即预订" button with glow/pulse effect. Make it look like a real booking button.
8. **QR Code** — Centered: <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://example.com" alt="QR Code" style="width:180px;height:180px;border-radius:12px;">
9. **Footer** — Hotel branding, address, contact

## DESIGN RULES:

**Typography:**
- Google Fonts: 'Manrope' for headlines, 'Inter' for body
- Headlines: large (clamp(2.5rem, 6vw, 5rem)), bold, tight letter-spacing
- Body: 1.1rem, relaxed line-height

**Colors (use CSS variables):**
- Apply the provided theme colors consistently throughout
- Dark backgrounds, light text, accent colors for buttons and highlights
- EVERY section must have a styled background — no white/unstyled sections

**Animations:**
- Hero: subtle gradient animation or parallax hint
- Cards: hover scale + shadow transitions
- CTA button: pulse or shimmer @keyframes animation
- Sections: fadeInUp on scroll (use CSS animation-delay for stagger)

**Layout:**
- Use CSS flexbox and grid
- Full-width sections with max-width inner containers (1200px)
- Generous padding (80px-120px vertical) between sections
- Diagonal section dividers using clip-path on 1-2 sections for visual interest

## Theme Presets:
- **Luxury Gold**: Dark (#050510) base, Gold (#D4AF37) accents, warm amber glows
- **Festive Red**: Maroon (#1a0008) base, Crimson (#C41E3A) + Gold (#FFD700), warm celebration feel
- **Modern Black**: Black (#000) base, white/silver accents, ultra-minimal, high contrast
- **Classic Casino**: Emerald (#001a0a) base, Gold + Green accents, classic glamour

## PERSONALIZATION PLACEHOLDERS (use these EXACTLY as written):
- `{{GREETING}}` — personalized greeting (e.g., "Dear John Smith" or "尊敬的张伟")
- `{{CUSTOMER_NAME}}` — full name
- `{{CUSTOMER_FIRST_NAME}}` — first name only
- `{{CUSTOMER_TIER_BADGE}}` — tier label (e.g., "Platinum VIP", "Diamond Elite")
- `{{CUSTOMER_TIER}}` — raw tier (e.g., "Platinum")
- These will be replaced server-side with real customer data. Use them in the HTML exactly as shown with double curly braces.

## CRITICAL TECHNICAL RULES:
- Single self-contained HTML file. ALL CSS in one embedded <style> tag.
- NO Tailwind, NO CSS frameworks. Write all CSS directly.
- CSS variables for colors. Mobile-responsive with @media queries.
- Semantic HTML5. Bilingual: use English as the PRIMARY language for all text, with Chinese (中文) as a SMALLER subtitle/line below. Be CONSISTENT — every section should follow the same pattern: English headline first, Chinese translation smaller below. Never mix languages randomly within the same line.
- EVERY element must be fully styled. NO white gaps, NO unstyled sections, NO broken layouts.
- The page must look complete and polished from top to bottom.
- NAV BAR CSS (MANDATORY — include this EXACTLY):
  ```css
  nav, .nav, header { display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; overflow: visible !important; }
  nav a, nav button, .nav a, .nav button, header a, header button { white-space: nowrap; flex-shrink: 0; }
  ```

## Output:
Return ONLY the complete HTML, starting with <!DOCTYPE html> and ending with </html>. No explanations, no markdown."""


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


async def generate_html_with_streaming(
    campaign_name: str,
    campaign_description: str,
    hotel_name: str,
    theme: str,
    start_date: str,
    end_date: str,
    hero_image_url: str | None = None
) -> str:
    """Generate landing page HTML using streaming to avoid timeout."""

    theme_config = CAMPAIGN_THEMES.get(theme, CAMPAIGN_THEMES["luxury_gold"])

    date_info = ""
    if start_date and end_date:
        date_info = f"\n- Campaign Period: {start_date} to {end_date}"

    hero_image_section = ""
    if hero_image_url:
        hero_image_section = """
## AI-Generated Hero Image (MUST USE):
- An AI-generated hero banner image has been created for this campaign.
- You MUST use it as the hero section background: `background-image: url('HERO_IMAGE_PLACEHOLDER'); background-size: cover; background-position: center;`
- Use EXACTLY the string `HERO_IMAGE_PLACEHOLDER` as the URL — it will be replaced with the actual image after generation.
- Add a semi-transparent dark overlay (rgba(0,0,0,0.4)) on top for text readability
- Make the hero section full-viewport height (100vh) to showcase the image prominently
- The image is the visual centerpiece — design the page around it
"""

    user_prompt = f"""Create a STUNNING, one-of-a-kind luxury landing page for this campaign. Make it visually breathtaking — this is for a C-suite demo showcasing AI creativity.

## Campaign Brief:
- **Campaign:** {campaign_name}
- **Story:** {campaign_description}
- **Venue:** {hotel_name}
- **Theme:** {theme_config['name']}{date_info}
{hero_image_section}
## Color Palette:
- Primary: {theme_config['primary_color']}
- Secondary: {theme_config['secondary_color']}
- Accent: {theme_config['accent_color']}
- Background: {theme_config['background']}
- Text: {theme_config['text_color']}
- Button: {theme_config['button_color']}
- Button Text: {theme_config['button_text']}

## Creative Direction:
Create something UNIQUE and IMPRESSIVE. Choose a bold layout approach — asymmetric grids, overlapping sections, cinematic hero, diagonal dividers, floating cards, anything that says "an AI designed this and it's amazing."

Include these elements (in any creative order — surprise me with the arrangement):
- **Epic Hero** — Full-viewport (100vh), {campaign_name} as a massive headline with Chinese translation, compelling value prop
- **Campaign Story** — {campaign_description} — present it as an immersive narrative, not a boring text block
- **Date Showcase** — {start_date} to {end_date} — make the dates feel exclusive (countdown style, "Limited Window", or elegant badge)
- **Benefits/Features** — 3-4 cards with creative designs (glassmorphism, gradient borders, 3D tilt, neon glow — pick one style)
- **Exclusivity** — urgency element ("By Invitation Only", "Limited to Select Members", tier badges)
- **CTA** — animated button with glow/shimmer/pulse effect
- **QR Code** — <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://example.com" alt="QR Code">
- **Footer** — {hotel_name} branding

## Language:
- Primary: English with luxury editorial copywriting (think Ritz-Carlton meets Apple)
- Hero headline + CTA: include Chinese (中文) translations
- Use actual dates ({start_date} to {end_date}), never placeholders

## IMPORTANT: Make this page dramatically different from a standard corporate template. Use creative CSS animations, bold typography, and a layout that showcases AI creativity.

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
        "temperature": 0.75,
        "max_tokens": 12000,
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

    html_content = html_content.strip()

    if hero_image_url and "HERO_IMAGE_PLACEHOLDER" in html_content:
        html_content = html_content.replace("HERO_IMAGE_PLACEHOLDER", hero_image_url)
        print(f"[Creative Producer] Injected hero image URL into HTML: {hero_image_url[:80]}")

    return html_content


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
            task="Generating hero image with AI"
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
                    task="Hero image generated",
                    data={"image_url": hero_image_url}
                )
            else:
                await publish_event(
                    campaign_id=campaign_id,
                    event_type="workflow_status",
                    agent="Creative Producer",
                    task="Image gen unavailable, using CSS gradients"
                )

            await publish_event(
                campaign_id=campaign_id,
                event_type="agent_started",
                agent="Creative Producer",
                task="Generating landing page HTML"
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
