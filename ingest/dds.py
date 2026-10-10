"""Offline parser for DDS road-flood/gauge snapshots. See docs/VARUN_IMPLEMENTATION.md §6 T21.

Never touches the network -- reads bytes already saved by
cctv/archiver/dds_snapshot.py (or, for tests, a sample fixture) and turns
them into the interim parquet contracts Dhanya (D3.4) and the dashboard
read. Idempotent: safe to run repeatedly over an always-growing snapshot
directory.

The real DDS payload shape is unknown (HU4 -- no sample has been provided
yet), so parse_road_flood_payload/parse_stations_payload are written
against tests/varun/fixtures/dds_sample_*.json, a plausible guess at the
structure. Every `# TODO(HU4)` marks a spot that will need adapting once
a real payload lands.

Rain totals from DDS/TMD-style gauges are conventionally a 07:00-07:00 ICT
"day" (not midnight-to-midnight) -- noted here for whoever aggregates
timeseries.parquet into daily figures downstream; this module only writes
the raw per-reading rows, it does not aggregate.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

RAW_ROOT = Path("data/raw/obs/dds")
ENDPOINTS_PATH = Path("secrets/dds_endpoints.yaml")
OUT_ROAD_FLOOD = Path("data/interim/obs/dds_road_flood.parquet")
OUT_STATIONS = Path("data/interim/stations/stations.parquet")
OUT_TIMESERIES = Path("data/interim/stations/timeseries.parquet")

ICT = ZoneInfo("Asia/Bangkok")

ROAD_FLOOD_COLUMNS = [
    "point_id",
    "road_name",
    "district",
    "ts_utc",
    "depth_cm",
    "lane",
    "lon",
    "lat",
    "source_ref",
    "data_class",
    "location_method",
    "loc_accuracy_m",
]
STATIONS_COLUMNS = ["station_id", "type", "name", "lon", "lat", "source"]
TIMESERIES_COLUMNS = ["station_id", "ts_utc", "value", "unit", "data_class"]


def _to_utc_iso(local_time_str: str) -> str:
    """DDS timestamps are assumed local ICT with no offset marker (no real
    sample to confirm -- TODO(HU4): verify once a payload lands; adjust if
    DDS actually publishes UTC or a different format)."""
    dt_local = datetime.strptime(local_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ICT)
    return dt_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_road_flood_payload(raw: bytes, source_name: str = "dds_road_flood") -> pd.DataFrame:
    """TODO(HU4): written against dds_sample_road_flood.json's {"points": [...]}
    shape; adapt field names once a real DDS floodbangkok payload is saved."""
    data = json.loads(raw)
    rows = []
    for p in data.get("points", []):
        has_coords = p.get("lon") is not None and p.get("lat") is not None
        rows.append(
            {
                "point_id": p["id"],
                "road_name": p.get("road"),
                "district": p.get("district"),
                "ts_utc": _to_utc_iso(p["time"]),
                "depth_cm": p.get("depth_cm"),
                "lane": p.get("lane"),
                "lon": p.get("lon"),  # null + [DATA GAP] downstream when missing, never guessed
                "lat": p.get("lat"),
                "source_ref": source_name,
                "data_class": "OBSERVED",
                "location_method": "DDS_PROVIDED" if has_coords else None,
                "loc_accuracy_m": None,  # [DATA GAP] DDS doesn't publish accuracy
            }
        )
    return pd.DataFrame(rows, columns=ROAD_FLOOD_COLUMNS)


def parse_stations_payload(raw: bytes, source_name: str = "dds") -> tuple[pd.DataFrame, pd.DataFrame]:
    """TODO(HU4): written against dds_sample_stations.json's {"stations": [...]}
    shape; adapt field names once a real DDS SCADA payload is saved."""
    data = json.loads(raw)
    station_rows, ts_rows = [], []
    for s in data.get("stations", []):
        station_rows.append(
            {
                "station_id": s["code"],
                "type": s["type"],
                "name": s.get("name"),
                "lon": s.get("lon"),  # null + [DATA GAP] downstream when missing, never guessed
                "lat": s.get("lat"),
                "source": source_name,
            }
        )
        unit = "mm" if s["type"] == "rain" else "m"
        value_key = "value_mm" if s["type"] == "rain" else "value_m"
        for r in s.get("readings", []):
            ts_rows.append(
                {
                    "station_id": s["code"],
                    "ts_utc": _to_utc_iso(r["time"]),
                    "value": r.get(value_key),
                    "unit": unit,
                    "data_class": "OBSERVED",
                }
            )
    return (
        pd.DataFrame(station_rows, columns=STATIONS_COLUMNS),
        pd.DataFrame(ts_rows, columns=TIMESERIES_COLUMNS),
    )


def _load_endpoint_kinds(endpoints_path: Path) -> dict[str, str]:
    if not endpoints_path.exists():
        return {}
    data = yaml.safe_load(endpoints_path.read_text()) or {}
    return {e["name"]: e["kind"] for e in data.get("endpoints", [])}


def _iter_snapshot_rows(raw_root: Path):
    for index_path in sorted(raw_root.glob("*/_index.jsonl")):
        for line in index_path.read_text().splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)


def _dedupe_write(df: pd.DataFrame, out_path: Path, key_cols: list[str]) -> pd.DataFrame:
    if out_path.exists():
        existing = pd.read_parquet(out_path)
        df = pd.concat([existing, df], ignore_index=True) if not df.empty else existing
    if df.empty:
        return df
    df = df.drop_duplicates(subset=key_cols, keep="last").sort_values(key_cols).reset_index(drop=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return df


def run(
    raw_root: Path = RAW_ROOT,
    endpoints_path: Path = ENDPOINTS_PATH,
    out_road_flood: Path = OUT_ROAD_FLOOD,
    out_stations: Path = OUT_STATIONS,
    out_timeseries: Path = OUT_TIMESERIES,
) -> dict:
    """Idempotent: re-running over the same (growing) snapshot dir never
    duplicates a row, since every output is deduped on its natural key
    before being written."""
    kinds = _load_endpoint_kinds(endpoints_path)

    road_flood_frames, station_frames, ts_frames = [], [], []
    for row in _iter_snapshot_rows(raw_root):
        if row.get("status") != 200 or "path" not in row:
            continue
        kind = kinds.get(row["name"])
        path = Path(row["path"])
        if not path.exists():
            continue
        raw = path.read_bytes()

        if kind == "road_flood":
            road_flood_frames.append(parse_road_flood_payload(raw, source_name=row["name"]))
        elif kind in ("rain", "canal"):
            stations_df, ts_df = parse_stations_payload(raw, source_name=row["name"])
            station_frames.append(stations_df)
            ts_frames.append(ts_df)

    road_flood_df = pd.concat(road_flood_frames, ignore_index=True) if road_flood_frames else pd.DataFrame(
        columns=ROAD_FLOOD_COLUMNS
    )
    stations_df = pd.concat(station_frames, ignore_index=True) if station_frames else pd.DataFrame(
        columns=STATIONS_COLUMNS
    )
    timeseries_df = pd.concat(ts_frames, ignore_index=True) if ts_frames else pd.DataFrame(columns=TIMESERIES_COLUMNS)

    road_flood_out = _dedupe_write(road_flood_df, out_road_flood, ["point_id", "ts_utc"])
    stations_out = _dedupe_write(stations_df, out_stations, ["station_id"])
    timeseries_out = _dedupe_write(timeseries_df, out_timeseries, ["station_id", "ts_utc"])

    return {
        "road_flood_rows": len(road_flood_out),
        "stations_rows": len(stations_out),
        "timeseries_rows": len(timeseries_out),
    }


def main() -> None:
    result = run()
    print(f"dds_road_flood: {result['road_flood_rows']} rows")
    print(f"stations: {result['stations_rows']} rows")
    print(f"timeseries: {result['timeseries_rows']} rows")


if __name__ == "__main__":
    main()
