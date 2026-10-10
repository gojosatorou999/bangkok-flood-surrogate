"""Merges the archiver's daily jsonl meta logs into cctv_frames.parquet.

See docs/VARUN_IMPLEMENTATION.md §6 T20 / §2.4. Idempotent: re-running
never duplicates a (cam_id, ts_utc) row, so it's safe to run hourly over
an always-growing set of jsonl files.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

META_ROOT = Path("data/cctv/meta")
OUT_PATH = Path("data/cctv/cctv_frames.parquet")

COLUMNS = [
    "cam_id",
    "ts_utc",
    "http_status",
    "path",
    "sha1",
    "phash",
    "width",
    "height",
    "bytes",
    "quality_flag",
    "sat_mean",
    "lap_var",
]


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def compact(meta_root: Path = META_ROOT, out_path: Path = OUT_PATH) -> pd.DataFrame:
    rows: list[dict] = []
    for jsonl_path in sorted(meta_root.glob("cctv_frames_*.jsonl")):
        rows.extend(_read_jsonl(jsonl_path))

    if out_path.exists():
        existing = pd.read_parquet(out_path)
        new_df = pd.DataFrame(rows)
        df = pd.concat([existing, new_df], ignore_index=True) if not new_df.empty else existing
    else:
        df = pd.DataFrame(rows)

    if df.empty:
        df = pd.DataFrame(columns=COLUMNS)
    else:
        df = df.drop_duplicates(subset=["cam_id", "ts_utc"], keep="last").sort_values(["cam_id", "ts_utc"])
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = None
        df = df[COLUMNS]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return df


def main() -> None:
    df = compact()
    print(f"wrote {len(df)} rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
