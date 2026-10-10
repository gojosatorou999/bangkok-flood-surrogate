"""Camera registry builder. See docs/VARUN_IMPLEMENTATION.md §6 T11.

Builds `cctv/registry/cameras.geojson` from a human-provided CSV
(`cctv/registry/cameras_input.csv`, HU2). Falls back to the T01 fixture
camera set (marked `is_mock: true`) when that CSV doesn't exist yet, so
nothing downstream blocks waiting on it.

Never includes snapshot URLs — those live in `secrets/cctv_urls.json`.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from shapely.geometry import Point, shape

DEFAULT_INPUT_CSV = Path("cctv/registry/cameras_input.csv")
DEFAULT_OUTPUT = Path("cctv/registry/cameras.geojson")
DEFAULT_FIXTURE = Path("tools/fixtures/out/cameras.geojson")
DEFAULT_POLYGON_CANDIDATES = (
    Path("configs/analysis_polygon.geojson"),
    Path("tools/fixtures/out/analysis_polygon.geojson"),
)
DDS_HOTSPOTS = Path("data/interim/obs/dds_hotspots.geojson")
DEFAULT_ROI_OVERRIDES = Path("cctv/registry/roi_overrides.json")
DEFAULT_MANUAL_CAMERAS = Path("cctv/registry/manual_cameras.json")

VALID_SOURCES = ("BMAT", "ITIC", "LNGD")
_URL_TOKENS = ("http://", "https://", "www.")


def _load_polygon(polygon_path: Path | None = None):
    candidates = (polygon_path,) if polygon_path else DEFAULT_POLYGON_CANDIDATES
    for p in candidates:
        if p and Path(p).exists():
            fc = json.loads(Path(p).read_text())
            return shape(fc["features"][0]["geometry"])
    return None


def _nearest_dds(lon: float, lat: float, hotspots_path: Path = DDS_HOTSPOTS):
    if not hotspots_path.exists():
        return None, None
    fc = json.loads(hotspots_path.read_text())
    pt = Point(lon, lat)
    best_id, best_dist = None, math.inf
    for feat in fc.get("features", []):
        d = pt.distance(shape(feat["geometry"]))
        if d < best_dist:
            best_dist, best_id = d, feat.get("properties", {}).get("point_id")
    return (best_id, best_dist) if best_id is not None else (None, None)


def _scrub_no_urls(props: dict) -> None:
    for k, v in props.items():
        if isinstance(v, str) and any(tok in v.lower() for tok in _URL_TOKENS):
            raise ValueError(f"refusing to write a URL-like value in property {k!r}: {v!r}")


def _to_float_or_none(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _to_int_or_none(v):
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


def build_from_csv(input_csv: Path, polygon_path: Path | None = None) -> dict:
    polygon = _load_polygon(polygon_path)
    counters: dict[str, int] = {}
    features = []
    with Path(input_csv).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            src = (row.get("source") or "").strip()
            if src not in VALID_SOURCES:
                raise ValueError(f"unknown source {src!r} in {input_csv} (expected one of {VALID_SOURCES})")
            counters[src] = counters.get(src, 0) + 1
            cam_id = f"{src}-{counters[src]:04d}"
            lon, lat = float(row["lon"]), float(row["lat"])
            in_domain = bool(polygon is not None and polygon.contains(Point(lon, lat)))
            nearest_id, dist = _nearest_dds(lon, lat)

            props = {
                "cam_id": cam_id,
                "source": src,
                "source_cam_ref": row.get("source_cam_ref") or None,
                "name_th": row.get("name_th") or None,
                "name_en": row.get("name_en") or None,
                "lon": lon,
                "lat": lat,
                "loc_method": row.get("loc_method") or None,
                "loc_accuracy_m": _to_float_or_none(row.get("loc_accuracy_m")),
                "heading_deg": _to_float_or_none(row.get("heading_deg")),
                "road_name": row.get("road_name") or None,
                "refresh_s": _to_int_or_none(row.get("refresh_s")),
                "calib_refs": row.get("calib_refs") or None,
                "priority": _to_int_or_none(row.get("priority")) or 99,
                "in_domain": in_domain,
                "nearest_dds_point_id": nearest_id,
                "dist_dds_m": dist,
                "road_roi_px": None,
                "status": "ACTIVE",
                "is_mock": False,
            }
            _scrub_no_urls(props)
            features.append(
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}
            )
    return {"type": "FeatureCollection", "metadata": {"is_mock": False}, "features": features}


def _load_manual_cameras(manual_path: Path, polygon_path: Path | None = None) -> list[dict]:
    """Cameras ingested via cctv.archiver.ingest_manual (NO_GO fallback, see
    cctv/manual/README.md) never go through build_from_csv -- they have no
    live snapshot URL or source_cam_ref to derive a position from. This reads
    a small hand-maintained JSON file (one object per manual camera) so they
    survive a `build_registry()` re-run instead of only existing until the
    next regen overwrites DEFAULT_OUTPUT from the CSV/fixture branch.

    Each entry must say its own `is_mock` and `loc_method` explicitly --
    nothing here is invented. A `loc_method` of "ASSUMPTION_PLACEHOLDER"
    (see docs/assumptions.md) means the lon/lat is not a real geocode, just
    a point inside the domain so the camera is clickable on the map; such
    entries should also set `is_mock: true` so the dashboard's MOCK
    watermark warns that the *position* (not necessarily the imagery) isn't
    verified.
    """
    if not manual_path.exists():
        return []
    polygon = _load_polygon(polygon_path)
    entries = json.loads(manual_path.read_text())
    features = []
    for i, row in enumerate(entries, start=1):
        cam_id = row.get("cam_id") or f"MANUAL-{i:04d}"
        lon, lat = float(row["lon"]), float(row["lat"])
        in_domain = bool(polygon is not None and polygon.contains(Point(lon, lat)))
        nearest_id, dist = _nearest_dds(lon, lat)
        props = {
            "cam_id": cam_id,
            "source": "MANUAL",
            "source_cam_ref": row.get("source_cam_ref"),
            "name_th": row.get("name_th"),
            "name_en": row.get("name_en"),
            "lon": lon,
            "lat": lat,
            "loc_method": row["loc_method"],
            "loc_accuracy_m": _to_float_or_none(row.get("loc_accuracy_m")),
            "heading_deg": _to_float_or_none(row.get("heading_deg")),
            "road_name": row.get("road_name"),
            "refresh_s": _to_int_or_none(row.get("refresh_s")),
            "calib_refs": row.get("calib_refs"),
            "priority": _to_int_or_none(row.get("priority")) or 99,
            "in_domain": in_domain,
            "nearest_dds_point_id": nearest_id,
            "dist_dds_m": dist,
            "road_roi_px": None,
            "status": row.get("status", "ACTIVE"),
            "is_mock": bool(row["is_mock"]),
        }
        _scrub_no_urls(props)
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props})
    return features


def _apply_roi_overrides(fc: dict, roi_overrides_path: Path) -> None:
    """Merge cctv/labelling/label_app.py's saved ROI polygons (T51) into road_roi_px."""
    if not roi_overrides_path.exists():
        return
    overrides = json.loads(roi_overrides_path.read_text())
    for feat in fc["features"]:
        cam_id = feat["properties"]["cam_id"]
        if cam_id in overrides:
            feat["properties"]["road_roi_px"] = overrides[cam_id]


