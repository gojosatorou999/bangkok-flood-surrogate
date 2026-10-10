"""Synthetic MOCK_cctv_obs.parquet for pipeline testing — never metrics.

See docs/VARUN_IMPLEMENTATION.md §6 T53. Samples each camera's class from
the fixture hydraulic depth at its nearest grid cell over the fixture run.

[ASSUMPTION] T54 (camera -> model-cell mapping) hasn't landed yet, so this
uses a plain nearest-cell lookup instead of T54's 30 m buffer + road-clip
logic. Swap in validation.cctv.cam_cells once T54 exists — this file
only exists to exercise the cctv_obs.parquet schema end to end before
real classifications are trustworthy, so the extra precision isn't
worth building T54 early for.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from pyproj import Transformer

from .write_obs import PROB_COLS, _depth_proxy_bin_for_class, _depth_proxy_bins

REGISTRY_PATH = Path("cctv/registry/cameras.geojson")
DEPTH_NC = Path("tools/fixtures/out/MOCK_BKK-S99/M000/depth.nc")
OUT_PATH = Path("data/cctv/MOCK_cctv_obs.parquet")

# Ordered by increasing severity; depth_proxy_bins_m upper edges are checked in this order.
_CLASS_ORDER = ["NORMAL", "WATERLOGGING", "FLOODING", "SEVERE_FLOODING"]
_PROB_COL_FOR_CLASS = {
    "NORMAL": "p_normal",
    "WATERLOGGING": "p_waterlogging",
    "FLOODING": "p_flooding",
    "SEVERE_FLOODING": "p_severe",
    "UNUSABLE": "p_unusable",
}


def _class_from_depth(depth_m: float, bins: dict) -> str:
    for cls in _CLASS_ORDER:
        lo, hi = bins.get(cls, (None, None))
        if hi is None or depth_m < hi:
            return cls
    return _CLASS_ORDER[-1]


def build_synth_obs(
    registry_path: Path = REGISTRY_PATH, depth_nc: Path = DEPTH_NC, out_path: Path = OUT_PATH
) -> pd.DataFrame:
    if not Path(registry_path).exists():
        raise FileNotFoundError(f"{registry_path} not found; run T11's build_registry first")
    if not Path(depth_nc).exists():
        raise FileNotFoundError(f"{depth_nc} not found; run `make fixtures` first")

    fc = json.loads(Path(registry_path).read_text())
    ds = xr.open_dataset(depth_nc)
    tf = Transformer.from_crs(4326, ds.attrs.get("crs", "EPSG:32647"), always_xy=True)
    xs, ys = ds["x"].values, ds["y"].values
    bins = _depth_proxy_bins()

    rows = []
    for feat in fc.get("features", []):
        props = feat["properties"]
        cam_id = props["cam_id"]
        x, y = tf.transform(props["lon"], props["lat"])
        col = int(np.argmin(np.abs(xs - x)))
        row_idx = int(np.argmin(np.abs(ys - y)))

        for t in range(ds.sizes["time"]):
            depth_m = float(ds["depth_m"].isel(time=t, y=row_idx, x=col).values)
            cls = _class_from_depth(depth_m, bins)
            ts = pd.Timestamp(ds["time"].values[t]).strftime("%Y-%m-%dT%H:%M:%SZ")
            probs = {c: 0.0 for c in PROB_COLS}
            probs[_PROB_COL_FOR_CLASS[cls]] = 1.0
            rows.append(
                {
                    "cam_id": cam_id,
                    "ts_utc": ts,
                    "class": cls,
                    **probs,
                    "class_smoothed": cls,
                    "depth_proxy_bin": _depth_proxy_bin_for_class(cls, bins),
                    # The fixture's own simulated depth at this cell is already
                    # exact ground truth here (that's what `cls` was derived
                    # from above) -- unlike the real CCTV path, which only
                    # ever has a CLIP-probability/pixel-based *estimate*.
                    "depth_proxy_m": round(depth_m, 3),
                    # No real image/pixels exist for this synthetic path
                    # (driven purely by the fixture depth grid, not a frame
                    # file) -- never invented, per rule 8.
                    "water_pixel_pct": None,
                    "is_submerged": None,
                    "quality_flag": "OK",
                    "frame_sha1": None,
                    "model_version": "synth-from-depth-v0",
                    "data_class": "SYNTHETIC",
                    "is_mock": True,
                }
            )
    ds.close()

    out = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    return out


def main() -> None:
    df = build_synth_obs()
    print(f"wrote {len(df)} rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
