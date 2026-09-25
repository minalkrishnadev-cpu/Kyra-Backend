from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image

from wardrobe_pipeline.utils.fs import ensure_dir

logger = logging.getLogger(__name__)


def _load_rgba(image_dir: Path, rel_path: str) -> Image.Image:
    """Load image from image_dir using filename from rel_path (e.g. processed_items/b1.png -> b1.png)."""
    p = image_dir / Path(rel_path).name
    im = Image.open(p)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    return im


def render_outfit_collage(
    outfit_id: str,
    items: list[dict[str, Any]],
    image_dir: Path,
    out_path: Path,
    canvas_width: int = 768,
    slot_height: int = 768,
    padding: int = 24,
) -> None:
    """
    Vertical layout by category order:
    - outerwear, top, bottom, footwear
    """
    ensure_dir(out_path.parent)

    order = {"outerwear": 0, "top": 1, "bottom": 2, "footwear": 3}
    items_sorted = sorted(items, key=lambda x: order.get(str(x.get("category", "")), 9))

    images: list[Image.Image] = []
    for it in items_sorted:
        images.append(_load_rgba(image_dir, str(it["image_path"])))

    slots = len(images)
    canvas_height = slots * slot_height + (slots + 1) * padding
    canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))

    y = padding
    for im in images:
        # Fit into slot
        target_w = canvas_width - 2 * padding
        target_h = slot_height
        scale = min(target_w / im.width, target_h / im.height)
        new_size = (max(1, int(im.width * scale)), max(1, int(im.height * scale)))
        im2 = im.resize(new_size, Image.LANCZOS)

        x = padding + (target_w - im2.width) // 2
        y_slot = y + (target_h - im2.height) // 2
        canvas.alpha_composite(im2, (x, y_slot))
        y += slot_height + padding

    canvas.save(out_path, format="PNG", optimize=True)
    logger.debug("saved collage %s to %s", outfit_id, out_path)

