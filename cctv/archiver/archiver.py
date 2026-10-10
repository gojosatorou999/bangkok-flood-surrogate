"""Unattended, polite, privacy-preserving CCTV frame capture. See docs/VARUN_IMPLEMENTATION.md §6 T20.

Run: `tmux new -d -s cctv 'make cctv-archive'`, then hourly `make cctv-compact`.

Refuses to start unless the legal gate says GO for every selected camera's
source (`cctv/legal_gate.py::require_go` -- never bypassed) and unless
FG_CONTACT_EMAIL is set (used in the User-Agent so a source operator can
reach us). NO_GO fallback: `cctv/manual/README.md`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import httpx
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from PIL import Image

from cctv.legal_gate import require_go
from cctv.registry.build_registry import select_for_archive

from .privacy import blur_sensitive
from .quality import assess

CONFIG_PATH = Path("configs/cctv.yaml")
REGISTRY_PATH = Path("cctv/registry/cameras.geojson")
URLS_PATH = Path("secrets/cctv_urls.json")
RAW_ROOT = Path("data/cctv/raw")
THUMBS_ROOT = Path("data/cctv/thumbs")
META_ROOT = Path("data/cctv/meta")

# source registry value -> cctv/legal_status.yaml key
SOURCE_TO_LEGAL_KEY = {"BMAT": "bmatraffic", "ITIC": "itic", "LNGD": "longdo"}

_phash_history: dict[str, list[str]] = defaultdict(list)


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(config_path.read_text())


def user_agent(contact_email: str) -> str:
    return f"FloodGuard-POC/0.1 (flood research; contact: {contact_email})"


def _meta_path(cam_id: str, yyyymmdd: str, meta_root: Path) -> Path:
    return meta_root / f"cctv_frames_{yyyymmdd}.jsonl"


def append_meta(meta: dict, meta_root: Path = META_ROOT) -> None:
    meta_root.mkdir(parents=True, exist_ok=True)
    path = _meta_path(meta["cam_id"], meta["ts_utc"][:10].replace("-", ""), meta_root)
    with path.open("a") as f:
        f.write(json.dumps(meta) + "\n")


async def fetch_and_process(
    cam_id: str,
    url: str,
    client: httpx.AsyncClient,
    cfg: dict,
    *,
    phash_history: dict[str, list[str]] | None = None,
    raw_root: Path = RAW_ROOT,
    thumbs_root: Path = THUMBS_ROOT,
    meta_root: Path = META_ROOT,
) -> dict:
    """Fetch one camera's snapshot, process it, write it, and append its
    metadata row. Never raises -- exceptions become an EXCEPTION meta row so
    the scheduler loop keeps running regardless of one camera's failure.
    Returns the meta dict that was recorded, for tests.
    """
    phash_history = _phash_history if phash_history is None else phash_history
    ts = datetime.now(timezone.utc)
    meta: dict = {"cam_id": cam_id, "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ")}

    try:
        resp = await client.get(url, timeout=cfg.get("timeout_s", 15))
    except Exception as exc:
        meta.update(http_status=None, quality_flag="EXCEPTION", error=str(exc)[:200])
        append_meta(meta, meta_root)
        return meta

    meta["http_status"] = resp.status_code
    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200 or not content_type.startswith("image/"):
        meta["quality_flag"] = "HTTP_ERROR"
        append_meta(meta, meta_root)
        return meta

    try:
        img = Image.open(BytesIO(resp.content))
        img.load()
        img = img.convert("RGB")
    except Exception as exc:
        meta.update(quality_flag="EXCEPTION", error=f"decode failed: {exc}"[:200])
        append_meta(meta, meta_root)
        return meta

    meta.update(
        process_and_save(
            img,
            cam_id,
            ts,
            cfg,
            phash_history=phash_history,
            raw_root=raw_root,
            thumbs_root=thumbs_root,
        )
    )
    append_meta(meta, meta_root)
    return meta


def process_and_save(
    img: Image.Image,
    cam_id: str,
    ts: datetime,
    cfg: dict,
    *,
    phash_history: dict[str, list[str]],
    raw_root: Path = RAW_ROOT,
    thumbs_root: Path = THUMBS_ROOT,
) -> dict:
    """Downscale, blur, quality-assess, and save one already-decoded frame.
    Shared by the live fetch path and `ingest_manual.py` (the NO_GO
    fallback) so both go through the exact same privacy/quality pipeline.
    Returns the fields to merge into that frame's meta row.
    """
    max_w = cfg.get("max_width_px", 640)
    if img.width > max_w:
        new_h = round(img.height * max_w / img.width)
        img = img.resize((max_w, new_h), Image.LANCZOS)

    img = blur_sensitive(img)

    history = phash_history[cam_id]
    result = assess(img, history, cfg.get("quality"))
    phash_history[cam_id] = (history + [result["phash"]])[-10:]  # bounded

    ts_str = ts.strftime("%Y%m%dT%H%M%SZ")
    yyyymmdd = ts.strftime("%Y%m%d")
    fname = f"{cam_id}_{ts_str}.jpg"

    raw_dir = raw_root / cam_id / yyyymmdd
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / fname
    img.save(raw_path, "JPEG", quality=85)
    raw_bytes = raw_path.read_bytes()

    thumb_w = cfg.get("thumb_width_px", 320)
    thumb = img.copy()
    thumb.thumbnail((thumb_w, thumb_w * img.height // img.width or 1))
    thumb_dir = thumbs_root / cam_id / yyyymmdd
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb.save(thumb_dir / fname, "JPEG", quality=85)

    return {
        "path": str(raw_path),
        "sha1": hashlib.sha1(raw_bytes).hexdigest(),
        "phash": result["phash"],
        "width": img.width,
        "height": img.height,
        "bytes": len(raw_bytes),
        "quality_flag": result["quality_flag"],
        "sat_mean": result["sat_mean"],
        "lap_var": result["lap_var"],
    }


def load_selected_cameras(
    registry_path: Path = REGISTRY_PATH, config_path: Path = CONFIG_PATH
) -> list[dict]:
    fc = json.loads(registry_path.read_text())
    cfg = load_config(config_path)
    return [f["properties"] for f in select_for_archive(fc, n=cfg.get("max_cameras", 50))]


def load_urls(urls_path: Path = URLS_PATH) -> dict[str, str]:
    if not urls_path.exists():
        return {}
    return json.loads(urls_path.read_text())


def check_legal_gate(cameras: list[dict], status_path: Path | str = None) -> None:
    """Raises LegalGateError (uncaught, on purpose) unless every selected
    camera's source is cleared. Never called with a try/except around it --
    a refusal here must stop startup, not be silently swallowed.

    `status_path` defaults to the real cctv/legal_status.yaml (via
    require_go's own default); only tests should override it.
    """
    sources = {c["source"] for c in cameras}
    kwargs = {"status_path": status_path} if status_path is not None else {}
    for source in sources:
        require_go(SOURCE_TO_LEGAL_KEY.get(source, source.lower()), **kwargs)


def build_scheduler(
    cameras_with_urls: list[tuple[str, str]],
    client: httpx.AsyncClient,
    cfg: dict,
    *,
    phash_history: dict[str, list[str]] | None = None,
) -> AsyncIOScheduler:
    """Builds (but does not start) the scheduler: one interval job per
    camera, min_interval_s apart with jitter_s jitter, first runs staggered
    uniformly across the interval so all cameras don't fire at once."""
    scheduler = AsyncIOScheduler()
    min_interval = cfg.get("min_interval_s", 120)
    jitter = cfg.get("jitter_s", 20)
    now = datetime.now(timezone.utc)
    n = max(len(cameras_with_urls), 1)
    for i, (cam_id, url) in enumerate(cameras_with_urls):
        start_offset = (i / n) * min_interval
        scheduler.add_job(
            fetch_and_process,
            trigger=IntervalTrigger(seconds=min_interval, jitter=jitter),
            args=[cam_id, url, client, cfg],
            kwargs={"phash_history": phash_history} if phash_history is not None else {},
            id=f"fetch-{cam_id}",
            max_instances=1,
            coalesce=True,
            next_run_time=now + timedelta(seconds=start_offset),
        )
    return scheduler


async def run() -> None:
    cfg = load_config()
    contact_email = os.environ.get("FG_CONTACT_EMAIL", "")
    if not contact_email:
        raise SystemExit("FG_CONTACT_EMAIL is not set; refusing to start (needed for the User-Agent)")

    cameras = load_selected_cameras()
    check_legal_gate(cameras)  # raises LegalGateError, uncaught, if any source isn't GO

    urls = load_urls()
    cameras_with_urls = [(c["cam_id"], urls[c["cam_id"]]) for c in cameras if c["cam_id"] in urls]
    if not cameras_with_urls:
        raise SystemExit("no camera has a snapshot URL in secrets/cctv_urls.json; nothing to archive")

    headers = {"User-Agent": user_agent(contact_email)}
    async with httpx.AsyncClient(headers=headers) as client:
        scheduler = build_scheduler(cameras_with_urls, client, cfg)
        scheduler.start()
        try:
            await asyncio.Event().wait()  # run forever
        finally:
            scheduler.shutdown(wait=False)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
