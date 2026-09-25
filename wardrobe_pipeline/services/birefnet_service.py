"""
BiRefNet Background Removal Service (PyTorch)

High-quality background removal using the "ZhengPeng7/BiRefNet" checkpoint via
transformers. Thread-safe lazy initialization; CPU by default.

This implementation returns **transparent PNG** bytes (pipeline contract).
"""

from __future__ import annotations

import io
import logging
import threading
import time

from PIL import Image, ImageOps

from wardrobe_pipeline.config.settings import settings

logger = logging.getLogger(__name__)


class BiRefNetService:
    _init_lock = threading.Lock()
    _initialized = False
    _device = "cpu"
    _model = None
    _transform = None

    @classmethod
    def _ensure_initialized(cls) -> None:
        if cls._initialized:
            logger.debug("[BIREFNET] Already initialized, skipping")
            return
        with cls._init_lock:
            if cls._initialized:
                return

            birefnet_enabled = getattr(settings, "birefnet_enabled", False)
            if not birefnet_enabled:
                logger.info("[BIREFNET] Disabled via settings; using fallback passthrough")
                cls._initialized = True
                return

            try:
                import torch  # noqa: F401
                from torchvision import transforms
                from transformers import AutoModelForImageSegmentation

                device = "cpu"
                logger.info("[BIREFNET] Using CPU device")

                load_start = time.time()
                model = AutoModelForImageSegmentation.from_pretrained(
                    "ZhengPeng7/BiRefNet",
                    trust_remote_code=True,
                )
                logger.debug("[BIREFNET] Model loaded in %.2fs", time.time() - load_start)

                model.to(device)
                model.float()
                model.eval()

                transform = transforms.Compose(
                    [
                        transforms.Resize((1024, 1024)),
                        transforms.ToTensor(),
                        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
                    ]
                )

                cls._model = model
                cls._device = device
                cls._transform = transform
                cls._initialized = True
                logger.info("[BIREFNET] Initialized on device: %s", device)
            except Exception as e:
                logger.error("[BIREFNET] Failed to initialize: %s", e, exc_info=True)
                logger.error("[BIREFNET] Falling back to opaque PNG passthrough")
                cls._initialized = True
                cls._model = None
                cls._device = "cpu"
                cls._transform = None

    @staticmethod
    def _to_u8_mask(tensor) -> Image.Image:
        import torch

        t = tensor.clamp(0, 1)
        t = (t * 255).to(torch.uint8).cpu()
        arr = t.numpy()
        return Image.fromarray(arr, mode="L")

    @classmethod
    def remove_bg_png(cls, image_bytes: bytes) -> bytes:
        """
        Returns a transparent **PNG** (RGBA) byte-string.
        If BiRefNet isn't available, returns an opaque RGBA PNG of the original.
        """
        cls._ensure_initialized()

        # Load image, normalize orientation, convert to RGB
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            rgb = img.convert("RGB")
            original_size = rgb.size

        if cls._model is None:
            rgba = rgb.convert("RGBA")
            out = io.BytesIO()
            rgba.save(out, format="PNG", optimize=True)
            return out.getvalue()

        import torch

        # Preprocess
        input_tensor = cls._transform(rgb).unsqueeze(0).to(cls._device)

        # Inference
        with torch.inference_mode():
            outputs = cls._model(input_tensor)

        # Extract mask-like tensor
        if isinstance(outputs, (list, tuple)):
            pred = outputs[-1]
        elif hasattr(outputs, "logits"):
            pred = outputs.logits
        else:
            pred = outputs

        pred = pred.sigmoid()
        pred_hw = pred[0].squeeze()

        mask_pil = cls._to_u8_mask(pred_hw).resize(original_size, Image.LANCZOS)

        rgba = rgb.copy()
        if mask_pil.mode != "L":
            mask_pil = mask_pil.convert("L")
        rgba.putalpha(mask_pil)

        out = io.BytesIO()
        rgba.save(out, format="PNG", optimize=True)
        return out.getvalue()

