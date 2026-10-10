"""Manual CCTV ingest -- the NO_GO fallback. See cctv/manual/README.md and
docs/VARUN_IMPLEMENTATION.md §6 T20.

For a source whose legal decision is NO_GO: a human saves <=20 frames by
hand (browser screenshot, phone photo, whatever), and this runs them
through the exact same privacy + quality pipeline the live archiver uses
(`archiver.process_and_save`), so downstream consumers (classifier,
dashboard) can't tell the difference. Never fetches anything itself --
no legal gate check needed here, since nothing in this file makes an
automated request to the source.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .archiver import CONFIG_PATH, META_ROOT, RAW_ROOT, THUMBS_ROOT, append_meta, load_config, process_and_save

MAX_MANUAL_FRAMES = 20

_phash_history: dict[str, list[str]] = defaultdict(list)


def ingest_one(
    path: Path,
    cam_id: str,
    cfg: dict,
    *,
    phash_history: dict[str, list[str]] | None = None,
    raw_root: Path = RAW_ROOT,
    thumbs_root: Path = THUMBS_ROOT,
    meta_root: Path = META_ROOT,
) -> dict:
    phash_history = _phash_history if phash_history is None else phash_history
    ts = datetime.now(timezone.utc)
    meta: dict = {
        "cam_id": cam_id,
        "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "http_status": None,
        "source_file": str(path),
    }

    try:
        img = Image.open(path)
        img.load()
        img = img.convert("RGB")
    except Exception as exc:
        meta.update(quality_flag="EXCEPTION", error=f"decode failed: {exc}"[:200])
        append_meta(meta, meta_root)
        return meta

    meta.update(
        process_and_save(img, cam_id, ts, cfg, phash_history=phash_history, raw_root=raw_root, thumbs_root=thumbs_root)
    )
    append_meta(meta, meta_root)
    return meta


def ingest_dir(dir_path: Path, cam_id: str | None = None, config_path: Path = CONFIG_PATH) -> list[dict]:
    """cam_id defaults to the directory's own name when not given."""
    cfg = load_config(config_path)
    cam_id = cam_id or dir_path.name
    images = sorted(p for p in dir_path.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if len(images) > MAX_MANUAL_FRAMES:
        print(f"note: {len(images)} images found; only the first {MAX_MANUAL_FRAMES} will be ingested")
        images = images[:MAX_MANUAL_FRAMES]
    return [ingest_one(p, cam_id, cfg) for p in images]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory of manually-saved images (<=20 used)")
    parser.add_argument("--cam-id", default=None, help="defaults to the directory name")
    args = parser.parse_args()

    results = ingest_dir(args.directory, args.cam_id)
    print(f"ingested {len(results)} frame(s) from {args.directory}")


if __name__ == "__main__":
    main()
