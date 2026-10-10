"""Per-camera archiver health: last-frame age + 1h error rate. See docs/VARUN_IMPLEMENTATION.md §6 T20.

Reads today's (and yesterday's, to not miss rows just after UTC midnight)
meta jsonl directly -- doesn't wait for the hourly `compact()` so
`make cctv-health` reflects near-real-time status.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .compact import META_ROOT, _read_jsonl

CONFIG_PATH = Path("configs/cctv.yaml")
OUT_PATH = Path("data/cctv/health.json")


def _load_cfg(config_path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(config_path.read_text()) if config_path.exists() else {}


def _recent_rows(meta_root: Path, within: timedelta, *, now: datetime) -> list[dict]:
    rows = []
    for day_offset in (0, 1):  # today + yesterday
        day = (now - timedelta(days=day_offset)).strftime("%Y%m%d")
        path = meta_root / f"cctv_frames_{day}.jsonl"
        if path.exists():
            rows.extend(_read_jsonl(path))

    cutoff = now - within
    out = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts_utc"].replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            continue
        if ts >= cutoff:
            out.append({**r, "_ts": ts})
    return out


def check_health(
    meta_root: Path = META_ROOT,
    config_path: Path = CONFIG_PATH,
    out_path: Path = OUT_PATH,
    *,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    cfg = _load_cfg(config_path)
    health_cfg = cfg.get("health", {})
    offline_after_s = health_cfg.get("offline_after_s", 600)
    max_error_rate = health_cfg.get("max_error_rate_1h", 0.5)

    rows_24h = _recent_rows(meta_root, timedelta(hours=24), now=now)
    rows_1h = _recent_rows(meta_root, timedelta(hours=1), now=now)

    by_cam: dict[str, list[dict]] = {}
    for r in rows_24h:
        by_cam.setdefault(r["cam_id"], []).append(r)
    by_cam_1h: dict[str, list[dict]] = {}
    for r in rows_1h:
        by_cam_1h.setdefault(r["cam_id"], []).append(r)

    cameras = []
    offline_count = 0
    for cam_id, rows in sorted(by_cam.items()):
        last_ts = max(r["_ts"] for r in rows)
        age_s = (now - last_ts).total_seconds()
        is_offline = age_s > offline_after_s
        if is_offline:
            offline_count += 1

        hour_rows = by_cam_1h.get(cam_id, [])
        error_rows = [r for r in hour_rows if r.get("quality_flag") in ("HTTP_ERROR", "EXCEPTION")]
        error_rate = (len(error_rows) / len(hour_rows)) if hour_rows else 0.0

        cameras.append(
            {
                "cam_id": cam_id,
                "last_frame_age_s": round(age_s, 1),
                "offline": is_offline,
                "error_rate_1h": round(error_rate, 3),
                "error_rate_1h_exceeded": error_rate > max_error_rate,
            }
        )

    offline_fraction = (offline_count / len(cameras)) if cameras else 0.0
    result = {
        "checked_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cameras": cameras,
        "n_cameras": len(cameras),
        "n_offline": offline_count,
        "offline_fraction": round(offline_fraction, 3),
        "healthy": offline_fraction <= 0.2,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1))
    return result


def main() -> int:
    result = check_health()
    for cam in result["cameras"]:
        flags = []
        if cam["offline"]:
            flags.append("OFFLINE")
        if cam["error_rate_1h_exceeded"]:
            flags.append("HIGH_ERROR_RATE")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"{cam['cam_id']:20s} age={cam['last_frame_age_s']:>8.0f}s err1h={cam['error_rate_1h']:.0%}{flag_str}")
    print(f"\n{result['n_offline']}/{result['n_cameras']} cameras offline ({result['offline_fraction']:.0%})")
    if not result["healthy"]:
        print("UNHEALTHY: more than 20% of cameras are offline")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
