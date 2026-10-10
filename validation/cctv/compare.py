"""Shared CCTV <-> model-depth comparison helpers (L3).

See docs/VARUN_IMPLEMENTATION.md §6 T54. Rishanth owns the final L3
report; these two functions are the shared building blocks:
`model_series` turns a depth NetCDF + cam_cells into a per-camera time
series, `confusion` joins that against `cctv_obs.parquet` classifications.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml
from sklearn.metrics import cohen_kappa_score, confusion_matrix

THRESHOLDS_PATH = Path("configs/thresholds.yaml")

# Same 4-class taxonomy as cctv_depth_proxy_bins_m (UNUSABLE has no depth analogue).
_CLASS_ORDER = ["NORMAL", "WATERLOGGING", "FLOODING", "SEVERE_FLOODING"]


def _load_thresholds() -> dict:
    if not THRESHOLDS_PATH.exists():
        return {}
    return yaml.safe_load(THRESHOLDS_PATH.read_text()) or {}


def _depth_bins_m(thresholds: dict) -> list[float]:
    return thresholds.get("depth_bins_m", [0.05, 0.15, 0.30, 0.50, 1.0])


def _bin_label(depth_m: float, bins: list[float]) -> str:
    edges = [0.0, *bins, float("inf")]
    for lo, hi in zip(edges[:-1], edges[1:]):
        if lo <= depth_m < hi:
            return f"{lo:.2f}-{hi:.2f}" if hi != float("inf") else f"{lo:.2f}-"
    return f"{edges[-2]:.2f}-"


def _class_from_depth(depth_m: float, proxy_bins: dict) -> str:
    for cls in _CLASS_ORDER:
        lo, hi = proxy_bins.get(cls, (None, None))
        if hi is None or depth_m < hi:
            return cls
    return _CLASS_ORDER[-1]


def model_series(depth_nc, cam_cells: pd.DataFrame, grid_res_m: int | None = None) -> pd.DataFrame:
    """Per-camera, per-timestep MAX depth over its mapped cells.

    Returns DataFrame(cam_id, ts_utc, depth_max_m, bin).
    """
    ds = xr.open_dataset(depth_nc)
    try:
        if grid_res_m is None:
            res_values = cam_cells["grid_res_m"].unique()
            if len(res_values) != 1:
                raise ValueError("cam_cells has more than one grid_res_m; pass grid_res_m explicitly")
            grid_res_m = int(res_values[0])

        cells = cam_cells[cam_cells["grid_res_m"] == grid_res_m]
        bins = _depth_bins_m(_load_thresholds())
        times = ds["time"].values
        depth = ds["depth_m"].values  # (time, y, x)

        rows = []
        for cam_id, group in cells.groupby("cam_id"):
            rr, cc = group["row"].to_numpy(), group["col"].to_numpy()
            for t_idx, t in enumerate(times):
                depth_max = float(depth[t_idx, rr, cc].max()) if len(rr) else float("nan")
                rows.append(
                    {
                        "cam_id": cam_id,
                        "ts_utc": pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "depth_max_m": depth_max,
                        "bin": _bin_label(depth_max, bins) if not np.isnan(depth_max) else None,
                    }
                )
        return pd.DataFrame(rows)
    finally:
        ds.close()


def confusion(cctv_obs: pd.DataFrame, model_series_df: pd.DataFrame, tol_min: int = 7) -> dict:
    """Nearest-time join (within +/- tol_min) of cctv_obs.class_smoothed
    against model depth binned onto the same 4-class taxonomy.

    Returns {confusion_matrix, labels, kappa, onset_error_min (per camera,
    cctv-minus-model in minutes; None where either side never reaches
    onset), n_pairs}.
    """
    thresholds = _load_thresholds()
    proxy_bins = thresholds.get("cctv_depth_proxy_bins_m", {})
    onset_class = thresholds.get("cctv_onset_class", "FLOODING")
    onset_depth_m = (proxy_bins.get(onset_class) or [0.15, None])[0]

    cctv = cctv_obs.copy()
    model = model_series_df.copy()
    cctv["ts_utc"] = pd.to_datetime(cctv["ts_utc"])
    model["ts_utc"] = pd.to_datetime(model["ts_utc"])

    pairs = []
    for cam_id, cctv_group in cctv.groupby("cam_id"):
        model_group = model[model["cam_id"] == cam_id].sort_values("ts_utc")
        if model_group.empty:
            continue
        merged = pd.merge_asof(
            cctv_group.sort_values("ts_utc"),
            model_group[["ts_utc", "depth_max_m"]],
            on="ts_utc",
            direction="nearest",
            tolerance=pd.Timedelta(minutes=tol_min),
        ).dropna(subset=["depth_max_m"])
        merged["cam_id"] = cam_id
        pairs.append(merged)

    if not pairs:
        return {"confusion_matrix": None, "labels": _CLASS_ORDER, "kappa": None, "onset_error_min": {}, "n_pairs": 0}

    joined = pd.concat(pairs, ignore_index=True)
    joined = joined[joined["class_smoothed"] != "UNUSABLE"]
    if joined.empty:
        return {"confusion_matrix": None, "labels": _CLASS_ORDER, "kappa": None, "onset_error_min": {}, "n_pairs": 0}

    joined["model_class"] = joined["depth_max_m"].apply(lambda d: _class_from_depth(d, proxy_bins))

    cm = confusion_matrix(joined["class_smoothed"], joined["model_class"], labels=_CLASS_ORDER)
    if (joined["class_smoothed"] == joined["model_class"]).all():
        kappa = 1.0  # sklearn returns NaN for a constant-but-identical series; perfect agreement is still kappa=1
    else:
        kappa = float(cohen_kappa_score(joined["class_smoothed"], joined["model_class"]))

    onset_error: dict[str, float | None] = {}
    for cam_id in joined["cam_id"].unique():
        cam_cctv_onset = cctv[(cctv["cam_id"] == cam_id) & (cctv["class_smoothed"] == onset_class)]
        cam_model = model[model["cam_id"] == cam_id].sort_values("ts_utc")
        cam_model_onset = cam_model[cam_model["depth_max_m"] >= onset_depth_m]
        if cam_cctv_onset.empty or cam_model_onset.empty:
            onset_error[cam_id] = None
        else:
            delta = cam_cctv_onset["ts_utc"].min() - cam_model_onset["ts_utc"].min()
            onset_error[cam_id] = delta.total_seconds() / 60.0

    return {
        "confusion_matrix": cm.tolist(),
        "labels": _CLASS_ORDER,
        "kappa": kappa,
        "onset_error_min": onset_error,
        "n_pairs": len(joined),
    }
