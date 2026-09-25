#!/usr/bin/env python3
"""
One-time script: organize processed_items into Male/ and Female/ subfolders
by matching filenames from male.json and female.json.
"""
import json
import shutil
from pathlib import Path

PROCESSED = Path("processed_items")
MALE_JSON = Path("male.json")
FEMALE_JSON = Path("female.json")


def main() -> None:
    male_dir = PROCESSED / "Male"
    female_dir = PROCESSED / "Female"
    male_dir.mkdir(parents=True, exist_ok=True)
    female_dir.mkdir(parents=True, exist_ok=True)

    for path, out_dir in [(MALE_JSON, male_dir), (FEMALE_JSON, female_dir)]:
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        for item in data:
            if not isinstance(item, dict):
                continue
            fn = item.get("filename") or (item.get("image_id", "") + ".png")
            if not fn:
                continue
            src = PROCESSED / fn
            if src.exists() and src.is_file():
                dst = out_dir / fn
                shutil.copy2(src, dst)
                print(f"  {path.name}: {fn} -> {out_dir.name}/")


if __name__ == "__main__":
    main()
