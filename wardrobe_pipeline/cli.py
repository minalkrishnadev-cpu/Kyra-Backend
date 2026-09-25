from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from wardrobe_pipeline.pipeline.process_items import process_items
from wardrobe_pipeline.pipeline.process_items_ingest import process_items_ingest
from wardrobe_pipeline.pipeline.generate_outfits import generate_outfits


def _configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def _cmd_process_items_ingest(args: argparse.Namespace) -> int:
    summary = process_items_ingest(
        add_image_paths=[Path(p) for p in args.add_image],
        gender=args.gender,
        uploads_dir=Path(args.uploads_dir),
        processed_dir=Path(args.processed_dir),
        wardrobe_male_path=Path(args.male_json),
        wardrobe_female_path=Path(args.female_json),
        id_overrides=args.id,
        logs_dir=Path(args.logs_dir),
        concurrency=args.concurrency,
        force=args.force,
        skip_existing=args.skip_existing,
    )
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_process_items(args: argparse.Namespace) -> int:
    summary = process_items(
        uploads_dir=Path(args.uploads_dir),
        processed_dir=Path(args.processed_dir),
        wardrobe_male_path=Path(args.male_json),
        wardrobe_female_path=Path(args.female_json),
        concurrency=args.concurrency,
        force=args.force,
        skip_existing=args.skip_existing,
    )
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_generate_outfits(args: argparse.Namespace) -> int:
    summary = generate_outfits(
        gender=args.gender,
        wardrobe_male_path=Path(args.male_json),
        wardrobe_female_path=Path(args.female_json),
        processed_dir=Path(args.processed_dir),
        collages_dir=Path(args.collages_dir),
        male_outfits_path=Path(args.male_outfits_json),
        female_outfits_path=Path(args.female_outfits_json),
        max_outfits=args.max_outfits,
        max_outerwear_per_pair=args.max_outerwear_per_pair,
        image_source_base=Path(args.image_source_base),
    )
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_run_all(args: argparse.Namespace) -> int:
    s1 = process_items(
        uploads_dir=Path(args.uploads_dir),
        processed_dir=Path(args.processed_dir),
        wardrobe_male_path=Path(args.male_json),
        wardrobe_female_path=Path(args.female_json),
        concurrency=args.concurrency,
        force=args.force,
        skip_existing=args.skip_existing,
    )
    s2 = generate_outfits(
        gender="all",
        wardrobe_male_path=Path(args.male_json),
        wardrobe_female_path=Path(args.female_json),
        processed_dir=Path(args.processed_dir),
        collages_dir=Path(args.collages_dir),
        male_outfits_path=Path(args.male_outfits_json),
        female_outfits_path=Path(args.female_outfits_json),
        max_outfits=args.max_outfits,
        max_outerwear_per_pair=args.max_outerwear_per_pair,
        image_source_base=Path(args.image_source_base),
    )
    summary = {"process_items": s1, "generate_outfits": s2}
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wardrobe_pipeline")
    parser.add_argument("-v", "--verbose", action="count", default=0)

    sub = parser.add_subparsers(dest="cmd", required=True)

    common_io = argparse.ArgumentParser(add_help=False)
    common_io.add_argument("--uploads-dir", default="uploads")
    common_io.add_argument("--processed-dir", default="processed_items")
    common_io.add_argument("--collages-dir", default="wardrobe/outfits")
    common_io.add_argument("--male-json", default="male.json")
    common_io.add_argument("--female-json", default="female.json")
    common_io.add_argument("--male-outfits-json", default="male_outfits.json")
    common_io.add_argument("--female-outfits-json", default="female_outfits.json")

    p1 = sub.add_parser("process-items", parents=[common_io], help="Process images from uploads/Male and uploads/Female into wardrobe JSON")
    p1.add_argument("--concurrency", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    p1.add_argument("--force", action="store_true", help="Reprocess even if outputs exist")
    p1.add_argument("--skip-existing", action="store_true", help="Skip items already in processed_items and wardrobe JSON")
    p1.set_defaults(func=_cmd_process_items)

    p_ingest = sub.add_parser("process-items-ingest", parents=[common_io], help="Ingest images via CLI: assign image_id, process, merge by image_id")
    p_ingest.add_argument("--add-image", nargs="+", required=True, metavar="PATH", help="One or more image file paths to ingest")
    p_ingest.add_argument("--gender", choices=["male", "female"], required=True)
    p_ingest.add_argument("--id", nargs="+", metavar="ID", help="Optional image_id overrides (one per --add-image)")
    p_ingest.add_argument("--logs-dir", default="logs", help="Directory for batch manifests")
    p_ingest.add_argument("--concurrency", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    p_ingest.add_argument("--force", action="store_true")
    p_ingest.add_argument("--skip-existing", action="store_true", help="Skip if processed and in wardrobe")
    p_ingest.set_defaults(func=_cmd_process_items_ingest)

    p2 = sub.add_parser("generate-outfits", parents=[common_io], help="Generate outfits + collages from wardrobe JSON")
    p2.add_argument("--gender", choices=["male", "female", "all"], default="all")
    p2.add_argument("--max-outfits", type=int, default=0, help="0 means no cap (may be large)")
    p2.add_argument("--max-outerwear-per-pair", type=int, default=10)
    p2.add_argument("--image-source-base", default="processed_items", help="Base dir for images; use processed_items (flat) or uploads (Male/Female).")
    p2.set_defaults(func=_cmd_generate_outfits)

    p3 = sub.add_parser("run-all", parents=[common_io], help="Run end-to-end: process-items then generate-outfits")
    p3.add_argument("--concurrency", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    p3.add_argument("--force", action="store_true")
    p3.add_argument("--skip-existing", action="store_true", help="Skip already-processed items")
    p3.add_argument("--max-outfits", type=int, default=0)
    p3.add_argument("--max-outerwear-per-pair", type=int, default=10)
    p3.add_argument("--image-source-base", default="processed_items", help="Base dir for collage images; use processed_items (flat) or uploads (Male/Female)")
    p3.set_defaults(func=_cmd_run_all)

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return int(args.func(args))

