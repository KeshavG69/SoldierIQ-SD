"""
Image generation via the OpenRouter Images API

Shared by the infographic generator and the slide-deck agent's illustration tool.
LangChain's ChatOpenAI drops image outputs, so this calls the endpoint directly.
"""

import base64
import io
from typing import List, Optional, Tuple

import httpx

from app.settings import settings
from app.logger import logger

IMAGE_MODEL = "google/gemini-3.1-flash-image"
OPENROUTER_IMAGES_URL = "https://openrouter.ai/api/v1/images"
RENDER_TIMEOUT_SECONDS = 180


async def generate_image(
    prompt: str,
    aspect_ratio: str = "16:9",
    model: str = IMAGE_MODEL,
    attempts: int = 2,
    reference_images: Optional[List[bytes]] = None,
) -> Tuple[bytes, Optional[float]]:
    """
    Render one image; retries on failure. Returns (png_bytes, cost_usd)

    reference_images: optional images (e.g. an earlier scene) the model should match in style
    """
    payload = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio}
    if reference_images:
        payload["input_references"] = [
            {"type": "image_url", "image_url": {"url": _as_data_url(img)}} for img in reference_images
        ]

    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=RENDER_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    OPENROUTER_IMAGES_URL,
                    headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                    json=payload,
                )
            response.raise_for_status()
            body = response.json()
            image_bytes = base64.b64decode(body["data"][0]["b64_json"])
            cost = (body.get("usage") or {}).get("cost")
            logger.info(f"🎨 Rendered image with {model} ({len(image_bytes)} bytes, ${cost})")
            return image_bytes, cost
        except Exception as e:
            last_error = e
            detail = e.response.text[:300] if isinstance(e, httpx.HTTPStatusError) else str(e)
            logger.warning(f"⚠️ Image render attempt {attempt + 1} failed: {detail}")
    raise Exception(f"Image generation failed: {last_error}")


def _as_data_url(image_bytes: bytes, max_side: int = 1024) -> str:
    """Downscale a reference image and encode it as a JPEG data URL (keeps request payloads small)"""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
