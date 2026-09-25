from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Gender = Literal["male", "female"]
Category = Literal["top", "bottom", "outerwear", "footwear"]


@dataclass(frozen=True)
class WardrobeItem:
    image_id: str
    image_path: str
    type: str
    category: Category
    gender: Gender
    color: str = "unknown"
    pattern: str = "unknown"
    fit: str = "unknown"
    formality: str = "unknown"
    sleeve_type: str | None = None
    length: str | None = None
    compatible_with: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    needs_review: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def item_to_json(item: WardrobeItem) -> dict[str, Any]:
    d: dict[str, Any] = {
        "image_id": item.image_id,
        "image_path": item.image_path,
        "type": item.type,
        "category": item.category,
        "gender": item.gender,
        "color": item.color,
        "pattern": item.pattern,
        "fit": item.fit,
        "formality": item.formality,
    }
    if item.sleeve_type is not None:
        d["sleeve_type"] = item.sleeve_type
    if item.length is not None:
        d["length"] = item.length
    if item.compatible_with:
        d["compatible_with"] = list(item.compatible_with)
    if item.tags:
        d["tags"] = list(item.tags)
    if item.needs_review:
        d["needs_review"] = True
    if item.extra:
        d.update(item.extra)
    return d


def _map_external_category(raw: str) -> str | None:
    """Map external category to pipeline top|bottom|outerwear|footwear."""
    r = (raw or "").strip().lower()
    if r in {"top", "shirt", "blouse", "tank", "camisole", "tee", "polo", "sweater"}:
        return "top"
    if r in {"bottom", "pants", "trousers", "jeans", "skirt", "shorts", "wide leg pants"}:
        return "bottom"
    if r in {"outerwear", "jacket", "coat", "blazer", "bomber jacket", "utility jacket"}:
        return "outerwear"
    if r in {"footwear", "boots", "loafers", "sneakers", "heels", "flats", "shoes", "sandals", "oxfords", "moccasins", "slides"}:
        return "footwear"
    return None


def item_from_external_schema(d: dict[str, Any], gender: str) -> WardrobeItem | None:
    """Map external male/female.json schema to WardrobeItem."""
    filename = d.get("filename")
    if not filename or not isinstance(filename, str):
        return None

    raw_cat = str(d.get("category", "")).strip()
    category = _map_external_category(raw_cat)
    if category is None:
        return None

    stem = str(filename).rsplit(".", 1)[0] if "." in filename else filename
    occasion = (d.get("occasion") or "").lower()
    formality = "formal" if "formal" in occasion or "business" in occasion else "casual"

    return WardrobeItem(
        image_id=stem,
        image_path=f"processed_items/{filename}",
        type=str(d.get("subcategory") or d.get("article_name") or "unknown"),
        category=category,
        gender="male" if gender.lower() == "male" else "female",
        color=str(d.get("basic_color", "unknown")),
        pattern=str(d.get("pattern", "unknown")),
        fit=str(d.get("fit", "unknown")),
        formality=formality,
        sleeve_type=None,
        length=str(d.get("length")) if d.get("length") else None,
        compatible_with=[],
        tags=[],
        needs_review=False,
        extra={
            "article_name": d.get("article_name"),
            "texture": d.get("texture"),
            "material": d.get("material"),
            "season": d.get("season"),
            "color_hex_codes": d.get("color_hex_codes"),
        },
    )


def item_from_json(d: dict[str, Any]) -> WardrobeItem:
    return WardrobeItem(
        image_id=str(d["image_id"]),
        image_path=str(d["image_path"]),
        type=str(d.get("type", "unknown")),
        category=d.get("category", "top"),
        gender=d.get("gender", "male"),
        color=str(d.get("color", "unknown")),
        pattern=str(d.get("pattern", "unknown")),
        fit=str(d.get("fit", "unknown")),
        formality=str(d.get("formality", "unknown")),
        sleeve_type=d.get("sleeve_type"),
        length=d.get("length"),
        compatible_with=list(d.get("compatible_with", []) or []),
        tags=list(d.get("tags", []) or []),
        needs_review=bool(d.get("needs_review", False)),
        extra={k: v for k, v in d.items() if k not in {
            "image_id","image_path","type","category","gender","color","pattern","fit","formality",
            "sleeve_type","length","compatible_with","tags","needs_review"
        }},
    )

