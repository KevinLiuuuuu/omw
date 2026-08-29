"""Optional YOLOv8 helper: count product units on a shelf photo and turn that
count into a rough "how full is it" percentage.

One public function, ``detect_fullness(image_bytes)``, which returns a 0-100 int
or ``None`` if a count could not be produced.

The model at ``models/best.pt`` is a YOLOv8 detector fine-tuned on SKU-110K. It
has a single class, ``{0: 'object'}``, and detects individual product units on a
shelf. It does NOT classify them, so it cannot tell perishables from toiletries
-- it only produces a count.

Like ``vision.py``, this is a pre-fill convenience and never raises: every
failure path returns ``None``. If ultralytics or torch is not importable the
import here fails softly so app startup is unaffected, and ``detect_fullness``
just returns ``None``.
"""

import io
import logging
import os
import time

# Soft import: a missing ultralytics/torch must not break app startup. If this
# fails, YOLO stays None and detect_fullness returns None on every call.
try:
    from ultralytics import YOLO
except Exception:  # ImportError, but also torch load-time errors
    YOLO = None

_log = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "best.pt")

# Box count seen on a single well-stocked reference shelf photo. This was eyeballed
# against one image and is a rough anchor for the "100%" end of the scale, not a
# validated figure -- treat the resulting percentage as a hint, nothing more.
REFERENCE_FULL_COUNT = 81

# Lazy-loaded YOLO model. Never populated at import time: Flask's debug reloader
# imports modules twice, which would load the weights twice.
_model = None


def _get_model():
    """Load the YOLO model once into the module global. Returns None on failure."""
    global _model
    if _model is not None:
        return _model
    if YOLO is None:
        _log.warning("ultralytics is not available; skipping shelf detection")
        return None
    try:
        _model = YOLO(MODEL_PATH)
    except Exception:
        _log.exception("failed to load YOLO model at %s", MODEL_PATH)
        return None
    return _model


def _load_image(image_bytes):
    """Decode ``image_bytes`` into a PIL image ultralytics.predict accepts.

    In-memory decode is practical here, so no temp file is written. Raises if the
    bytes are not a decodable image; callers let that propagate to the ``None``
    return path.
    """
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    return img


def detect_fullness(image_bytes):
    """Count product units in ``image_bytes`` and scale to a 0-100 percentage.

    Returns an int 0-100, or ``None`` on any failure -- missing model, missing
    ultralytics, undecodable image, inference error. Never raises.
    """
    try:
        model = _get_model()
        if model is None:
            return None

        source = _load_image(image_bytes)

        started = time.monotonic()
        results = model.predict(source, conf=0.25, verbose=False)
        elapsed = time.monotonic() - started

        count = 0
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is not None:
                count += len(boxes)

        _log.info("shelf detection: %d boxes in %.1fs", count, elapsed)

        pct = round(count / REFERENCE_FULL_COUNT * 100)
        return max(0, min(100, pct))
    except Exception:
        _log.exception("shelf fullness detection failed")
        return None


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    with open(sys.argv[1], "rb") as fh:
        data = fh.read()

    model = _get_model()
    source = _load_image(data)

    started = time.monotonic()
    results = model.predict(source, conf=0.25, verbose=False)
    elapsed = time.monotonic() - started

    boxes = sum(len(r.boxes) for r in results if getattr(r, "boxes", None) is not None)
    pct = max(0, min(100, round(boxes / REFERENCE_FULL_COUNT * 100)))

    print(f"box count:  {boxes}")
    print(f"percentage: {pct}")
    print(f"elapsed:    {elapsed:.1f}s")
