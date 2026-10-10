"""Writes data/cctv/cctv_obs.parquet — handoff H6 to Rishanth. See docs/VARUN_IMPLEMENTATION.md §6 T53.

Run via `make cctv-classify` (embeds + zero-shot-scores any new frames,
then builds the observation table).
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

FRAMES_PARQUET = Path("data/cctv/cctv_frames.parquet")
ZEROSHOT_CACHE = Path("cctv/classifier/cache/zeroshot_v0.parquet")
PROBE_CHOSEN = Path("cctv/classifier/models/CHOSEN.txt")
THRESHOLDS_PATH = Path("configs/thresholds.yaml")
OUT_PATH = Path("data/cctv/cctv_obs.parquet")

PROB_COLS = ["p_normal", "p_waterlogging", "p_flooding", "p_severe", "p_unusable"]
OUT_COLUMNS = [
    "cam_id",
    "ts_utc",
    "class",
    "p_normal",
    "p_waterlogging",
    "p_flooding",
    "p_severe",
    "p_unusable",
    "class_smoothed",
    "depth_proxy_bin",
    "depth_proxy_m",
    "water_pixel_pct",
    "is_submerged",
    "quality_flag",
    "frame_sha1",
    "model_version",
    "data_class",
    "is_mock",
]


def model_version() -> str:
    # T52 hasn't landed yet (no labelled probe), so this is always clip-zs-v0
    # today; switches automatically once cctv/classifier/models/CHOSEN.txt exists.
    return "clip-probe-v1" if PROBE_CHOSEN.exists() else "clip-zs-v0"


def _depth_proxy_bins() -> dict:
    if not THRESHOLDS_PATH.exists():
        return {}
    return (yaml.safe_load(THRESHOLDS_PATH.read_text()) or {}).get("cctv_depth_proxy_bins_m", {})


def _depth_proxy_bin_for_class(cls: str, bins: dict) -> str | None:
    if cls == "UNUSABLE" or cls not in bins or bins[cls] is None:
        return None
    lo, hi = bins[cls]
    return f"{lo:.2f}-{hi:.2f}" if hi is not None else f"{lo:.2f}-"


def _water_pixel_pct(thumb_path: str | None) -> float | None:
    """Fraction of thumbnail pixels that look like standing water.

    Improvements over naive blue-only detection:
    - Analyses only the bottom 60% of the frame (water pools at the bottom
      of road-level CCTV shots; sky/signage at the top create false positives).
    - Four complementary water signatures:
        1. Clear / blue water  – blue-shifted hues, low-medium saturation
        2. Murky / brown flood – orange-brown hues, high saturation
           (very common in Bangkok drainage overflow)
        3. Reflective grey     – near-achromatic, medium brightness
           (sky reflections on shallow standing water)
        4. Wet road sheen      – very dark, low-saturation surface
           (tarmac soaked through but not yet pooling)
    - Returns None when the thumbnail cannot be opened rather than crashing.
    """
    if not thumb_path:
        return None
    try:
        from PIL import Image  # noqa: PLC0415
        img = Image.open(thumb_path).convert("RGB")
        # Work at a fixed size for speed; keep aspect ratio
        img = img.resize((120, 90), Image.LANCZOS)
        h_px = img.height
        # Crop to lower 60% — water pools at the bottom of road-cam shots
        crop_top = int(h_px * 0.40)
        img = img.crop((0, crop_top, img.width, h_px))

        arr = np.asarray(img, dtype=np.float32) / 255.0
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

        # 1. Clear / blue water (canals, clean flood)
        blue_water = (
            (hue >= 0.50) & (hue <= 0.72) &
            (sat >= 0.08) & (sat <= 0.65) &
            (val >= 0.15) & (val <= 0.80)
        )
        # 2. Murky / brown floodwater (Bangkok drainage / sewer overflow)
        brown_water = (
            (hue >= 0.02) & (hue <= 0.12) &
            (sat >= 0.20) & (sat <= 0.85) &
            (val >= 0.15) & (val <= 0.65)
        )
        # 3. Reflective grey (shallow water reflecting overcast sky)
        grey_water = (
            (sat <= 0.12) &
            (val >= 0.30) & (val <= 0.72) &
            (np.abs(r - g) <= 0.06) & (np.abs(g - b) <= 0.06)
        )
        # 4. Wet road sheen (very dark, near-achromatic — flooded tarmac)
        wet_road = (
            (sat <= 0.18) &
            (val >= 0.05) & (val <= 0.32)
        )

        # Weight each mask by confidence so noisy pixels count less.
        # [ASSUMPTION] grey_water raised 0.60->0.80: verified against a real
        # submerged-car frame (BMAT-0011) where turbid floodwater under
        # overcast light reads as near-achromatic -- mean saturation ~0.10,
        # not the >=0.20 brown_water needs -- so ~84% of its water surface
        # was only ever caught by grey_water, and the old 0.60 weight (tuned
        # for "shallow puddle reflecting sky", a different real signature)
        # undercounted deep/extensive flooding whenever it wasn't vividly
        # blue or saturated brown. Still an unvalidated heuristic either way
        # (no labelled ground truth exists yet -- T52 blocked on HU5): a
        # known-dry mock fixture frame (BMAT-0000, flat grey synthetic road)
        # already read ~59% "water" even at the old weight, from grey dry
        # pavement matching the same mask. That case's depth_proxy_m stays
        # correct regardless (p_severe≈0 there, so the pixel-based scaling
        # below never engages) -- but the raw water_pixel_pct the UI shows
        # can still look wrong on a dry grey road. Revisit with real labels.
        score = (
            blue_water.astype(np.float32) * 1.0 +
            brown_water.astype(np.float32) * 0.90 +
            grey_water.astype(np.float32) * 0.80 +
            wet_road.astype(np.float32) * 0.35
        )
        # Cap per-pixel score at 1.0 (overlapping masks shouldn't inflate)
        score = np.clip(score, 0.0, 1.0)
        return float(round(score.mean(), 4))
    except Exception:  # noqa: BLE001
        return None


# Water-pixel thresholds for scaling depth within SEVERE_FLOODING.
# Physical reference points at a road-level CCTV (~2m mount height):
#   0.10 = ankle puddles (~10 cm)
#   0.25 = knee level     (~30 cm)
#   0.40 = car door sill  (~50 cm)
#   0.55 = car bonnet     (~80 cm)  ← 54 % pixel case
#   0.70 = car roof       (~120 cm)
#   0.85 = car fully under (~150 cm+)
_SEVERE_PIXEL_BREAKPOINTS = [
    (0.00, 0.30),   # water_pct < 10 % → 30 cm
    (0.10, 0.40),
    (0.25, 0.55),
    (0.40, 0.70),
    (0.55, 0.90),   # ← 54% water_pct → ~90 cm
    (0.70, 1.20),
    (0.85, 1.50),
]


def _severe_depth_from_pixels(water_pct: float) -> float:
    """Linear-interpolate depth in metres from water pixel percentage.
    Only used when argmax class is SEVERE_FLOODING."""
    pts = _SEVERE_PIXEL_BREAKPOINTS
    for i in range(len(pts) - 1):
        p0, d0 = pts[i]
        p1, d1 = pts[i + 1]
        if water_pct <= p1:
            t = (water_pct - p0) / max(p1 - p0, 1e-6)
            return round(d0 + t * (d1 - d0), 3)
    return pts[-1][1]  # above last breakpoint → max


def _depth_estimate_combined(
    probs: dict[str, float],
    bins: dict,
    water_pixel_pct: float | None,
) -> float | None:
    """Best-estimate depth in metres combining CLIP probabilities + pixel water %.

    For NORMAL / WATERLOGGING / FLOODING the CLIP-weighted blend is used
    (smooth, more precise than argmax alone).

    For SEVERE_FLOODING the pixel fraction drives the estimate: 54 % water
    pixels at road-cam height correspond to ~80-90 cm (car bonnet level),
    not the naive 47 cm cap.  When water_pixel_pct is unavailable we fall
    back to the CLIP-weighted value.
    """
    class_map = {
        "p_normal": "NORMAL",
        "p_waterlogging": "WATERLOGGING",
        "p_flooding": "FLOODING",
        "p_severe": "SEVERE_FLOODING",
    }
    # CLIP-weighted base (ignoring p_unusable in the depth blend)
    total_w = 0.0
    total_m = 0.0
    for prob_key, cls in class_map.items():
        w = probs.get(prob_key, 0.0)
        if w <= 0 or cls not in bins or bins[cls] is None:
            continue
        lo, hi = bins[cls]
        mid = (lo + (hi if hi is not None else lo + 0.40)) / 2
        total_w += w
        total_m += w * mid
    if total_w == 0:
        return None
    clip_depth = total_m / total_w

    p_severe = probs.get("p_severe", 0.0)

    # When SEVERE_FLOODING dominates AND we have pixel data, use the pixel
    # scale (which extends to 1.50 m) weighted by SEVERE confidence.
    if p_severe >= 0.50 and water_pixel_pct is not None:
        pixel_depth = _severe_depth_from_pixels(water_pixel_pct)
        # Blend: high p_severe → trust pixels more; mixed → average with CLIP
        depth = p_severe * pixel_depth + (1.0 - p_severe) * clip_depth
    else:
        depth = clip_depth

    return round(depth, 3)



def _smoothed_series(df: pd.DataFrame) -> list[str | None]:
    """Majority of the last <=3 USABLE frames per camera, in ts order; ties -> most recent.

    Assumes `df` is sorted by (cam_id, ts_utc) with a plain RangeIndex.
    """
    out: list[str | None] = [None] * len(df)
    for _cam_id, idx in df.groupby("cam_id").groups.items():
        window: deque[str] = deque(maxlen=3)
        for i in idx:
            row_class = df.at[i, "class"]
            if row_class != "UNUSABLE":
                window.append(row_class)
            if not window:
                continue
            counts = Counter(window)
            top = max(counts.values())
            tied = {c for c, n in counts.items() if n == top}
            if len(tied) == 1:
                out[i] = next(iter(tied))
            else:
                for c in reversed(window):
                    if c in tied:
                        out[i] = c
                        break
    return out


def build_cctv_obs(
    frames_parquet: Path = FRAMES_PARQUET,
    zeroshot_cache: Path = ZEROSHOT_CACHE,
    out_path: Path = OUT_PATH,
) -> pd.DataFrame:
    frames = pd.read_parquet(frames_parquet).sort_values(["cam_id", "ts_utc"]).reset_index(drop=True)
    zs = (
        pd.read_parquet(zeroshot_cache)
        if zeroshot_cache.exists()
        else pd.DataFrame(columns=["sha1", *PROB_COLS, "argmax_class"])
    )
    zs = zs.drop_duplicates(subset="sha1").set_index("sha1")

    bins = _depth_proxy_bins()
    version = model_version()

    rows = []
    for _, row in frames.iterrows():
        if row["quality_flag"] == "OK" and row["sha1"] in zs.index:
            zrow = zs.loc[row["sha1"]]
            cls = zrow["argmax_class"]
            probs = {c: float(zrow[c]) for c in PROB_COLS}
        else:
            # not OK, or OK but not embedded yet -> treated as unusable (never invented)
            cls = "UNUSABLE"
            probs = {c: 0.0 for c in PROB_COLS}
            probs["p_unusable"] = 1.0

        # Resolve the thumbnail path so we can compute water pixel %
        ts_str = str(row["ts_utc"])
        date_str = ts_str[:10].replace("-", "")
        ts_file = ts_str.replace("-", "").replace(":", "")
        thumb_path = f"data/cctv/thumbs/{row['cam_id']}/{date_str}/{row['cam_id']}_{ts_file}.jpg"
        wpct = _water_pixel_pct(thumb_path) if cls != "UNUSABLE" else None

        # Combined depth: CLIP-weighted blend, but for SEVERE_FLOODING scaled
        # by water_pixel_pct (a 54%-submerged-car frame reads as ~0.89 m, not
        # a flat 0.47 m bin-midpoint cap) -- see _depth_estimate_combined.
        depth_m = _depth_estimate_combined(probs, bins, wpct) if cls != "UNUSABLE" else None

        # [ASSUMPTION] "submerged" = classifier already confident this frame
        # is SEVERE_FLOODING (p_severe >= 0.50, same gate _depth_estimate_combined
        # uses) AND water_pixel_pct is at/above the car-roof breakpoint (0.70,
        # see _SEVERE_PIXEL_BREAKPOINTS). Gating on p_severe too (not pixel %
        # alone) matters: grey_water's mask can't distinguish turbid floodwater
        # from plain dry grey pavement by colour alone (see the grey_water
        # weight comment above) -- a dry mock frame (BMAT-0000) reads ~79%
        # "water" on pixels alone, which would otherwise flag it SUBMERGED
        # despite p_severe≈0. None (not False) when water_pixel_pct is unknown.
        is_submerged = (probs.get("p_severe", 0.0) >= 0.50 and wpct >= 0.70) if wpct is not None else None

        rows.append(
            {
                "cam_id": row["cam_id"],
                "ts_utc": row["ts_utc"],
                "class": cls,
                **probs,
                "depth_proxy_bin": _depth_proxy_bin_for_class(cls, bins),
                "depth_proxy_m": depth_m,
                "water_pixel_pct": wpct,
                "is_submerged": is_submerged,
                "quality_flag": row["quality_flag"],
                "frame_sha1": row["sha1"],
                "model_version": version,
                "data_class": "OBSERVED",
                "is_mock": False,
            }
        )


    out = pd.DataFrame(rows)
    out["class_smoothed"] = _smoothed_series(out)
    out = out[OUT_COLUMNS]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="auto", choices=["auto", "zs", "probe"])
    args = parser.parse_args()

    if args.model == "probe" and not PROBE_CHOSEN.exists():
        raise SystemExit("no probe chosen yet (T52 hasn't run) -- use --model zs/auto")

    # make cctv-classify is the one-shot entry point: embed + score + write.
    from .embed import embed_new_frames
    from .zeroshot import write_zeroshot

    embed_new_frames()
    write_zeroshot()

    df = build_cctv_obs()
    print(f"wrote {len(df)} rows -> {OUT_PATH} (model_version={model_version()})")


if __name__ == "__main__":
    main()
