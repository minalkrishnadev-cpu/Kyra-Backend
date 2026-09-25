from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from wardrobe_pipeline.types import WardrobeItem, item_from_external_schema, item_from_json, item_to_json
from wardrobe_pipeline.utils.fs import ensure_dir, read_wardrobe_json, read_json_list, write_json_atomic
from wardrobe_pipeline.utils.ids import outfit_id
from wardrobe_pipeline.visuals.collage import render_outfit_collage

logger = logging.getLogger(__name__)


_FORMALITY = {"casual": 0, "semi-casual": 1, "formal": 2, "other": 1, "unknown": 1}


def _formality_score(x: str) -> int:
    return _FORMALITY.get((x or "unknown").strip().lower(), 1)


def _is_pattern_loud(p: str) -> bool:
    p = (p or "unknown").strip().lower()
    return p not in {"solid", "unknown"}


@dataclass(frozen=True)
class Outfit:
    gender: str
    items: tuple[WardrobeItem, ...]

    @property
    def image_ids(self) -> list[str]:
        return [i.image_id for i in self.items]


def _compatible(a: WardrobeItem, b: WardrobeItem) -> bool:
    # Formality distance
    if abs(_formality_score(a.formality) - _formality_score(b.formality)) > 1:
        return False

    # Simple pattern heuristic (skip for footwear)
    if a.category != "footwear" and b.category != "footwear":
        if _is_pattern_loud(a.pattern) and _is_pattern_loud(b.pattern):
            return False

    # Explicit compatibility hints (soft allowlist)
    if a.compatible_with:
        if (b.type not in a.compatible_with) and (b.category not in a.compatible_with):
            pass
    if b.compatible_with:
        if (a.type not in b.compatible_with) and (a.category not in b.compatible_with):
            pass

    return True


def _footwear_compatible(footwear: WardrobeItem, outfit_items: tuple[WardrobeItem, ...]) -> bool:
    """Footwear matches if formality is within range of the outfit."""
    if not outfit_items:
        return True
    max_dist = 1
    for it in outfit_items:
        if abs(_formality_score(footwear.formality) - _formality_score(it.formality)) > max_dist:
            return False
    return True


def _load_items(path: Path, gender: str) -> list[WardrobeItem]:
    """Load wardrobe items, supporting both pipeline schema and external male/female.json format."""
    try:
        raw = read_wardrobe_json(path)
    except Exception:
        raw = read_json_list(path) if path.exists() else []

    items: list[WardrobeItem] = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        try:
            if "filename" in d:
                # External schema (male.json / female.json) — has filename, may have image_id
                item = item_from_external_schema(d, gender)
                if item is not None:
                    items.append(item)
            elif "image_path" in d:
                # Internal schema (full WardrobeItem)
                items.append(item_from_json(d))
        except Exception:
            continue
    return items


def _dedupe_outfits(outfits: Iterable[Outfit]) -> list[Outfit]:
    seen: set[tuple[str, ...]] = set()
    out: list[Outfit] = []
    for o in outfits:
        key = tuple(sorted(o.image_ids))
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out


def _generate_for_gender(
    gender: str,
    items: list[WardrobeItem],
    max_outfits: int,
    max_outerwear_per_pair: int,
    max_footwear_per_outfit: int = 1,
) -> list[Outfit]:
    tops = [i for i in items if i.category == "top"]
    bottoms = [i for i in items if i.category == "bottom"]
    outerwears = [i for i in items if i.category == "outerwear"]
    footwears = [i for i in items if i.category == "footwear"]

    outfits: list[Outfit] = []
    for t in tops:
        for b in bottoms:
            if t.image_id == b.image_id:
                continue
            if not _compatible(t, b):
                continue
            base = (t, b)
            outfits.append(Outfit(gender=gender, items=base))
            added_outer = 0
            for o in outerwears:
                if o.image_id in {t.image_id, b.image_id}:
                    continue
                if _compatible(o, t) and _compatible(o, b):
                    base_with_o = (o, t, b)
                    outfits.append(Outfit(gender=gender, items=base_with_o))
                    added_outer += 1
                    if max_outerwear_per_pair and added_outer >= max_outerwear_per_pair:
                        break

            if max_outfits and len(outfits) >= max_outfits:
                break
        if max_outfits and len(outfits) >= max_outfits:
            break

    outfits = _dedupe_outfits(outfits)

    # Coverage pass: try to include unused items at least once
    used: dict[str, int] = {}
    for o in outfits:
        for iid in o.image_ids:
            used[iid] = used.get(iid, 0) + 1

    def _try_add(o: Outfit) -> None:
        nonlocal outfits
        outfits = _dedupe_outfits([*outfits, o])

    for it in items:
        if used.get(it.image_id, 0) > 0:
            continue
        if it.category == "top":
            for b in bottoms:
                if _compatible(it, b):
                    _try_add(Outfit(gender=gender, items=(it, b)))
                    break
        elif it.category == "bottom":
            for t in tops:
                if _compatible(it, t):
                    _try_add(Outfit(gender=gender, items=(t, it)))
                    break
        elif it.category == "outerwear":
            for t in tops:
                for b in bottoms:
                    if _compatible(t, b) and _compatible(it, t) and _compatible(it, b):
                        _try_add(Outfit(gender=gender, items=(it, t, b)))
                        break
                else:
                    continue
                break
        elif it.category == "footwear":
            for o in list(outfits):
                if it.image_id in {i.image_id for i in o.items}:
                    continue
                if _footwear_compatible(it, o.items):
                    _try_add(Outfit(gender=gender, items=(*o.items, it)))
                    break

    # Add exactly one footwear to every outfit when footwear exists (skip if already has footwear).
    # Use least-used-first so all footwear types appear across outfits.
    if footwears:
        footwear_usage: dict[str, int] = {f.image_id: 0 for f in footwears}
        expanded: list[Outfit] = []
        for o in outfits:
            has_footwear = any(i.category == "footwear" for i in o.items)
            if has_footwear:
                expanded.append(o)
                continue
            compatible = [
                f for f in footwears
                if f.image_id not in {i.image_id for i in o.items}
                and _footwear_compatible(f, o.items)
            ]
            if not compatible:
                compatible = [f for f in footwears if f.image_id not in {i.image_id for i in o.items}]
            best_f: WardrobeItem | None = min(
                compatible,
                key=lambda f: footwear_usage[f.image_id],
                default=None,
            )
            if best_f is not None:
                footwear_usage[best_f.image_id] += 1
                expanded.append(Outfit(gender=gender, items=(*o.items, best_f)))
            else:
                expanded.append(o)
        outfits = _dedupe_outfits(expanded)

    # Require footwear on every outfit: only keep outfits that have at least one footwear item.
    outfits = [o for o in outfits if any(i.category == "footwear" for i in o.items)]
    if not outfits and items:
        logger.warning(
            "No footwear in wardrobe for %s; all outfits require footwear. Add shoe images to generate outfits.",
            gender,
        )

    if max_outfits:
        outfits = outfits[:max_outfits]
    return outfits