def build_registry(
    input_csv: Path = DEFAULT_INPUT_CSV,
    output_path: Path = DEFAULT_OUTPUT,
    fixture_path: Path = DEFAULT_FIXTURE,
    polygon_path: Path | None = None,
    roi_overrides_path: Path = DEFAULT_ROI_OVERRIDES,
    manual_cameras_path: Path = DEFAULT_MANUAL_CAMERAS,
) -> dict:
    input_csv, fixture_path, output_path = Path(input_csv), Path(fixture_path), Path(output_path)

    if input_csv.exists():
        fc = build_from_csv(input_csv, polygon_path)
    else:
        if not fixture_path.exists():
            raise FileNotFoundError(
                f"no cameras_input.csv at {input_csv} and no fixtures at {fixture_path}; run `make fixtures` first"
            )
        fc = json.loads(fixture_path.read_text())
        fc.setdefault("metadata", {})["is_mock"] = True

    fc["features"].extend(_load_manual_cameras(Path(manual_cameras_path), polygon_path))

    _apply_roi_overrides(fc, Path(roi_overrides_path))

    for feat in fc["features"]:
        _scrub_no_urls(feat["properties"])

    cam_ids = [f["properties"]["cam_id"] for f in fc["features"]]
    if len(cam_ids) != len(set(cam_ids)):
        raise ValueError("duplicate cam_id in registry output")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(fc, indent=1))
    return fc


def select_for_archive(fc: dict, n: int = 50) -> list[dict]:
    """In-domain, ACTIVE, auto-fetchable cameras, sorted by priority then
    distance to a DDS hotspot. Excludes `source == "MANUAL"` -- those only
    ever get manually-ingested frames (cctv/manual/README.md's NO_GO
    fallback), never a live snapshot URL, and have no corresponding
    legal_status.yaml entry for check_legal_gate() to clear.
    """
    candidates = [
        f
        for f in fc["features"]
        if f["properties"].get("in_domain")
        and f["properties"].get("status") == "ACTIVE"
        and f["properties"].get("source") != "MANUAL"
    ]

    def _key(f):
        p = f["properties"]
        priority = p.get("priority") if p.get("priority") is not None else 99
        dist = p.get("dist_dds_m")
        return (priority, dist if dist is not None else math.inf)

    candidates.sort(key=_key)
    return candidates[:n]


def main() -> None:
    fc = build_registry()
    selected = select_for_archive(fc)
    print(f"wrote {DEFAULT_OUTPUT} with {len(fc['features'])} cameras; {len(selected)} selectable for archive")


if __name__ == "__main__":
    main()
