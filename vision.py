"""Optional Gemini vision helper: guess how full a pantry's shelves are from a photo.

One public function, ``estimate_capacity(image_bytes)``, which returns a dict with
``perishables_pct`` / ``non_perishables_pct`` / ``toiletries_pct`` (each 0-100 or
None if that category isn't visible) and ``confidence`` (0.0-1.0).

This is a pre-fill convenience for the capacity sliders, nothing more. Callers are
expected to catch exceptions and fall back to manual entry.
"""

import io
import os

from google import genai
from google.genai import types
from PIL import Image
from pydantic import BaseModel, Field

# Current recommended multimodal Flash model (verified against
# ai.google.dev/gemini-api/docs/models, 2026-08). Swap to "gemini-2.5-flash" if
# 3.7 isn't available on the account.
MODEL = "gemini-3.7-flash"

# Hard ceiling on the request. HttpOptions.timeout is in milliseconds. The Flask
# endpoint also bounds the call independently in case the SDK's own timeout slips.
# The API rejects any deadline under 10s ("Minimum allowed deadline is 10s"), so
# keep this above that floor.
TIMEOUT_MS = 12000

_PROMPT = (
    "This is a photo of shelves at a community food bank. Estimate how full the "
    "shelves are for each of these categories, as a percentage from 0 (empty) to "
    "100 (completely stocked): perishables (fresh/refrigerated food), "
    "non-perishables (canned and dry goods), and toiletries (hygiene products). "
    "If a category is not visible in the frame, return null for it. Also return "
    "your overall confidence in the estimate from 0.0 to 1.0."
)


class CapacityEstimate(BaseModel):
    perishables_pct: int | None = Field(
        description="Fullness of the perishable/fresh-food shelves, 0-100, or null "
        "if not visible"
    )
    non_perishables_pct: int | None = Field(
        description="Fullness of the canned/dry-goods shelves, 0-100, or null if "
        "not visible"
    )
    toiletries_pct: int | None = Field(
        description="Fullness of the toiletries/hygiene shelves, 0-100, or null if "
        "not visible"
    )
    confidence: float = Field(
        description="Overall confidence in this estimate, 0.0-1.0"
    )


def _preprocess(image_bytes: bytes, max_dim: int = 512, quality: int = 70) -> bytes:
    """Downscale and re-encode as JPEG to keep the upload small and fast."""
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((max_dim, max_dim))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def _clamp_pct(value):
    if value is None:
        return None
    return max(0, min(100, int(value)))


def estimate_capacity(image_bytes: bytes) -> dict:
    """Ask Gemini to estimate shelf fullness from ``image_bytes``.

    Returns a dict with perishables_pct / non_perishables_pct / toiletries_pct
    (0-100 or None) and confidence (0.0-1.0). Raises on a missing API key, a
    bad image, or any API failure -- the caller handles the fallback.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    optimized = _preprocess(image_bytes)

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=optimized, mime_type="image/jpeg"),
            _PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CapacityEstimate,
            temperature=0.0,
            max_output_tokens=300,
        ),
    )

    estimate: CapacityEstimate = response.parsed
    return {
        "perishables_pct": _clamp_pct(estimate.perishables_pct),
        "non_perishables_pct": _clamp_pct(estimate.non_perishables_pct),
        "toiletries_pct": _clamp_pct(estimate.toiletries_pct),
        "confidence": max(0.0, min(1.0, float(estimate.confidence))),
    }
