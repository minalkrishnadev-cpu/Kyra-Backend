from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def list_images(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    paths: list[Path] = []
    for p in input_dir.iterdir():
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            paths.append(p)
    return sorted(paths, key=lambda x: x.name)


def list_images_by_gender(base_dir: Path) -> dict[str, list[Path]]:
    """
    List images from base_dir/Male/ and base_dir/Female/.
    Returns {"male": [...], "female": [...]} with paths sorted by name.
    """
    out: dict[str, list[Path]] = {"male": [], "female": []}
    for gender, subdir in [("male", "Male"), ("female", "Female")]:
        d = base_dir / subdir
        out[gender] = list_images(d)
    return out


def _wardrobe_key(item: dict[str, Any], key_field: str) -> str | None:
    """Extract merge key from item. Returns None if item should be skipped."""
    if key_field == "image_id":
        kid = item.get("image_id")
        if kid is not None and isinstance(kid, str):
            return str(kid)
        fn = item.get("filename")
        if fn is not None and isinstance(fn, str):
            return str(Path(fn).stem)
        return None
    fn = item.get("filename")
    if fn is not None and isinstance(fn, str):
        return str(fn)
    return None


def merge_wardrobe_json(
    path: Path,
    upserts: list[dict[str, Any]],
    key_field: str = "filename",
) -> None:
    """
    Upsert items into male.json/female.json.
    key_field: "filename" (default) or "image_id" for merge key.
    """
    if not upserts:
        return
    existing = read_wardrobe_json(path)
    by_key: dict[str, dict[str, Any]] = {}
    for x in existing:
        if isinstance(x, dict):
            k = _wardrobe_key(x, key_field)
            if k is not None:
                by_key[k] = dict(x)
    for item in upserts:
        if not isinstance(item, dict):
            continue
        k = _wardrobe_key(item, key_field)
        if k is not None:
            by_key[k] = dict(item)
    merged = [by_key[k] for k in sorted(by_key.keys())]
    write_json_atomic(path, merged)


def read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    raise ValueError(f"{path} must contain a JSON list")


def read_wardrobe_json(path: Path) -> list[dict[str, Any]]:
    """
    Robust loader for male.json / female.json that may be malformed:
    - Multiple concatenated arrays (e.g. male.json: ]  [ )
    - Mix of top-level objects and arrays (e.g. female.json)
    Returns a flat list of item dicts.
    """
    if not path.exists():
        return []

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    # Normalize to a single JSON array
    fixed = raw
    # Merge consecutive arrays: ]  [ -> ,
    fixed = re.sub(r"\]\s*\[\s*", ",", fixed)
    # Object followed by object: }  { -> },
    fixed = re.sub(r"}\s*{\s*", "},{", fixed)
    # Object followed by array: }  [ -> },
    fixed = re.sub(r"}\s*\[\s*", "},{", fixed)
    # Array followed by object: ]  { -> ,{
    fixed = re.sub(r"\]\s*{\s*", ",{", fixed)

    # Ensure we have an array
    if fixed.startswith("{"):
        fixed = "[" + fixed
    if not fixed.startswith("["):
        fixed = "[" + fixed
    if not fixed.endswith("]"):
        fixed = fixed + "]"

    try:
        data = json.loads(fixed)
    except json.JSONDecodeError:
        # Fallback: extract all {...} objects via brace matching
        out = _extract_json_objects(raw)
        return out

    if not isinstance(data, list):
        return []

    out_list: list[dict[str, Any]] = []
    for x in data:
        if isinstance(x, dict):
            out_list.append(x)
        elif isinstance(x, list):
            for item in x:
                if isinstance(item, dict):
                    out_list.append(item)
    return out_list


def _extract_json_objects(raw: str) -> list[dict[str, Any]]:
    """Extract top-level JSON objects from malformed input via brace matching."""
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(raw):
        if raw[i] in " \t\n\r,":
            i += 1
            continue
        if raw[i] == "{":
            depth = 1
            start = i
            i += 1
            while i < len(raw) and depth > 0:
                c = raw[i]
                if c == '"' and (i == 0 or raw[i - 1] != "\\"):
                    i += 1
                    while i < len(raw) and (raw[i] != '"' or raw[i - 1] == "\\"):
                        i += 1
                    i += 1
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        try:
                            obj = json.loads(raw[start:i])
                            if isinstance(obj, dict):
                                out.append(obj)
                        except json.JSONDecodeError:
                            pass
                        break
                i += 1
        elif raw[i] == "[":
            depth = 1
            start = i
            i += 1
            while i < len(raw) and depth > 0:
                c = raw[i]
                if c == '"' and (i == 0 or raw[i - 1] != "\\"):
                    i += 1
                    while i < len(raw) and (raw[i] != '"' or raw[i - 1] == "\\"):
                        i += 1
                    i += 1
                    continue
                if c in "[{":
                    depth += 1
                elif c in "]}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        try:
                            arr = json.loads(raw[start:i])
                            if isinstance(arr, list):
                                for item in arr:
                                    if isinstance(item, dict):
                                        out.append(item)
                        except json.JSONDecodeError:
                            pass
                        break
                i += 1
        else:
            i += 1
    return out


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

