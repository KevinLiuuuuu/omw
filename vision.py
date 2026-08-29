"""Optional Gemini vision helper: guess how full a pantry's shelves are from a photo.

One public function, ``estimate_capacity(images)``, which takes a list of image
byte strings (one per shelf photo) and returns a dict with ``perishables_pct`` /
``non_perishables_pct`` / ``toiletries_pct`` (each a 0-100 int) or ``None`` if the
estimate could not be produced. A single ``bytes`` object is also accepted.

This is a pre-fill convenience for the capacity sliders, nothing more. It never
raises: every failure path returns ``None`` so the sliders stay manual.
"""

import io
import json
import logging
import os

from google import genai
from google.genai import types
from PIL import Image

# Current recommended multimodal Flash model (verified against
# ai.google.dev/gemini-api/docs/models, 2026-08). Swap to "gemini-2.5-flash" if
# 3.7 isn't available on the account.
MODEL = "gemini-3.5-flash-lite"

_log = logging.getLogger(__name__)

# Hard ceiling on the request. HttpOptions.timeout is in milliseconds. The Flask
# endpoint also bounds the call independently in case the SDK's own timeout slips.
# The API rejects any deadline under 10s ("Minimum allowed deadline is 10s"), so
# keep this above that floor. Image calls have been observed at 15-20s even with a
# small payload and a trivial prompt, so give them real headroom.
TIMEOUT_MS = 45000

_PROMPT = (
    "These photos show different shelves at the same community food bank. "
    "Estimate how full the shelves are across all the photos together, for each "
    "of these categories, as a percentage from 0 (empty) to 100 (completely "
    "stocked): perishables (fresh/refrigerated food), non-perishables (canned "
    "and dry goods), and toiletries (hygiene products). If a category is not "
    "visible in any of the photos, return null for it. Also return your overall "
    "confidence in the estimate from 0.0 to 1.0. In \"description\", give a short "
    "description of what is visible across all the photos, maximum 15 words, "
    "naming the actual items you can see. "
    "Return only the JSON object. No prose, no markdown fences."
)

# Plain JSON-schema dict rather than a Pydantic class: passing a Pydantic model as
# response_schema makes the SDK introspect it as a callable tool, which trips
# automatic function calling and silently drops response_mime_type, so the model
# never actually enters JSON mode.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "perishables": {"type": "integer", "minimum": 0, "maximum": 100},
        "non_perishables": {"type": "integer", "minimum": 0, "maximum": 100},
        "toiletries": {"type": "integer", "minimum": 0, "maximum": 100},
        "description": {"type": "string"},
    },
    "required": ["perishables", "non_perishables", "toiletries"],
}

_CATEGORIES = (
    ("perishables", "perishables_pct"),
    ("non_perishables", "non_perishables_pct"),
    ("toiletries", "toiletries_pct"),
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


def _loads_loose(text):
    """Best-effort JSON parse of a model reply that may carry prose or fences."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(stripped[start : end + 1])
    except (ValueError, TypeError):
        return None


def _coerce_estimate(data):
    """Turn a raw dict into {..._pct: int 0-100}, or None if a category is missing.

    An optional "description" string is passed through (trimmed to 120 chars) when
    present and usable; a missing or unusable description never fails the estimate.
    """
    if not isinstance(data, dict):
        return None
    out = {}
    for src, dst in _CATEGORIES:
        if src not in data or data[src] is None:
            return None
        try:
            out[dst] = max(0, min(100, int(data[src])))
        except (TypeError, ValueError):
            return None
    description = data.get("description")
    if isinstance(description, str) and description.strip():
        out["description"] = description.strip()[:120]
    return out


def _parse_response(response):
    """Pull a usable estimate out of ``response`` -- parsed dict first, then text."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        result = _coerce_estimate(parsed)
        if result is not None:
            return result
    return _coerce_estimate(_loads_loose(getattr(response, "text", None)))


def estimate_capacity(images):
    """Ask Gemini to estimate shelf fullness from one or more shelf photos.

    ``images`` is a list of image byte strings (a single ``bytes`` object is also
    accepted and treated as a one-photo list); at most the first 4 are used.

    Returns a dict with perishables_pct / non_perishables_pct / toiletries_pct
    (each a 0-100 int), or ``None`` on any failure -- missing key, bad image, API
    error, truncated or unparseable reply. Never raises.
    """
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            _log.warning("GEMINI_API_KEY is not set; skipping photo estimate")
            return None

        if isinstance(images, (bytes, bytearray)):
            images = [images]
        images = list(images)[:4]
        if not images:
            _log.warning("no images passed to photo estimate")
            return None

        optimized = [_preprocess(image_bytes) for image_bytes in images]

        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=TIMEOUT_MS),
        )

        config_kwargs = dict(
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
            temperature=0.0,
            max_output_tokens=2048,
            tools=None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        contents = [
            types.Part.from_bytes(data=data, mime_type="image/jpeg")
            for data in optimized
        ]
        contents.append(_PROMPT)

        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        try:
            finish_reason = response.candidates[0].finish_reason
        except (AttributeError, IndexError, TypeError):
            finish_reason = None
        _log.info("Gemini estimate finish_reason=%s", finish_reason)

        try:
            usage_metadata = getattr(response, "usage_metadata", None)
        except (AttributeError, TypeError):
            usage_metadata = None
        _log.info("Gemini estimate usage_metadata=%s", usage_metadata)

        result = _parse_response(response)
        if result is None:
            _log.error(
                "Gemini estimate did not parse; raw text: %r",
                getattr(response, "text", None),
            )
        return result
    except Exception:
        _log.exception("photo capacity estimate failed")
        return None


if __name__ == "__main__":
    import sys
    import time

    logging.basicConfig(level=logging.INFO)

    images = []
    for path in sys.argv[1:]:
        with open(path, "rb") as fh:
            images.append(fh.read())

    started = time.monotonic()
    outcome = estimate_capacity(images)
    elapsed = time.monotonic() - started

    print(f"result:  {outcome}")
    print(f"elapsed: {elapsed:.1f}s")
