from __future__ import annotations

import base64
import json
import logging
from typing import Any

from wardrobe_pipeline.config.settings import settings

logger = logging.getLogger(__name__)


_PROMPT = """You are analyzing a single clothing item image with a transparent background.
Return ONLY valid JSON (no markdown, no explanation).

Required fields:
- type: string (shirt, trousers, jeans, jacket, coat, sweater, hoodie, dress, skirt, shorts, blazer, other)
- gender: "male" or "female" (pick the best fit)
- category: "top" or "bottom" or "outerwear"
- color: string (primary visible color)
- pattern: string (solid, striped, checked, floral, graphic, textured, other)
- fit: string (slim, regular, oversized, other)
- formality: string (casual, semi-casual, formal, other)

Optional fields:
- sleeve_type: string
- length: string
- compatible_with: array of strings (types or categories it pairs well with)

If uncertain, use "other" or "unknown" but still fill required fields.
"""


def _data_url_png(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def extract_metadata_from_png(png_bytes: bytes) -> dict[str, Any]:
    if not settings.kyra_openai_api_key:
        raise RuntimeError("KYRA_OPENAI_API_KEY is not set")

    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError(f"openai SDK not available: {e}") from e

    client = OpenAI(api_key=settings.kyra_openai_api_key)

    # Use the Responses API shape (current OpenAI Python SDK).
    # If the SDK changes, this is the only place to adapt.
    resp = client.responses.create(
        model=settings.openai_model_vision,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": _PROMPT},
                    {"type": "input_image", "image_url": _data_url_png(png_bytes)},
                ],
            }
        ],
    )

    text = getattr(resp, "output_text", None)
    if not text:
        # Try to reconstruct from output items if needed
        try:
            parts: list[str] = []
            for o in resp.output:
                for c in getattr(o, "content", []) or []:
                    t = getattr(c, "text", None)
                    if t:
                        parts.append(t)
            text = "\n".join(parts).strip()
        except Exception:
            text = ""

    if not text:
        raise RuntimeError("Empty response from vision model")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Repair attempt
        repair = client.responses.create(
            model=settings.openai_model_vision,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Fix this into valid JSON only, preserving fields and values:\n\n" + text,
                        }
                    ],
                }
            ],
        )
        repaired = getattr(repair, "output_text", "") or ""
        return json.loads(repaired)

