"""
Creative Producer A2A Agent - Generates luxury marketing landing pages.

Uses Qwen2.5-Coder-32B-FP8 model for HTML/CSS/JS generation.
"""
import os
import json
import httpx
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.models import (
    CAMPAIGN_THEMES,
    GenerateLandingPageInput,
    GenerateLandingPageOutput
)


app = FastAPI(title="Creative Producer Agent")

AGENT_CARD = {
    "name": "Creative Producer",
    "description": "Generates luxury marketing landing pages with HTML/CSS/JS",
    "version": "1.0.0",
    "protocol_version": "0.3.0",
    "skills": [
        {
            "name": "generate_landing_page",
            "description": "Create a luxury marketing landing page for casino campaigns",
            "input_schema": GenerateLandingPageInput.model_json_schema()
        }
    ]
}

CODE_MODEL_ENDPOINT = os.environ.get(
    "CODE_MODEL_ENDPOINT",
    "https://qwen25-coder-32b-fp8-0-marketing-assistant-demo.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com/v1"
)
CODE_MODEL_NAME = os.environ.get("CODE_MODEL_NAME", "qwen25-coder-32b-fp8")
CODE_MODEL_TOKEN = os.environ.get("CODE_MODEL_TOKEN", "")
EVENT_HUB_URL = os.environ.get("EVENT_HUB_URL", "http://event-hub:5001")


CODER_SYSTEM_PROMPT = """You are an expert frontend developer specializing in luxury casino marketing landing pages.

Your task is to generate a complete, self-contained HTML page with embedded CSS and JavaScript.

## Requirements:
1. Create a visually stunning, mobile-responsive landing page
2. Use the provided color scheme and theme
3. Include smooth animations and transitions
4. Add a prominent call-to-action button
5. Include QR code placeholder area
6. Support both English and Chinese text
7. Use elegant typography (Google Fonts)
8. Include subtle background effects (gradients, patterns)

## Technical Requirements:
- Single HTML file with embedded <style> and <script>
- No external dependencies except Google Fonts
- Mobile-first responsive design
- Smooth scroll behavior
- Animated elements on scroll
- High contrast for readability

## Output Format:
Return ONLY the complete HTML code, starting with <!DOCTYPE html> and ending with </html>.
Do not include any explanation or markdown formatting."""


class InvokeRequest(BaseModel):
    skill: str
    params: dict


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
    
    user_prompt = f"""Create a luxury marketing landing page for:

## Campaign Details:
- Campaign Name: {campaign_name}
- Description: {campaign_description}
- Hotel/Casino: {hotel_name}{date_info}

## Theme: {theme_config['name']}
- Primary Color: {theme_config['primary_color']}
- Secondary Color: {theme_config['secondary_color']}
- Accent Color: {theme_config['accent_color']}
- Background: {theme_config['background']}
- Text Color: {theme_config['text_color']}
- Button Color: {theme_config['button_color']}
- Button Text: {theme_config['button_text']}

## Content Requirements:
1. Hero section with campaign name and tagline
2. Benefits/features section (3-4 items)
3. Campaign dates prominently displayed: {start_date} to {end_date}
4. Call-to-action button
5. QR code placeholder section
6. Footer with hotel name

## Language:
- Primary text in English
- Include Chinese translations where appropriate
- Hotel name: {hotel_name}

Generate the complete HTML page now:"""

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


@app.get("/.well-known/agent-card.json")
async def get_agent_card():
    """Return agent capabilities for A2A discovery."""
    return JSONResponse(content=AGENT_CARD)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "agent": "Creative Producer"}


@app.post("/a2a/invoke")
async def invoke_skill(request: InvokeRequest):
    """Invoke an agent skill via A2A protocol."""
    
    if request.skill != "generate_landing_page":
        raise HTTPException(status_code=400, detail=f"Unknown skill: {request.skill}")
    
    try:
        params = GenerateLandingPageInput(**request.params)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {e}")
    
    campaign_id = request.params.get("campaign_id", "unknown")
    
    await publish_event(
        campaign_id=campaign_id,
        event_type="agent_started",
        agent="Creative Producer",
        task="Generating landing page"
    )
    
    try:
        html = await generate_html_with_streaming(
            campaign_name=params.campaign_name,
            campaign_description=params.campaign_description,
            hotel_name=params.hotel_name,
            theme=params.theme,
            start_date=params.start_date,
            end_date=params.end_date
        )
        
        result = GenerateLandingPageOutput(html=html, status="success")
        
        await publish_event(
            campaign_id=campaign_id,
            event_type="agent_completed",
            agent="Creative Producer",
            task="Landing page generated",
            data={"html_length": len(html)}
        )
        
        return result.model_dump()
        
    except Exception as e:
        await publish_event(
            campaign_id=campaign_id,
            event_type="agent_error",
            agent="Creative Producer",
            task="Generation failed",
            data={"error": str(e)}
        )
        
        return GenerateLandingPageOutput(
            html="",
            status="error",
            error=str(e)
        ).model_dump()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8081))
    uvicorn.run(app, host="0.0.0.0", port=port)