def _write_outfits(
    gender: str,
    outfits: list[Outfit],
    image_dir: Path,
    collages_dir: Path,
    outfits_path: Path,
) -> dict[str, Any]:
    ensure_dir(collages_dir)

    out_entries: list[dict[str, Any]] = []
    collage_failures: list[str] = []
    for o in outfits:
        iid = outfit_id(gender, o.image_ids)
        collage_path = collages_dir / f"{iid}.png"
        try:
            render_outfit_collage(
                outfit_id=iid,
                items=[item_to_json(i) for i in o.items],
                image_dir=image_dir,
                out_path=collage_path,
            )
        except Exception as e:
            logger.error("collage generation failed for %s: %s", iid, e, exc_info=True)
            collage_failures.append(iid)
            continue

        rel_path = str(collages_dir / f"{iid}.png").replace("\\", "/")
        out_entries.append(
            {
                "outfit_id": iid,
                "gender": gender,
                "collage_path": rel_path,
                "items": [item_to_json(i) for i in o.items],
            }
        )

    write_json_atomic(outfits_path, out_entries)
    summary: dict[str, Any] = {
        "outfits": len(out_entries),
        "outfits_path": str(outfits_path),
    }
    if collage_failures:
        summary["collage_failures"] = collage_failures
    return summary


def generate_outfits(
    gender: str,
    wardrobe_male_path: Path,
    wardrobe_female_path: Path,
    processed_dir: Path,
    collages_dir: Path,
    male_outfits_path: Path,
    female_outfits_path: Path,
    max_outfits: int = 0,
    max_outerwear_per_pair: int = 10,
    image_source_base: Path | None = None,
) -> dict[str, Any]:
    """Generate outfit combinations from wardrobe JSON and collage images.

    When image_source_base is set (e.g. uploads/), load images from:
      - {image_source_base}/Male/ for male outfits
      - {image_source_base}/Female/ for female outfits
    Falls back to image_source_base if Male/Female subdirs don't exist (flat layout).
    Otherwise use processed_dir for both.
    """
    ensure_dir(collages_dir)

    summary: dict[str, Any] = {"gender": gender}
    if image_source_base:
        male_sub = image_source_base / "Male"
        female_sub = image_source_base / "Female"
        male_image_dir = male_sub if male_sub.exists() else image_source_base
        female_image_dir = female_sub if female_sub.exists() else image_source_base
    else:
        male_image_dir = processed_dir
        female_image_dir = processed_dir

    if gender in {"male", "all"}:
        male_items = _load_items(wardrobe_male_path, "male")
        male_outfits = _generate_for_gender(
            "male",
            male_items,
            max_outfits=max_outfits,
            max_outerwear_per_pair=max_outerwear_per_pair,
        )
        summary["male"] = _write_outfits(
            gender="male",
            outfits=male_outfits,
            image_dir=male_image_dir,
            collages_dir=collages_dir,
            outfits_path=male_outfits_path,
        )

    if gender in {"female", "all"}:
        female_items = _load_items(wardrobe_female_path, "female")
        female_outfits = _generate_for_gender(
            "female",
            female_items,
            max_outfits=max_outfits,
            max_outerwear_per_pair=max_outerwear_per_pair,
        )
        summary["female"] = _write_outfits(
            gender="female",
            outfits=female_outfits,
            image_dir=female_image_dir,
            collages_dir=collages_dir,
            outfits_path=female_outfits_path,
        )

    return summary

