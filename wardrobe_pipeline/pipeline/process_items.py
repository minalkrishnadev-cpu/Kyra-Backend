from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from wardrobe_pipeline.pipeline.openai_metadata import extract_metadata_from_png
from wardrobe_pipeline.services.birefnet_service import BiRefNetService
from wardrobe_pipeline.utils.fs import ensure_dir, list_images_by_gender, merge_wardrobe_json, read_wardrobe_json

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessResult:
    filename: str
    source_path: str
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


def _fallback_external_schema(filename: str) -> dict[str, Any]:
    """Minimal external schema when Vision fails."""
    stem = Path(filename).stem.lower()
    cat = "Top"
    sub = "Other"
    if any(h in stem for h in {"pants", "trouser", "jean", "short", "skirt"}):
        cat, sub = "Bottom", "Trousers"
    elif any(h in stem for h in {"jacket", "coat", "blazer"}):
        cat, sub = "Outerwear", "Jacket"
    elif any(h in stem for h in {"boot", "loafer", "sneaker", "shoe"}):
        cat, sub = "Footwear", "Shoes"
    return {
        "filename": filename,
        "article_name": stem.replace("_", " ").title() or "Unknown",
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


def _extract_metadata_task(png_bytes: bytes, filename: str) -> tuple[dict[str, Any], str | None]:
    """Extract metadata via Vision. Returns (meta, error). Used for parallel execution."""
    try:
        meta = extract_metadata_from_png(png_bytes, filename)
        return meta, None
    except Exception as e:
        logger.error("metadata extraction failed for %s: %s", filename, e, exc_info=True)
        return _fallback_external_schema(filename), str(e)


def _remove_bg_task(image_bytes: bytes) -> bytes:
    """Remove background. Returns PNG bytes. Used for parallel execution."""
    return BiRefNetService.remove_bg_png(image_bytes)


def _process_one(
    src_path: Path,
    gender: str,
    processed_dir: Path,
    wardrobe_path: Path,
    force: bool,
    skip_existing: bool,
) -> ProcessResult:
    # Include gender to avoid collisions for same stem across Male/Female uploads.
    filename = f"{gender}_{src_path.stem}.png"
    processed_path = processed_dir / filename

    if skip_existing and not force:
        if processed_path.exists():
            existing = read_wardrobe_json(wardrobe_path)
            by_fn = {str(x.get("filename")): x for x in existing if isinstance(x, dict) and x.get("filename")}
            if filename in by_fn:
                return ProcessResult(
                    filename=filename,
                    source_path=str(src_path),
                    processed_path=str(processed_path),
                    gender=gender,
                    status="skipped",
                    wardrobe_entry=by_fn.get(filename) or {},
                )

    ensure_dir(processed_dir)
    image_bytes = src_path.read_bytes()
    png_for_vision = _to_png_bytes(image_bytes)

    status = "ok"
    err: str | None = None
    meta: dict[str, Any]
    need_bg = force or not processed_path.exists()

    if need_bg:
        # Run metadata extraction and background removal in parallel (separate threads).
        meta_result: list[tuple[dict[str, Any], str | None] | None] = [None]
        bg_result: list[bytes | None] = [None]

        def do_meta() -> None:
            meta_result[0] = _extract_metadata_task(png_for_vision, filename)

        def do_bg() -> None:
            bg_result[0] = _remove_bg_task(image_bytes)

        t1 = threading.Thread(target=do_meta)
        t2 = threading.Thread(target=do_bg)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        meta, err = meta_result[0] or (_fallback_external_schema(filename), "metadata failed")
        if err:
            status = "needs_review"
        png_bytes = bg_result[0]
        if png_bytes:
            processed_path.write_bytes(png_bytes)
            _validate_png_alpha(processed_path)
    else:
        meta, err = _extract_metadata_task(png_for_vision, filename)
        if err:
            status = "needs_review"

    return ProcessResult(
        filename=filename,
        source_path=str(src_path),
        processed_path=str(processed_path),
        gender=gender,
        status=status,
        error=err,
        wardrobe_entry=meta,
    )


def process_items(
    uploads_dir: Path,
    processed_dir: Path,
    wardrobe_male_path: Path,
    wardrobe_female_path: Path,
    concurrency: int = 4,
    force: bool = False,
    skip_existing: bool = False,
) -> dict[str, Any]:
    ensure_dir(uploads_dir)
    ensure_dir(processed_dir)

    by_gender = list_images_by_gender(uploads_dir)
    tasks: list[tuple[Path, str, Path]] = []
    for g, paths in by_gender.items():
        wpath = wardrobe_female_path if g == "female" else wardrobe_male_path
        for p in paths:
            tasks.append((p, g, wpath))

    if not tasks:
        return {"processed": 0, "results": [], "note": "no images in uploads/Male/ or uploads/Female/"}

    results: list[ProcessResult] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futs = [
            ex.submit(
                _process_one,
                src_path,
                gender,
                processed_dir,
                wardrobe_path,
                force,
                skip_existing,
            )
            for src_path, gender, wardrobe_path in tasks
        ]
        for f in as_completed(futs):
            results.append(f.result())

    results_sorted = sorted(results, key=lambda r: (r.gender, r.filename))

    male_upserts = [r.wardrobe_entry for r in results_sorted if r.gender == "male" and r.wardrobe_entry]
    female_upserts = [r.wardrobe_entry for r in results_sorted if r.gender == "female" and r.wardrobe_entry]

    merge_wardrobe_json(wardrobe_male_path, male_upserts)
    merge_wardrobe_json(wardrobe_female_path, female_upserts)

    return {
        "processed": len(results_sorted),
        "results": [asdict(r) for r in results_sorted],
    }
