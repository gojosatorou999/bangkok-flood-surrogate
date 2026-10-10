"""CCTV labelling app (HU5). See docs/VARUN_IMPLEMENTATION.md §6 T51.

FastAPI on port 8010 (`make label`). Serves frames from the blurred
archive only: data/cctv/raw -- despite the folder's name, the archiver
(T20) downscales + face/plate-blurs every frame *before* it is ever
written to disk (Agent rule 6), so nothing truly raw is ever served.

Sampling (`GET /api/next`): stratified by zero-shot argmax so rare
classes surface more often, with an oversampling boost for frames taken
during an hour when a rain gauge within 2 km recorded a high rate
([ASSUMPTION] stations.timeseries values are per-15-min totals here;
rate is approximated as value * 4 -- see docs/assumptions.md). Already
labelled sha1 are skipped *per labeller*, not globally, so a second
labeller can still double-label frames the first one already did.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

FRAMES_PARQUET = Path("data/cctv/cctv_frames.parquet")
ZEROSHOT_CACHE = Path("cctv/classifier/cache/zeroshot_v0.parquet")
LABELS_CSV = Path("cctv/labelling/labels.csv")
ROI_OVERRIDES = Path("cctv/registry/roi_overrides.json")
REGISTRY_PATH = Path("cctv/registry/cameras.geojson")
BLURRED_FRAMES_DIR = Path("data/cctv/raw")
STATIC_DIR = Path(__file__).parent / "static"

STATIONS_CANDIDATES = (Path("data/interim/stations/stations.parquet"), Path("tools/fixtures/out/stations/stations.parquet"))
TIMESERIES_CANDIDATES = (
    Path("data/interim/stations/timeseries.parquet"),
    Path("tools/fixtures/out/stations/timeseries.parquet"),
)

KEY_TO_LABEL = {
    "1": "NORMAL",
    "2": "WATERLOGGING",
    "3": "FLOODING",
    "4": "SEVERE_FLOODING",
    "0": "UNUSABLE",
    "o": "OCCLUDED",
}
VALID_LABELS = set(KEY_TO_LABEL.values())
LABELS_COLUMNS = ["cam_id", "ts_utc", "sha1", "label", "labeller", "labelled_utc"]

app = FastAPI(title="CCTV Labelling")
if BLURRED_FRAMES_DIR.exists():
    app.mount("/label_frames", StaticFiles(directory=str(BLURRED_FRAMES_DIR)), name="label_frames")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class LabelIn(BaseModel):
    cam_id: str
    ts_utc: str
    sha1: str
    label: str
    labeller: str


class UndoIn(BaseModel):
    labeller: str


class RoiIn(BaseModel):
    cam_id: str
    points: list[list[float]]


def _first_existing(paths) -> Path | None:
    for p in paths:
        if p.exists():
            return p
    return None


def _load_labels() -> pd.DataFrame:
    if not LABELS_CSV.exists():
        return pd.DataFrame(columns=LABELS_COLUMNS)
    return pd.read_csv(LABELS_CSV, dtype=str)


def _save_labels(df: pd.DataFrame) -> None:
    LABELS_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(LABELS_CSV, index=False)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nearby_high_rain_hours(cam_lon: float, cam_lat: float, radius_km: float = 2.0, rate_mm_h: float = 10.0) -> set[str]:
    stations_path = _first_existing(STATIONS_CANDIDATES)
    ts_path = _first_existing(TIMESERIES_CANDIDATES)
    if stations_path is None or ts_path is None:
        return set()
    stations = pd.read_parquet(stations_path)
    rain = stations[stations["type"] == "rain"]
    nearby_ids = {
        row["station_id"]
        for _, row in rain.iterrows()
        if _haversine_km(cam_lat, cam_lon, row["lat"], row["lon"]) <= radius_km
    }
    if not nearby_ids:
        return set()
    ts = pd.read_parquet(ts_path)
    ts = ts[ts["station_id"].isin(nearby_ids)]
    ts = ts[(ts["value"] * 4.0) >= rate_mm_h]  # [ASSUMPTION] 15-min total -> hourly-rate approximation
    return set(pd.to_datetime(ts["ts_utc"]).dt.strftime("%Y-%m-%dT%H:00:00Z"))


def _camera_lonlat() -> dict[str, tuple[float, float]]:
    if not REGISTRY_PATH.exists():
        return {}
    fc = json.loads(REGISTRY_PATH.read_text())
    return {f["properties"]["cam_id"]: (f["properties"]["lon"], f["properties"]["lat"]) for f in fc.get("features", [])}


def _candidate_pool(labeller: str) -> pd.DataFrame:
    if not FRAMES_PARQUET.exists():
        return pd.DataFrame()
    frames = pd.read_parquet(FRAMES_PARQUET)
    frames = frames[frames["quality_flag"] == "OK"].copy()
    if frames.empty:
        return frames

    done_sha1 = set(_load_labels().query("labeller == @labeller")["sha1"])
    frames = frames[~frames["sha1"].isin(done_sha1)]
    if frames.empty:
        return frames

    zs = pd.read_parquet(ZEROSHOT_CACHE) if ZEROSHOT_CACHE.exists() else pd.DataFrame(columns=["sha1", "argmax_class"])
    frames = frames.merge(zs[["sha1", "argmax_class"]], on="sha1", how="left")
    frames["argmax_class"] = frames["argmax_class"].fillna("UNKNOWN")
    class_counts = frames["argmax_class"].value_counts().to_dict()

    cam_lonlat = _camera_lonlat()
    rain_hours_by_cam: dict[str, set[str]] = {}
    weights = []
    for _, row in frames.iterrows():
        weight = 1.0 / class_counts.get(row["argmax_class"], 1)
        lon_lat = cam_lonlat.get(row["cam_id"])
        if lon_lat is not None:
            if row["cam_id"] not in rain_hours_by_cam:
                rain_hours_by_cam[row["cam_id"]] = _nearby_high_rain_hours(*lon_lat)
            hour_key = pd.Timestamp(row["ts_utc"]).strftime("%Y-%m-%dT%H:00:00Z")
            if hour_key in rain_hours_by_cam[row["cam_id"]]:
                weight *= 3.0
        weights.append(weight)
    frames["_weight"] = weights
    return frames


def _progress(labeller: str | None = None) -> dict:
    labels = _load_labels()
    if labeller:
        labels = labels[labels["labeller"] == labeller]
    return dict(Counter(labels["label"]))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/next")
def next_frame(labeller: str):
    pool = _candidate_pool(labeller)
    if pool.empty:
        raise HTTPException(404, "no more frames to label")
    row = pool.sample(1, weights=pool["_weight"]).iloc[0]
    yyyymmdd = pd.Timestamp(row["ts_utc"]).strftime("%Y%m%d")
    frame_url = f"/label_frames/{row['cam_id']}/{yyyymmdd}/{Path(row['path']).name}"
    return {
        "cam_id": row["cam_id"],
        "ts_utc": row["ts_utc"],
        "sha1": row["sha1"],
        "frame_url": frame_url,
        "zeroshot_class": row.get("argmax_class"),
    }


@app.post("/api/label")
def post_label(body: LabelIn):
    if body.label not in VALID_LABELS:
        raise HTTPException(422, f"invalid label {body.label!r}; expected one of {sorted(VALID_LABELS)}")
    labels = _load_labels()
    # last write wins per (sha1, labeller): drop any prior entry, then append
    labels = labels[~((labels["sha1"] == body.sha1) & (labels["labeller"] == body.labeller))]
    new_row = {
        "cam_id": body.cam_id,
        "ts_utc": body.ts_utc,
        "sha1": body.sha1,
        "label": body.label,
        "labeller": body.labeller,
        "labelled_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    labels = pd.concat([labels, pd.DataFrame([new_row])], ignore_index=True)
    _save_labels(labels)
    return {"status": "ok", "progress": _progress(body.labeller)}


@app.post("/api/undo")
def undo(body: UndoIn):
    # Most recent = last matching row in file order, not max(labelled_utc):
    # that timestamp only has 1-second resolution, so two labels landing in
    # the same second would tie and idxmax() would (wrongly) pick the first.
    labels = _load_labels()
    mine_idx = labels.index[labels["labeller"] == body.labeller]
    if len(mine_idx) == 0:
        raise HTTPException(404, "nothing to undo")
    last_idx = mine_idx[-1]
    removed = labels.loc[last_idx].to_dict()
    labels = labels.drop(index=last_idx)
    _save_labels(labels)
    return {"status": "ok", "removed": removed}


@app.get("/api/progress")
def progress(labeller: str | None = None):
    return _progress(labeller)


@app.post("/api/roi")
def post_roi(body: RoiIn):
    overrides = json.loads(ROI_OVERRIDES.read_text()) if ROI_OVERRIDES.exists() else {}
    overrides[body.cam_id] = body.points
    ROI_OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    ROI_OVERRIDES.write_text(json.dumps(overrides, indent=1))
    return {"status": "ok", "cam_id": body.cam_id, "n_points": len(body.points)}
