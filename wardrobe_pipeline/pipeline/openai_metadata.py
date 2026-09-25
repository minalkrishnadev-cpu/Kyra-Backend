# from __future__ import annotations

# import base64
# import json
# import logging
# from typing import Any

# from wardrobe_pipeline.config.settings import settings

# logger = logging.getLogger(__name__)


# _PROMPT = """You are analyzing a single clothing item image with a transparent background.
# Return ONLY valid JSON (no markdown, no explanation).

# Required fields:
# - type: string (shirt, trousers, jeans, jacket, coat, sweater, hoodie, dress, skirt, shorts, blazer, other)
# - gender: "male" or "female" (pick the best fit)
# - category: "top" or "bottom" or "outerwear"
# - color: string (primary visible color)
# - pattern: string (solid, striped, checked, floral, graphic, textured, other)
# - fit: string (slim, regular, oversized, other)
# - formality: string (casual, semi-casual, formal, other)

# Optional fields:
# - sleeve_type: string
# - length: string
# - compatible_with: array of strings (types or categories it pairs well with)

# If uncertain, use "other" or "unknown" but still fill required fields.
# """


# def _data_url_png(png_bytes: bytes) -> str:
#     b64 = base64.b64encode(png_bytes).decode("ascii")
#     return f"data:image/png;base64,{b64}"


# def extract_metadata_from_png(png_bytes: bytes,filename: str = "") -> dict[str, Any]:
#     if not settings.kyra_openai_api_key:
#         raise RuntimeError("KYRA_OPENAI_API_KEY is not set")

#     try:
#         from openai import OpenAI
#     except Exception as e:
#         raise RuntimeError(f"openai SDK not available: {e}") from e

#     client = OpenAI(api_key=settings.kyra_openai_api_key)
#     print("this is the client")

#     # Use the Responses API shape (current OpenAI Python SDK).
#     # If the SDK changes, this is the only place to adapt.
#     resp = client.responses.create(
#         model=settings.openai_model_vision,
#         input=[
#             {
#                 "role": "user",
#                 "content": [
#                     {"type": "input_text", "text": _PROMPT},
#                     {"type": "input_image", "image_url": _data_url_png(png_bytes)},
#                 ],
#             }
#         ],
#     )

#     text = getattr(resp, "output_text", None)
#     print("text",text)
#     if not text:
#         # Try to reconstruct from output items if needed
#         try:
#             parts: list[str] = []
#             for o in resp.output:
#                 for c in getattr(o, "content", []) or []:
#                     t = getattr(c, "text", None)
#                     if t:
#                         parts.append(t)
#             text = "\n".join(parts).strip()
#             print("texttttttttttttttttttttttttttttttttttttttttttttttttttttt*************",text)
#         except Exception:
#             text = ""
     
#     if not text:
#         raise RuntimeError("************************************ Empty response from vision model *********************")

#     try:
#         output=json.loads(text)
#         print("outputttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttttt",output)
#         return output
#     except json.JSONDecodeError:
#         # Repair attempt
#         repair = client.responses.create(
#             model=settings.openai_model_vision,
#             input=[
#                 {
#                     "role": "user",
#                     "content": [
#                         {
#                             "type": "input_text",
#                             "text": "Fix this into valid JSON only, preserving fields and values:\n\n" + text,
#                         }
#                     ],
#                 }
#             ],
#         )
#         print("repaireeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee texttttttttttttttttttttttttttttttttttttttt",repair)
#         repaired = getattr(repair, "output_text", "") or ""
#         return json.loads(repaired)

import json
import re
from typing import Any


def _clean_json_string(text: str) -> str:
    """Strips markdown code fences (```json ... ```) and extra whitespace."""
    if not text:
        return ""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _extract_text_from_response(resp: Any) -> str:
    """Safely extracts text content from the OpenAI SDK response object."""
    # Try direct attribute first if available
    text = getattr(resp, "output_text", None)
    if text:
        return text.strip()

    # Fallback to traversing response output objects
    parts: list[str] = []
    try:
        output_list = getattr(resp, "output", []) or []
        for item in output_list:
            content_list = getattr(item, "content", []) or []
            for c in content_list:
                t = getattr(c, "text", None)
                if t:
                    parts.append(t)
    except Exception:
        pass

    return "\n".join(parts).strip()


def extract_metadata_from_png(png_bytes: bytes, filename: str = "") -> dict[str, Any]:
    if not settings.kyra_openai_api_key:
        raise RuntimeError("KYRA_OPENAI_API_KEY is not set")

    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError(f"openai SDK not available: {e}") from e

    client = OpenAI(api_key=settings.kyra_openai_api_key)

    # 1. Primary Request
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

    text = _extract_text_from_response(resp)
    if not text:
        raise RuntimeError(f"Empty response from vision model for {filename or 'image'}")

    # 2. Clean & Attempt Direct Parse
    cleaned_text = _clean_json_string(text)
    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        pass  # Move to repair step if parsing failed

    # 3. Repair Attempt
    repair = client.responses.create(
        model=settings.openai_model_vision,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"Fix this into raw valid JSON only, without markdown fences or text commentary:\n\n{text}",
                    }
                ],
            }
        ],
    )

    repaired_raw = _extract_text_from_response(repair)
    cleaned_repaired = _clean_json_string(repaired_raw)

    if not cleaned_repaired:
        raise RuntimeError(
            f"Failed to extract metadata for {filename or 'image'}. Repair response yielded empty text."
        )

    # 4. Final Parse
    try:
        return json.loads(cleaned_repaired)
    except json.JSONDecodeError as err:
        raise RuntimeError(
            f"Failed to parse JSON for {filename or 'image'} after repair. Raw repaired response: {repaired_raw!r}"
        ) from err