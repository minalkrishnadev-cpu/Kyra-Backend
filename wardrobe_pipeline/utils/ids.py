from __future__ import annotations

import hashlib
import re
from pathlib import Path


_KEEP_AS_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]*_\d+$")


def content_hash8(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:8]


def derive_image_id(image_path: Path, image_bytes: bytes) -> str:
    """
    If filename stem already matches the user's expected style (e.g. shirt_001),
    keep it. Otherwise create a deterministic ID based on stem + hash.
    """
    stem = image_path.stem.strip()
    if _KEEP_AS_ID.match(stem):
        return stem
    h = content_hash8(image_bytes)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_") or "item"
    return f"{safe}_{h}"


def outfit_id(gender: str, image_ids: list[str]) -> str:
    joined = "|".join(sorted(image_ids))
    h = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:6]
    return f"{gender}_outfit_{h}"

