"""Legal gate for CCTV / DDS sources. See docs/VARUN_IMPLEMENTATION.md §6 T10.

No code may make automated requests to any CCTV or DDS source unless
cctv/legal_status.yaml says `decision: GO` for that source **and**
`approved_by` has been filled in by a human. This module only reads
legal_status.yaml — it must never write `decision` or `approved_by`.
"""
from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_STATUS_PATH = Path("cctv/legal_status.yaml")


class LegalGateError(Exception):
    """Raised when a source is not cleared for automated access."""


def _load_sources(status_path: Path) -> dict:
    if not status_path.exists():
        raise LegalGateError(f"legal status file not found: {status_path}")
    data = yaml.safe_load(status_path.read_text()) or {}
    return data.get("sources", {})


def require_go(source: str, status_path: Path | str = DEFAULT_STATUS_PATH) -> None:
    """Raise LegalGateError unless `source` is GO, approved, and acknowledged.

    Callers (archiver.py, dds_snapshot.py) must call this once per source
    before making any request to it, every time the process starts.
    """
    status_path = Path(status_path)
    sources = _load_sources(status_path)
    entry = sources.get(source)
    if entry is None:
        raise LegalGateError(f"unknown source {source!r} (not in {status_path})")

    decision = entry.get("decision")
    approved_by = entry.get("approved_by")
    conditions_ack = entry.get("conditions_ack", False)

    if decision != "GO":
        raise LegalGateError(f"{source}: decision is {decision!r}, not GO")
    if not approved_by:
        raise LegalGateError(f"{source}: GO but approved_by is empty")
    if not conditions_ack:
        raise LegalGateError(f"{source}: GO but conditions_ack is not true")
