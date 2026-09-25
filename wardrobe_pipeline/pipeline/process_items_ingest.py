"""
Stage A — Ingest mode: accept images via CLI, assign image_id, process, merge.

Flow: A1 ingest → A2 Vision + BiRefNet (parallel) → A3 merge by image_id.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from wardrobe_pipeline.pipeline.openai_metadata import extract_metadata_from_png
from wardrobe_pipeline.services.birefnet_service import BiRefNetService
from wardrobe_pipeline.utils.fs import IMAGE_EXTS, ensure_dir, merge_wardrobe_json, read_wardrobe_json, write_json_atomic
from wardrobe_pipeline.utils.ids import derive_image_id

logger = logging.getLogger(__name__)

_FOREGROUND_ALPHA_THRESHOLD = 127
_FOREGROUND_MIN_RATIO = 0.01


@dataclass(frozen=True)
class IngestResult:
    image_id: str
    source_path: str
    uploaded_path: str
    processed_path: str
    gender: str
    status: str
    error: str | None = None
    wardrobe_entry: dict[str, Any] = field(default_factory=dict)


def _to_png_bytes(image_bytes: bytes) -> bytes:
    """Normalize any supported image input into PNG bytes for Vision."""
    import io

    with Image.open(io.BytesIO(image_bytes)) as im:
        im = ImageOps.exif_transpose(im)
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()


def _validate_png_alpha(png_path: Path) -> None:
    with Image.open(png_path) as im:
        if im.mode not in {"RGBA", "LA"} and "A" not in im.getbands():
            raise ValueError("processed image has no alpha channel")


def _validate_foreground(png_path: Path, min_ratio: float = _FOREGROUND_MIN_RATIO) -> None:
    """Ensure non-empty foreground: alpha > threshold pixels exceed min_ratio of total."""
    with Image.open(png_path) as im:
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        arr = im.getchannel("A")
        total = arr.width * arr.height
        if total == 0:
            raise ValueError("empty image")
        count = sum(1 for p in arr.getdata() if p > _FOREGROUND_ALPHA_THRESHOLD)
        ratio = count / total
        if ratio < min_ratio:
            raise ValueError(f"foreground too small: {ratio:.2%} < {min_ratio:.2%}")


def _fallback_external_schema(image_id: str) -> dict[str, Any]:
    stem = (image_id or "item").lower().replace("_", " ")
    cat = "Top"
    sub = "Other"
    if any(h in stem for h in {"pants", "trouser", "jean", "short", "skirt"}):
        cat, sub = "Bottom", "Trousers"
    elif any(h in stem for h in {"jacket", "coat", "blazer"}):
        cat, sub = "Outerwear", "Jacket"
    elif any(h in stem for h in {"boot", "loafer", "sneaker", "shoe"}):
        cat, sub = "Footwear", "Shoes"
    return {
        "image_id": image_id,
        "filename": f"{image_id}.png",
        "article_name": stem.title() or "Unknown",
        "category": cat,
        "subcategory": sub,
        "basic_color": "Unknown",
        "color_hex_codes": [],
        "pattern": "solid",
        "texture": "Unknown",
        "material": "Unknown",
        "occasion": "Unknown",
        "season": "all-season",
        "fit": "regular",
        "length": "Unknown",
    }


def _gender_from_path(path: Path, default: str) -> str:
    """Derive gender from path if under Male or Female folder; else use default."""
    parts = Path(path).resolve().parts
    if "Male" in parts:
        return "male"
    if "Female" in parts:
        return "female"
    return default


def _extract_metadata_task(png_bytes: bytes, filename: str, image_id: str) -> dict[str, Any]:
    """Extract metadata via Vision. Returns external schema dict. Used for parallel execution."""
    try:
        meta = extract_metadata_from_png(png_bytes, filename)
        meta["image_id"] = image_id
        meta["filename"] = filename
        return meta
    except Exception as e:
        logger.error("metadata extraction failed for %s: %s", image_id, e, exc_info=True)
        fallback = _fallback_external_schema(image_id)
        fallback["_meta_error"] = str(e)
        return fallback


def _remove_bg_task(image_bytes: bytes) -> bytes:
    """Remove background. Returns PNG bytes. Used for parallel execution."""
    return BiRefNetService.remove_bg_png(image_bytes)


def _process_one_ingest(
    src_path: Path,
    image_id: str,
    gender: str,
    uploads_dir: Path,
    processed_dir: Path,
    wardrobe_path: Path,
    force: bool,
    skip_existing: bool,
) -> IngestResult:
    ext = src_path.suffix.lower() if src_path.suffix.lower() in IMAGE_EXTS else ".png"
    gender_dir = uploads_dir / "Male" if gender == "male" else uploads_dir / "Female"
    uploaded_path = gender_dir / f"{image_id}{ext}"
    processed_path = processed_dir / f"{image_id}.png"

    if skip_existing and not force:
        if processed_path.exists():
            existing = read_wardrobe_json(wardrobe_path)
            by_id = {str(x.get("image_id", Path(x.get("filename", "")).stem)): x for x in existing if isinstance(x, dict)}
            if image_id in by_id:
                entry = by_id[image_id]
                return IngestResult(
                    image_id=image_id,
                    source_path=str(src_path),
                    uploaded_path=str(uploaded_path),
                    processed_path=str(processed_path),
                    gender=gender,
                    status="skipped",
                    wardrobe_entry=dict(entry) if isinstance(entry, dict) else {},
                )

    ensure_dir(gender_dir)
    ensure_dir(processed_dir)

    image_bytes = src_path.read_bytes()
    if force or not uploaded_path.exists():
        uploaded_path.write_bytes(image_bytes)

    filename = f"{image_id}.png"
    png_for_vision = _to_png_bytes(image_bytes)

    status = "ok"
    err: str | None = None
    meta: dict[str, Any]
    png_bytes: bytes

    need_bg = force or not processed_path.exists()
    if need_bg:
        # Run metadata extraction and background removal in parallel (separate threads).
        meta_result: list[dict[str, Any] | None] = [None]
        bg_result: list[bytes | None] = [None]

        def do_meta() -> None:
            meta_result[0] = _extract_metadata_task(png_for_vision, filename, image_id)

        def do_bg() -> None:
            bg_result[0] = _remove_bg_task(image_bytes)

        t1 = threading.Thread(target=do_meta)
        t2 = threading.Thread(target=do_bg)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        meta = meta_result[0] or _fallback_external_schema(image_id)
        png_bytes = bg_result[0] or image_bytes
    else:
        meta = _extract_metadata_task(png_for_vision, filename, image_id)
        png_bytes = processed_path.read_bytes()

    if meta.get("_meta_error"):
        status = "needs_review"
        err = meta.pop("_meta_error", None)

    if need_bg:
        processed_path.write_bytes(png_bytes)
        _validate_png_alpha(processed_path)
        try:
            _validate_foreground(processed_path)
        except ValueError as e:
            logger.warning("foreground check for %s: %s", image_id, e)

    return IngestResult(
        image_id=image_id,
        source_path=str(src_path),
        uploaded_path=str(uploaded_path),
        processed_path=str(processed_path),
        gender=gender,
        status=status,
        error=err,
        wardrobe_entry=meta,
    )


def process_items_ingest(
    add_image_paths: list[Path],
    gender: str,
    uploads_dir: Path,
    processed_dir: Path,
    wardrobe_male_path: Path,
    wardrobe_female_path: Path,
    id_overrides: list[str] | None = None,
    logs_dir: Path = Path("logs"),
    concurrency: int = 4,
    force: bool = False,
    skip_existing: bool = False,
) -> dict[str, Any]:
    """
    Stage A ingest: A1 ingest + ID → A2 Vision + BiRefNet (parallel) → A3 merge by image_id.
    """
    ensure_dir(uploads_dir)
    ensure_dir(processed_dir)
    ensure_dir(logs_dir)

    valid_paths: list[Path] = []
    for p in add_image_paths:
        p = Path(p).resolve()
        if not p.exists():
            logger.warning("skipping missing path: %s", p)
            continue
        if not p.is_file():
            logger.warning("skipping non-file: %s", p)
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            logger.warning("skipping non-image: %s", p)
            continue
        valid_paths.append(p)

    if not valid_paths:
        return {
            "processed": 0,
            "results": [],
            "manifest_path": None,
            "note": "no valid image paths",
        }

    ids_overrides = (id_overrides or []) if id_overrides else []
    tasks: list[tuple[Path, str, str]] = []
    for i, src in enumerate(valid_paths):
        if i < len(ids_overrides) and ids_overrides[i]:
            image_id = ids_overrides[i]
        else:
            image_id = derive_image_id(src, src.read_bytes())
        img_gender = _gender_from_path(src, gender)
        tasks.append((src, image_id, img_gender))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "source_to_id": {},
        "gender": gender,
        "uploaded_paths": [],
    }

    results: list[IngestResult] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futs = [
            ex.submit(
                _process_one_ingest,
                src,
                image_id,
                img_gender,
                uploads_dir,
                processed_dir,
                wardrobe_female_path if img_gender == "female" else wardrobe_male_path,
                force,
                skip_existing,
            )
            for src, image_id, img_gender in tasks
        ]
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            manifest["source_to_id"][r.source_path] = r.image_id
            if r.wardrobe_entry:
                gender_dir = uploads_dir / "Male" if r.gender == "male" else uploads_dir / "Female"
                ext = Path(r.source_path).suffix
                manifest["uploaded_paths"].append(str(gender_dir / f"{r.image_id}{ext}"))

    results_sorted = sorted(results, key=lambda x: (x.gender, x.image_id))
    male_upserts = [r.wardrobe_entry for r in results_sorted if r.gender == "male" and r.wardrobe_entry]
    female_upserts = [r.wardrobe_entry for r in results_sorted if r.gender == "female" and r.wardrobe_entry]
    merge_wardrobe_json(wardrobe_male_path, male_upserts, key_field="image_id")
    merge_wardrobe_json(wardrobe_female_path, female_upserts, key_field="image_id")

    manifest_path = logs_dir / f"batch_{ts}.json"
    write_json_atomic(manifest_path, manifest)

    return {
        "processed": len(results_sorted),
        "results": [asdict(r) for r in results_sorted],
        "manifest_path": str(manifest_path),
    }
