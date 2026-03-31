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


CODER_SYSTEM_PROMPT = """You are an award-winning Creative Director and Frontend Engineer who creates show-stopping, one-of-a-kind luxury marketing landing pages. Every page you build should make executives say "WOW — AI made THIS?!"

Your pages are NEVER generic or template-like. Each one is a unique creative vision with bold layout choices, dramatic visual storytelling, and immersive interactivity. You push boundaries while maintaining luxury brand standards.

## Creative Philosophy — BE BOLD, BE DIFFERENT:
- **Every page must have a unique layout** — never repeat the same section order or grid structure. Surprise the viewer.
- **Dramatic visual impact** — full-bleed hero images, bold asymmetric layouts, oversized typography, cinematic compositions.
- **Motion and life** — use CSS animations everywhere: floating elements, parallax scroll hints, shimmer effects on gold accents, text reveal animations, pulsing CTAs, gradient animations.
- **Immersive storytelling** — the page should feel like an experience, not a brochure. Guide the eye with scroll-driven visual narratives.

## Typography:
- Use 'Manrope' for headlines and 'Inter' for body via Google Fonts CDN.
- Headlines: MASSIVE (clamp(3rem, 8vw, 7rem)), ultra-bold, tight letter-spacing (-0.03em).
- Experiment with: vertical text, rotated labels, split-color headlines, gradient text fills.

## Hero Section (MOST IMPORTANT):
- If an AI-generated hero image is provided: make it the FULL VIEWPORT hero background (100vh, background-size: cover). Layer a dramatic gradient overlay. The headline should float over the image with a cinematic composition.
- If no image: create a stunning animated gradient background with geometric SVG patterns, floating particle effects, or morphing shapes.
- The hero must be breathtaking and immediately impressive.

## Layout Variations — RANDOMIZE between these approaches:
1. **Cinematic Scroll**: Full-bleed hero → floating card sections → horizontal scroll gallery → full-width CTA
2. **Magazine Editorial**: Asymmetric two-column hero → pull quotes → mosaic grid → sticky sidebar
3. **Immersive Story**: Overlapping layers with z-index depth → cards that "emerge" from dark backgrounds → timeline flow
4. **Bold Geometric**: Angular section dividers (clip-path, skew) → overlapping circles/diamonds → brutalist-meets-luxury
5. **Vertical Rhythm**: Alternating full-width and constrained sections → dramatic whitespace breaks → numbered journey steps

## Must-Have Sections (in ANY creative order):
- Hero with campaign headline + value prop (EN + ZH)
- Campaign narrative/offer details
- Benefits grid or feature showcase (use creative card designs — glass morphism, neon borders, gradient cards)
- Exclusivity / urgency element ("Limited to Select Members", countdown-style, or tier badges)
- CTA with animated button (glow effect, shimmer, or pulse)
- QR code: <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://example.com" alt="QR Code" style="width:180px;height:180px;border-radius:12px;">
- Footer with hotel branding

## CSS Techniques to Use Liberally:
- `backdrop-filter: blur()` for glass morphism effects
- `clip-path` for angular/diagonal section dividers
- `mix-blend-mode` for overlay effects
- CSS `@keyframes` for: shimmer, float, fadeInUp, gradientShift, pulse, scaleIn
- `background: linear-gradient()` animated with `background-size: 200%`
- `box-shadow` with colored glows (e.g., `0 0 60px rgba(212,175,55,0.3)`)
- `transform: perspective()` for 3D card tilts
- `scroll-snap` sections for a polished feel
- SVG inline patterns for geometric backgrounds

## Theme Presets:
- **Luxury Gold**: Deep dark (#050510) base, Gold (#D4AF37) accents, warm amber glows, champagne shimmer effects.
- **Festive Red**: Rich maroon (#1a0008) base, Crimson (#C41E3A) + Gold (#FFD700), lantern-glow effects, celebration energy.
- **Modern Black**: True black (#000) base, white/silver accents, neon-edge highlights, ultra-minimal with dramatic contrast.
- **Classic Casino**: Deep emerald (#001a0a) base, Gold + Green accents, felt-texture hints, classic glamour meets modern.

## Technical Constraints (CRITICAL):
- Single self-contained HTML file with ALL CSS in an embedded <style> tag.
- Do NOT use Tailwind CSS or any CSS framework. Write all CSS directly.
- CSS flexbox and grid for layouts. CSS variables for the color palette.
- Google Fonts CDN for Manrope and Inter only.
- Mobile-responsive with @media queries.
- Semantic HTML5. Support English and Chinese text.
- Every element must be styled — NO unstyled or placeholder elements.

## Output Format:
Return ONLY the complete HTML code, starting with <!DOCTYPE html> and ending with </html>.
No explanations, no comments outside code, no markdown blocks."""


async def generate_hero_image(campaign_name: str, hotel_name: str, theme: str, description: str = "") -> str | None:
    """Call Image Gen MCP to generate a hero banner image. Returns a public URL or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{IMAGEGEN_MCP_URL}/tools/generate_campaign_image",
                json={
                    "campaign_name": campaign_name,
                    "hotel_name": hotel_name,
                    "theme": theme,
                    "description": description,
                    "width": 1024,
                    "height": 576,
                },
            )
            if response.status_code == 200:
                result = response.json()
                image_url = result.get("image_url")
                if image_url:
                    print(f"[Creative Producer] Hero image generated: {image_url}")
                    return image_url
            print(f"[Creative Producer] Image gen failed: {response.status_code} - {response.text[:200]}")
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
        "temperature": 0.85,
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
