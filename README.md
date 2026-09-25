# Open Day Mirror — Wardrobe Processing Pipeline

Offline preparation pipeline to:
- remove backgrounds from uploaded clothing images (BiRefNet)
- extract wardrobe metadata (OpenAI Vision)
- generate deterministic outfit combinations
- render outfit collage images

## Outputs
- `processed_items/` — background-removed PNGs
- `male.json`, `female.json` — wardrobe metadata
- `male_outfits.json`, `female_outfits.json` — generated outfits (with embedded item metadata)
- `wardrobe/outfits/` — outfit collage PNGs

## Setup
Create a virtualenv, then install requirements:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Environment variables:
- `KYRA_OPENAI_API_KEY` (required for metadata extraction)
- `BIREFNET_ENABLED` (optional; default `1`)
- `OPENAI_MODEL_VISION` (optional; default `gpt-5.2-vision`)

## CLI
Put raw images in `uploads/Male/` and/or `uploads/Female/`.

Process items from uploads folders (metadata + background removal + JSON storage):

```bash
python -m wardrobe_pipeline process-items
```

Ingest one or more explicit file paths:

```bash
python -m wardrobe_pipeline process-items-ingest --add-image "/abs/path/item1.png" "/abs/path/item2.png" --gender male
```

Generate outfits + collages:

```bash
python -m wardrobe_pipeline generate-outfits --gender all --image-source-base processed_items
```

Run end-to-end:

```bash
python -m wardrobe_pipeline run-all
```

## Notes
- This pipeline is designed to be idempotent: re-running should not duplicate entries (upsert by `image_id`).
- BiRefNet is CPU by default in this implementation.

