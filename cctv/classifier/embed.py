"""Embeds every quality_flag==OK CCTV frame not yet in the cache.

See docs/VARUN_IMPLEMENTATION.md §6 T50. Resumable: only frames whose sha1
isn't already in the cache get re-embedded. Frames with quality_flag !=
OK are never embedded (they become UNUSABLE downstream, per T53).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from PIL import Image

from .clip_model import embed_and_zeroshot

FRAMES_PARQUET = Path("data/cctv/cctv_frames.parquet")
CACHE_PATH = Path("cctv/classifier/cache/embeddings_ViT-B-32.parquet")
REGISTRY_PATH = Path("cctv/registry/cameras.geojson")
BATCH_SIZE = 32


def _load_roi_by_cam(registry_path: Path = REGISTRY_PATH) -> dict[str, list]:
    if not registry_path.exists():
        return {}
    fc = json.loads(registry_path.read_text())
    return {
        f["properties"]["cam_id"]: f["properties"]["road_roi_px"]
        for f in fc.get("features", [])
        if f["properties"].get("road_roi_px")
    }


def _crop_to_roi(img: Image.Image, roi_px) -> Image.Image:
    """roi_px: a polygon [[x, y], ...] in pixel space (T51) -> crop to its
    bounding box. Returns the full frame when roi_px is falsy."""
    if not roi_px:
        return img
    xs = [p[0] for p in roi_px]
    ys = [p[1] for p in roi_px]
    box = (max(0, min(xs)), max(0, min(ys)), min(img.width, max(xs)), min(img.height, max(ys)))
    if box[2] <= box[0] or box[3] <= box[1]:
        return img
    return img.crop(box)


def _already_cached(cache_path: Path) -> set[str]:
    if not cache_path.exists():
        return set()
    return set(pd.read_parquet(cache_path, columns=["sha1"])["sha1"])


def embed_new_frames(
    frames_parquet: Path = FRAMES_PARQUET,
    cache_path: Path = CACHE_PATH,
    registry_path: Path = REGISTRY_PATH,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Returns the number of newly embedded frames."""
    if not frames_parquet.exists():
        return 0
    frames = pd.read_parquet(frames_parquet)
    frames = frames[frames["quality_flag"] == "OK"]
    cached = _already_cached(cache_path)
    frames = frames[~frames["sha1"].isin(cached)].drop_duplicates(subset="sha1")
    if frames.empty:
        return 0

    roi_by_cam = _load_roi_by_cam(registry_path)

    new_rows = []
    records = frames.to_dict("records")
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        imgs = [_crop_to_roi(Image.open(row["path"]).convert("RGB"), roi_by_cam.get(row["cam_id"])) for row in batch]
        emb, _ = embed_and_zeroshot(imgs)
        for row, vec in zip(batch, emb):
            new_rows.append(
                {
                    "cam_id": row["cam_id"],
                    "ts_utc": row["ts_utc"],
                    "sha1": row["sha1"],
                    "emb": vec.astype("float32").tolist(),
                }
            )

    new_df = pd.DataFrame(new_rows)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        out = pd.concat([pd.read_parquet(cache_path), new_df], ignore_index=True)
    else:
        out = new_df
    out.to_parquet(cache_path, index=False)
    return len(new_rows)


def main() -> None:
    n = embed_new_frames()
    print(f"embedded {n} new frame(s); cache at {CACHE_PATH}")


if __name__ == "__main__":
    main()
