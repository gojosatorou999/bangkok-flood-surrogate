"""VLM-assisted reference-object depth estimation (perception only).

Orchestrates a vision-language model (via OpenRouter) to identify known-size
objects in a CCTV frame and describe the waterline relative to them --
never to output a depth number itself. `depth_geometry.py` does all the
arithmetic from that structured description, so every final number is
traceable to an explicit reference height and formula, not to the model's
own (unreliable) sense of scale.

Requires OPENROUTER_API_KEY. Model defaults to a vision-capable Nemotron
model on OpenRouter; override with CCTV_VLM_MODEL.

Usage:
    python -m cctv.classifier.vlm_depth <image_path> [<image_path> ...]
"""
from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import httpx

from .depth_geometry import ObjectReading, estimate_depth

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl:free"

_OBJECT_TYPES = ["car", "motorcycle", "person_adult", "pedestrian_railing", "bus_bench", "curb", "indoor_furniture", "doorway"]
_LANDMARKS_BY_TYPE = {
    "car": ["wheel_bottom", "wheel_top", "door_sill", "bonnet", "window_sill", "roof"],
    "motorcycle": ["seat", "handlebar"],
    "person_adult": ["ankle", "knee", "thigh", "waist", "chest", "shoulder"],
    "pedestrian_railing": ["top", "mid"],
    "bus_bench": ["seat"],
    "curb": ["top"],
    "indoor_furniture": ["low_table_leg", "bed_frame"],
    "doorway": ["threshold"],
}

SYSTEM_PROMPT = f"""You are a visual perception component in a flood-monitoring pipeline. You look at one CCTV/traffic-camera photo and report ONLY what you can see -- you never estimate or state a depth number, a distance, or any measurement in cm/m/inches. A separate deterministic program converts your description into a number; your job is purely to identify objects of known typical size and describe the waterline position against them.

For every object of a known type you can clearly see in the photo, report:
- "object_type": one of {_OBJECT_TYPES}
- "landmark": one of the valid landmarks for that type: {json.dumps(_LANDMARKS_BY_TYPE)}
- "waterline_relation": one of "below" (water is below this landmark), "at" (water line is approximately at this landmark), "above" (water is above this landmark but you can't see how much higher), "fully_submerged" (the whole object/landmark is underwater)
- "confidence": "high" | "medium" | "low" -- your confidence in this specific reading, e.g. "low" if the object is partially occluded or the angle makes it hard to judge

Report every reference object you can identify -- not just one. If NO object of a known type (car, motorcycle, adult person, pedestrian railing, bus bench, curb, indoor furniture, doorway) is clearly visible, or the frame is too dark/blurry/occluded to judge, return an empty "objects" list -- do not force a guess.

Respond with ONLY a JSON object, no markdown fences, no prose, matching exactly:
{{"objects": [{{"object_type": "...", "landmark": "...", "waterline_relation": "...", "confidence": "..."}}], "notes": "one short sentence on anything relevant (occlusion, odd angle, night/IR, etc.)"}}"""


class VLMDepthError(Exception):
    pass


def _image_to_data_url(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _call_vlm(image_path: Path, *, model: str, api_key: str, timeout: float = 60.0) -> dict:
    data_url = _image_to_data_url(image_path)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Identify reference objects and the waterline position in this photo. JSON only."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    resp = httpx.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise VLMDepthError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
    content = resp.json()["choices"][0]["message"]["content"]
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise VLMDepthError(f"non-JSON response: {content[:300]}") from exc


def _parse_objects(raw: dict) -> list[ObjectReading]:
    readings = []
    for obj in raw.get("objects", []):
        try:
            ot, lm, rel = obj["object_type"], obj["landmark"], obj["waterline_relation"]
        except KeyError:
            continue
        if ot not in _OBJECT_TYPES or lm not in _LANDMARKS_BY_TYPE.get(ot, []) or rel not in (
            "below", "at", "above", "fully_submerged"
        ):
            continue  # silently drop malformed entries rather than crash the batch
        readings.append(ObjectReading(ot, lm, rel, obj.get("confidence", "medium")))
    return readings


def analyze_frame(image_path: Path, *, model: str | None = None, api_key: str | None = None) -> dict:
    """Runs one frame through the VLM + geometry pipeline. Returns a dict with
    the raw VLM output, parsed readings, and the final DepthEstimate."""
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise VLMDepthError("OPENROUTER_API_KEY not set")
    model = model or os.environ.get("CCTV_VLM_MODEL", DEFAULT_MODEL)

    raw = _call_vlm(image_path, model=model, api_key=api_key)
    readings = _parse_objects(raw)
    estimate = estimate_depth(readings)

    return {
        "image": str(image_path),
        "model": model,
        "vlm_notes": raw.get("notes", ""),
        "vlm_objects_raw": raw.get("objects", []),
        "readings_parsed": len(readings),
        "estimate": asdict(estimate),
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m cctv.classifier.vlm_depth <image_path> [...]")
        raise SystemExit(1)
    for p in sys.argv[1:]:
        try:
            result = analyze_frame(Path(p))
        except VLMDepthError as exc:
            print(f"{p}: ERROR: {exc}")
            continue
        print(f"{p}: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
