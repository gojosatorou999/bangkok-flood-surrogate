"""Camera -> model-grid-cell mapping (L3 helper, shared with Rishanth R4.2).

See docs/VARUN_IMPLEMENTATION.md §6 T54. For each camera: a 30 m buffer
around its point, intersected with OSM roads buffered 10 m when road data
exists (data/raw/osm/roads.geojson, from Dhanya); otherwise the 30 m
buffer alone, flagged road_clip=false. Cells = grid cells whose centres
fall inside, computed at both the hydraulic (20 m) and surrogate (40 m)
resolutions.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import unary_union

REGISTRY_PATH = Path("cctv/registry/cameras.geojson")
DOMAIN_CANDIDATES = (Path("configs/domain.yaml"), Path("tools/fixtures/out/domain.yaml"))
OSM_ROADS_CANDIDATES = (Path("data/raw/osm/roads.geojson"),)
OUT_PATH = Path("validation/cctv/cam_cells.parquet")

CAM_BUFFER_M = 30.0
ROAD_BUFFER_M = 10.0
GRID_RESOLUTIONS = (20, 40)  # hydraulic (native) and surrogate (block-averaged x2)


def _load_domain() -> dict:
    for p in DOMAIN_CANDIDATES:
        if p.exists():
            return yaml.safe_load(p.read_text())
    raise FileNotFoundError("no domain.yaml found (real or fixture); run `make fixtures` first")


def _load_roads():
    for p in OSM_ROADS_CANDIDATES:
        if p.exists():
            fc = json.loads(p.read_text())
            geoms = [shape(f["geometry"]) for f in fc.get("features", [])]
            if geoms:
                return unary_union(geoms)
    return None  # [DATA GAP] no OSM roads from Dhanya yet -> road_clip stays false everywhere


def _grid_centers(domain: dict, grid_res_m: int) -> tuple[np.ndarray, np.ndarray]:
    """Cell-centre coordinate arrays (xs, ys) at grid_res_m, aligned to the
    native grid the same way T40's surrogate block-average is (pairwise mean
    of adjacent native cell centres), not a fresh origin-based grid."""
    ox, oy = domain["origin_x"], domain["origin_y"]
    ny, nx = domain["shape"]
    native_res = domain["res_m"]
    xs0 = ox + (np.arange(nx) + 0.5) * native_res
    ys0 = oy + (np.arange(ny) + 0.5) * native_res
    if grid_res_m == native_res:
        return xs0, ys0
    if grid_res_m % native_res != 0:
        raise ValueError(f"grid_res_m={grid_res_m} isn't a multiple of the native {native_res} m grid")
    factor = grid_res_m // native_res
    xs = xs0[: (nx // factor) * factor].reshape(-1, factor).mean(axis=1)
    ys = ys0[: (ny // factor) * factor].reshape(-1, factor).mean(axis=1)
    return xs, ys


def _camera_footprint(x: float, y: float, roads):
    buf = Point(x, y).buffer(CAM_BUFFER_M)
    if roads is None:
        return buf, False
    road_buf = roads.buffer(ROAD_BUFFER_M)
    clipped = buf.intersection(road_buf)
    if clipped.is_empty:
        return buf, False  # road data exists but doesn't reach here -> fall back to the plain buffer
    return clipped, True


def build_cam_cells(
    registry_path: Path = REGISTRY_PATH,
    out_path: Path = OUT_PATH,
    grid_resolutions: tuple[int, ...] = GRID_RESOLUTIONS,
) -> pd.DataFrame:
    if not Path(registry_path).exists():
        raise FileNotFoundError(f"{registry_path} not found; run T11's build_registry first")

    fc = json.loads(Path(registry_path).read_text())
    domain = _load_domain()
    roads = _load_roads()
    tf = Transformer.from_crs(4326, domain.get("crs", "EPSG:32647"), always_xy=True)
    grids = {res: _grid_centers(domain, res) for res in grid_resolutions}

    rows = []
    for feat in fc.get("features", []):
        props = feat["properties"]
        cam_id = props["cam_id"]
        x, y = tf.transform(props["lon"], props["lat"])
        footprint, road_clip = _camera_footprint(x, y, roads)
        minx, miny, maxx, maxy = footprint.bounds

        for res in grid_resolutions:
            xs, ys = grids[res]
            col_idx = np.where((xs >= minx - res) & (xs <= maxx + res))[0]
            row_idx = np.where((ys >= miny - res) & (ys <= maxy + res))[0]
            for r in row_idx:
                for c in col_idx:
                    if footprint.contains(Point(xs[c], ys[r])):
                        rows.append(
                            {"cam_id": cam_id, "row": int(r), "col": int(c), "grid_res_m": res, "road_clip": road_clip}
                        )

    out = pd.DataFrame(rows, columns=["cam_id", "row", "col", "grid_res_m", "road_clip"])
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    return out


def main() -> None:
    df = build_cam_cells()
    print(f"wrote {len(df)} cam-cell rows -> {OUT_PATH} (road_clip available: {bool(_load_roads())})")


if __name__ == "__main__":
    main()
