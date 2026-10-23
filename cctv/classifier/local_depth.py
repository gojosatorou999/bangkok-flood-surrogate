"""Fully local, open-source reference-object depth estimation.

Same idea as vlm_depth.py (find a known-size object, see where the
waterline sits against it, let depth_geometry.py do the arithmetic) but
with NO external API call and NO per-image cost:

- Object detection: YOLO (ultralytics, MIT licensed) -- car/motorcycle/
  bench bounding boxes.
- Human landmarks: MediaPipe Pose (Apache 2.0) -- actual pixel
  coordinates for ankle/knee/hip/shoulder, not a text guess.
- Waterline: the same HSV water-color heuristic already in
  write_obs.py, applied per-object instead of whole-frame.

Everything runs on-device; the only network activity is a one-time
download of the YOLO/MediaPipe model weights (not of any CCTV photo).

Object sub-landmark positions for cars/motorcycles/benches are inferred
from the bounding box using the *same* REFERENCE_HEIGHTS_M table as
depth_geometry.py (landmark height / full-object height = fraction of
bbox from the ground up) -- so there's exactly one place reference
heights are defined, not two tables that can drift apart.

[ASSUMPTION] bbox-fraction placement assumes a roughly side-on or
3/4 view of the vehicle; a straight head-on shot will misplace
door_sill/window_sill. No worse than the water-color-only heuristic it
replaces, and it says so in its own `confidence` field.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image

from .depth_geometry import REFERENCE_HEIGHTS_M, ObjectReading, estimate_depth

# COCO class -> our object_type + full-height landmark (the landmark whose
# REFERENCE_HEIGHTS_M mid-value equals the object's total height off the
# ground, used to convert the bbox pixel height into a metres-per-pixel scale).
YOLO_CLASS_MAP = {
    "car": ("car", "roof"),
    "truck": ("car", "roof"),
    "motorcycle": ("motorcycle", "handlebar"),
    "bench": ("bus_bench", "seat"),
    # [ASSUMPTION] YOLO (COCO-trained, no flood scenes in training data) reads
    # a half-submerged car as "boat" -- confirmed on MANUAL-0002 (0.75 conf).
    # Treating "boat" as a candidate submerged car is a deliberate domain
    # patch for this flood-CCTV context, not a general fix -- it will
    # misfire on any frame that contains an actual boat (plausible on a
    # flooded street used for water transport, e.g. MANUAL-0009's background).
    "boat": ("car", "roof"),
}

# Landmarks to probe for each object type, ground-up (nearest-ground first) --
# mirrors the order water is checked for people, below.
_LANDMARK_ORDER = {
    "car": ["wheel_bottom", "door_sill", "wheel_top", "bonnet", "window_sill", "roof"],
    "motorcycle": ["seat", "handlebar"],
    "bus_bench": ["seat"],
    "person_adult": ["ankle", "knee", "thigh", "waist", "chest", "shoulder"],
}

_YOLO_MODEL = None
_POSE_LANDMARKER = None
_POSE_MODEL_PATH = Path(__file__).parent / "models" / "pose_landmarker_lite.task"
_POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)


_YOLO_WEIGHTS_PATH = Path(__file__).parent / "models" / "yolo11n.pt"


def _get_yolo():
    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        from ultralytics import YOLO  # noqa: PLC0415
        _YOLO_MODEL = YOLO(str(_YOLO_WEIGHTS_PATH))  # auto-downloads weights here on first use
    return _YOLO_MODEL


def _ensure_pose_model() -> Path:
    if not _POSE_MODEL_PATH.exists():
        import httpx  # noqa: PLC0415
        _POSE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        resp = httpx.get(_POSE_MODEL_URL, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        _POSE_MODEL_PATH.write_bytes(resp.content)
    return _POSE_MODEL_PATH


def _get_pose_landmarker():
    global _POSE_LANDMARKER
    if _POSE_LANDMARKER is None:
        import mediapipe as mp  # noqa: PLC0415
        model_path = _ensure_pose_model()
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_poses=4,
        )
        _POSE_LANDMARKER = mp.tasks.vision.PoseLandmarker.create_from_options(options)
    return _POSE_LANDMARKER


def _water_mask(rgb: np.ndarray) -> np.ndarray:
    """Boolean water-likely mask, same four HSV signatures as write_obs.py's
    _water_pixel_pct, but returned pixel-aligned instead of averaged to a
    scalar -- so we can ask "is THIS object's bounding box wet"."""
    arr = rgb.astype(np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin
    with np.errstate(invalid="ignore", divide="ignore"):
        hue = np.where(
            delta == 0, 0.0,
            np.where(cmax == r, ((g - b) / delta) % 6 / 6,
            np.where(cmax == g, ((b - r) / delta + 2) / 6,
                                ((r - g) / delta + 4) / 6))
        )
    sat = np.where(cmax == 0, 0.0, delta / cmax)
    val = cmax

    blue_water = (hue >= 0.50) & (hue <= 0.72) & (sat >= 0.08) & (sat <= 0.65) & (val >= 0.15) & (val <= 0.80)
    brown_water = (hue >= 0.02) & (hue <= 0.12) & (sat >= 0.20) & (sat <= 0.85) & (val >= 0.15) & (val <= 0.65)
    grey_water = (sat <= 0.12) & (val >= 0.30) & (val <= 0.72) & (np.abs(r - g) <= 0.06) & (np.abs(g - b) <= 0.06)
    wet_road = (sat <= 0.18) & (val >= 0.05) & (val <= 0.32)

    score = (blue_water * 1.0 + brown_water * 0.90 + grey_water * 0.80 + wet_road * 0.35)
    return np.clip(score, 0.0, 1.0) >= 0.5


def _row_is_wet(mask: np.ndarray, y: int, x0: int, x1: int, threshold: float = 0.45) -> bool:
    h = mask.shape[0]
    y = max(0, min(h - 1, y))
    band = mask[max(0, y - 2): y + 3, max(0, x0): max(x0 + 1, x1)]
    if band.size == 0:
        return False
    return float(band.mean()) >= threshold


def _detect_objects(image_path: Path) -> list[ObjectReading]:
    img = Image.open(image_path).convert("RGB")
    rgb = np.asarray(img)
    mask = _water_mask(rgb)
    h, w = rgb.shape[:2]

    readings: list[ObjectReading] = []

    # --- vehicles / benches via YOLO ---
    yolo = _get_yolo()
    results = yolo.predict(rgb, verbose=False, conf=0.35)[0]
    names = results.names
    for box in results.boxes:
        cls_name = names[int(box.cls[0])]
        mapped = YOLO_CLASS_MAP.get(cls_name)
        if mapped is None:
            continue
        obj_type, full_landmark = mapped
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        x1, x2 = int(max(0, x1)), int(min(w, x2))
        y1, y2 = int(max(0, y1)), int(min(h, y2))
        bbox_h = y2 - y1
        if bbox_h <= 0:
            continue
        full_height_m = REFERENCE_HEIGHTS_M[(obj_type, full_landmark)][1]

        order = _LANDMARK_ORDER[obj_type]
        wet_landmark = None
        for lm in order:  # ground-up
            frac = REFERENCE_HEIGHTS_M[(obj_type, lm)][1] / full_height_m
            y_px = y2 - int(frac * bbox_h)  # pixel row for this landmark
            if _row_is_wet(mask, y_px, x1, x2):
                wet_landmark = lm
            else:
                break  # dry landmark reached; stop scanning upward

        if wet_landmark is None:
            continue  # fully dry object, no reading worth reporting
        relation = "fully_submerged" if wet_landmark == order[-1] else "at"
        readings.append(ObjectReading(obj_type, wet_landmark, relation, vlm_confidence="medium"))

    # --- people via MediaPipe Pose ---
    import mediapipe as mp  # noqa: PLC0415
    landmarker = _get_pose_landmarker()
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    pose_result = landmarker.detect(mp_image)

    PL = mp.tasks.vision.PoseLandmark
    for person in pose_result.pose_landmarks:
        def pt(idx):
            lm = person[idx]
            return lm.x * w, lm.y * h, getattr(lm, "visibility", 1.0)

        la_x, la_y, la_v = pt(PL.LEFT_ANKLE)
        ra_x, ra_y, ra_v = pt(PL.RIGHT_ANKLE)
        lk_x, lk_y, lk_v = pt(PL.LEFT_KNEE)
        rk_x, rk_y, rk_v = pt(PL.RIGHT_KNEE)
        lh_x, lh_y, lh_v = pt(PL.LEFT_HIP)
        rh_x, rh_y, rh_v = pt(PL.RIGHT_HIP)
        ls_x, ls_y, ls_v = pt(PL.LEFT_SHOULDER)
        rs_x, rs_y, rs_v = pt(PL.RIGHT_SHOULDER)

        ankle_y, ankle_vis = (la_y + ra_y) / 2, min(la_v, ra_v)
        knee_y, knee_vis = (lk_y + rk_y) / 2, min(lk_v, rk_v)
        hip_y, hip_vis = (lh_y + rh_y) / 2, min(lh_v, rh_v)
        shoulder_y, shoulder_vis = (ls_y + rs_y) / 2, min(ls_v, rs_v)
        thigh_y = (knee_y + hip_y) / 2
        chest_y = (hip_y + shoulder_y) / 2
        x_center = (la_x + ra_x + ls_x + rs_x) / 4
        x0, x1 = int(x_center - 0.08 * w), int(x_center + 0.08 * w)

        landmark_ys = [
            ("ankle", ankle_y, ankle_vis), ("knee", knee_y, knee_vis),
            ("thigh", thigh_y, min(knee_vis, hip_vis)), ("waist", hip_y, hip_vis),
            ("chest", chest_y, min(hip_vis, shoulder_vis)), ("shoulder", shoulder_y, shoulder_vis),
        ]
        if ankle_vis < 0.3:  # legs not visible at all -- nothing usable
            continue

        wet_landmark, wet_conf = None, "medium"
        for name, y, vis in landmark_ys:
            if vis < 0.3:
                break
            if _row_is_wet(mask, int(y), x0, x1):
                wet_landmark = name
                wet_conf = "high" if vis > 0.7 else "medium"
            else:
                break

        if wet_landmark is None:
            continue
        relation = "fully_submerged" if wet_landmark == "shoulder" else "at"
        readings.append(ObjectReading("person_adult", wet_landmark, relation, vlm_confidence=wet_conf))

    return readings


def analyze_frame(image_path: Path) -> dict:
    readings = _detect_objects(image_path)
    estimate = estimate_depth(readings)
    return {
        "image": str(image_path),
        "readings": [asdict(r) for r in readings],
        "estimate": asdict(estimate),
    }


def main() -> None:
    import json
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m cctv.classifier.local_depth <image_path> [...]")
        raise SystemExit(1)
    for p in sys.argv[1:]:
        print(json.dumps(analyze_frame(Path(p)), indent=2))


if __name__ == "__main__":
    main()
