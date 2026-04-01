"""
Image Generation MCP Server - Wraps vLLM-Omni for AI image generation.

Provides tools for generating marketing campaign images via FLUX.1-schnell
served by vLLM-Omni. Generated images are stored in memory and served
at /images/{image_id}.png for easy embedding in landing pages.
"""
import os
import uuid
import base64
import time
import httpx
from typing import Optional
from fastmcp import FastMCP

mcp = FastMCP("Image Generation MCP")

IMAGEGEN_MODEL_ENDPOINT = os.environ.get(
    "IMAGEGEN_MODEL_ENDPOINT",
    "https://flux2-klein-4b-0-marketing-assistant-demo.apps.cluster-qf44v.qf44v.sandbox543.opentlc.com/v1"
)
IMAGEGEN_MODEL_NAME = os.environ.get("IMAGEGEN_MODEL_NAME", "flux2-klein-4b")
IMAGEGEN_MODEL_TOKEN = os.environ.get("IMAGEGEN_MODEL_TOKEN", "")
SELF_URL = os.environ.get("IMAGEGEN_MCP_SELF_URL", "http://imagegen-mcp:8091")

image_store: dict[str, bytes] = {}
MAX_STORE_SIZE = 50

THEME_PROMPTS = {
    "luxury_gold": "golden champagne tones, warm amber lighting, elegant marble and crystal, luxurious atmosphere",
    "festive_red": "vibrant crimson and gold, festive lanterns, celebration atmosphere, rich silk textures",
    "modern_black": "sleek monochrome, silver accents, futuristic minimalism, dramatic shadows, architectural lines",
    "classic_casino": "deep emerald green felt, gold and brass accents, classic elegance, vintage glamour",
}


def _build_prompt(campaign_name: str, hotel_name: str, theme: str, description: str = "") -> str:
    theme_style = THEME_PROMPTS.get(theme, THEME_PROMPTS["luxury_gold"])
    return (
        f"Professional luxury casino hotel interior and exterior photography, {theme_style}. "
        f"Night cityscape of Macau skyline backdrop, premium VIP atmosphere, "
        f"cinematic lighting, photorealistic, ultra high quality, 4K resolution, "
        f"wide banner composition. "
        f"ABSOLUTELY NO TEXT, NO WORDS, NO LETTERS, NO LOGOS, NO WATERMARKS, NO TYPOGRAPHY in the image. "
        f"Pure photography only, no graphic design elements."
    )


def _cleanup_store():
    if len(image_store) > MAX_STORE_SIZE:
        oldest_keys = list(image_store.keys())[: len(image_store) - MAX_STORE_SIZE]
        for k in oldest_keys:
            del image_store[k]


async def _call_imagegen_api(prompt: str, width: int = 1024, height: int = 576) -> bytes:
    """Call vLLM-Omni image generation API and return raw PNG bytes."""
    url = f"{IMAGEGEN_MODEL_ENDPOINT}/images/generations"
    headers = {"Content-Type": "application/json"}
    if IMAGEGEN_MODEL_TOKEN:
        headers["Authorization"] = f"Bearer {IMAGEGEN_MODEL_TOKEN}"

    payload = {
        "model": IMAGEGEN_MODEL_NAME,
        "prompt": prompt,
        "size": f"{width}x{height}",
        "response_format": "b64_json",
        "n": 1,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Image generation API error: {response.status_code} - {response.text}")
        data = response.json()
        b64_data = data["data"][0]["b64_json"]
        return base64.b64decode(b64_data)


@mcp.tool
async def generate_campaign_image(
    campaign_name: str,
    hotel_name: str = "Simon Casino Resort",
    theme: str = "luxury_gold",
    description: str = "",
    width: int = 1024,
    height: int = 576,
) -> dict:
    """
    Generate a marketing hero banner image for a campaign.

    Uses FLUX.1-schnell via vLLM-Omni to create a theme-aware
    marketing banner. Returns a URL to the generated image.

    Args:
        campaign_name: Name of the marketing campaign
        hotel_name: Hotel/casino name for branding
        theme: Visual theme (luxury_gold, festive_red, modern_black, classic_casino)
        description: Optional campaign description for prompt context
        width: Image width in pixels (default 1024)
        height: Image height in pixels (default 576 for banner ratio)

    Returns:
        Dict with image_url, image_id, and status
    """
    prompt = _build_prompt(campaign_name, hotel_name, theme, description)
    image_bytes = await _call_imagegen_api(prompt, width, height)

    image_id = f"img-{uuid.uuid4().hex[:12]}"
    image_store[image_id] = image_bytes
    _cleanup_store()

    image_url = f"{SELF_URL}/images/{image_id}.png"
    return {
        "image_url": image_url,
        "image_id": image_id,
        "prompt": prompt,
        "status": "success",
    }


@mcp.tool
async def generate_campaign_image_b64(
    campaign_name: str,
    hotel_name: str = "Simon Casino Resort",
    theme: str = "luxury_gold",
    description: str = "",
    width: int = 1024,
    height: int = 576,
) -> dict:
    """
    Generate a marketing hero banner and return as base64.

    Same as generate_campaign_image but returns the image inline
    as a base64 data URI for direct HTML embedding.

    Args:
        campaign_name: Name of the marketing campaign
        hotel_name: Hotel/casino name for branding
        theme: Visual theme (luxury_gold, festive_red, modern_black, classic_casino)
        description: Optional campaign description for prompt context
        width: Image width in pixels
        height: Image height in pixels

    Returns:
        Dict with data_uri, image_id, and status
    """
    prompt = _build_prompt(campaign_name, hotel_name, theme, description)
    image_bytes = await _call_imagegen_api(prompt, width, height)

    image_id = f"img-{uuid.uuid4().hex[:12]}"
    image_store[image_id] = image_bytes
    _cleanup_store()

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:image/png;base64,{b64}"
    return {
        "data_uri": data_uri,
        "image_id": image_id,
        "prompt": prompt,
        "status": "success",
    }


if __name__ == "__main__":
    import argparse
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import JSONResponse, Response
    from starlette.requests import Request

    parser = argparse.ArgumentParser(description="Image Generation MCP Server")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()

    async def serve_image(request: Request):
        filename = request.path_params["filename"]
        image_id = filename.replace(".png", "")
        if image_id not in image_store:
            return JSONResponse({"error": "Image not found"}, status_code=404)
        return Response(
            content=image_store[image_id],
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def health(request: Request):
        return JSONResponse({
            "status": "healthy",
            "service": "Image Generation MCP",
            "model_endpoint": IMAGEGEN_MODEL_ENDPOINT,
            "stored_images": len(image_store),
        })

    from starlette.routing import Mount
    mcp_asgi = mcp.http_app(path="/mcp")

    app = Starlette(
        routes=[
            Route("/healthz", health, methods=["GET"]),
        Route("/readyz", health, methods=["GET"]),
            Route("/images/{filename}", serve_image, methods=["GET"]),
            Mount("/", app=mcp_asgi),
        ],
        lifespan=mcp_asgi.lifespan,
    )

    print(f"[ImageGen MCP] Starting server on 0.0.0.0:{args.port}")
    print(f"[ImageGen MCP] MCP endpoint: http://0.0.0.0:{args.port}/mcp")
    print(f"[ImageGen MCP] Image serving: http://0.0.0.0:{args.port}/images/")
    print(f"[ImageGen MCP] Model endpoint: {IMAGEGEN_MODEL_ENDPOINT}")
    uvicorn.run(app, host="0.0.0.0", port=args.port)
