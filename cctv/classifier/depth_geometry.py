"""Reference-object depth-from-image geometry.

Converts a VLM's *qualitative* read of a photo (which known-size object is
visible, and where the waterline sits against it) into a depth estimate in
metres. The VLM (`vlm_depth.py`) only ever describes what it sees -- it
never outputs a number itself. All arithmetic lives here, in plain,
auditable Python, so every number this module produces can be traced back
to an explicit reference height and a one-line formula.

This is a visual *estimate* anchored to typical object sizes, not a
calibrated measurement -- see REFERENCE_HEIGHTS_M for the uncertainty each
entry carries, and `estimate_depth` always returns that uncertainty
alongside the estimate. Never silently invents a number when no usable
reference object was reported (mirrors the "UNUSABLE" convention in
write_obs.py): returns None with a reason instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# (low_m, mid_m, high_m) for each (object type, landmark) pair -- the
# height of that landmark off the ground, in metres. [ASSUMPTION] round
# figures for a typical Bangkok road/residential scene; not derived from
# surveyed measurements of any specific vehicle model, person, or fixture
# -- revisit once real paired ground-truth depth data exists (see
# cctv/classifier/probe.py's MIN_TOTAL_LABELS gate for the same caution
# applied to the severity classifier).
REFERENCE_HEIGHTS_M: dict[tuple[str, str], tuple[float, float, float]] = {
    ("car", "wheel_bottom"): (0.00, 0.00, 0.00),
    ("car", "wheel_top"): (0.55, 0.62, 0.70),
    ("car", "door_sill"): (0.38, 0.45, 0.52),
    ("car", "bonnet"): (0.70, 0.80, 0.90),
    ("car", "window_sill"): (0.95, 1.05, 1.15),
    ("car", "roof"): (1.40, 1.50, 1.62),
    ("motorcycle", "seat"): (0.72, 0.80, 0.88),
    ("motorcycle", "handlebar"): (0.95, 1.05, 1.15),
    ("person_adult", "ankle"): (0.08, 0.10, 0.13),
    ("person_adult", "knee"): (0.40, 0.46, 0.52),
    ("person_adult", "thigh"): (0.55, 0.65, 0.75),
    ("person_adult", "waist"): (0.85, 0.95, 1.05),
    ("person_adult", "chest"): (1.15, 1.25, 1.35),
    ("person_adult", "shoulder"): (1.35, 1.45, 1.55),
    ("pedestrian_railing", "top"): (0.85, 0.95, 1.05),
    ("pedestrian_railing", "mid"): (0.42, 0.48, 0.55),
    ("bus_bench", "seat"): (0.40, 0.45, 0.50),
    ("curb", "top"): (0.12, 0.15, 0.18),
    ("indoor_furniture", "low_table_leg"): (0.35, 0.42, 0.48),
    ("indoor_furniture", "bed_frame"): (0.42, 0.50, 0.58),
    ("doorway", "threshold"): (0.00, 0.02, 0.05),
}

VALID_RELATIONS = ("below", "at", "above", "fully_submerged")


@dataclass
class ObjectReading:
    """One reference object the VLM reported seeing in a frame."""
    object_type: str
    landmark: str
    waterline_relation: str  # one of VALID_RELATIONS
    vlm_confidence: str = "medium"  # "high" | "medium" | "low"


@dataclass
class DepthEstimate:
    depth_m: float | None
    low_m: float | None
    high_m: float | None
    confidence: str  # "high" | "medium" | "low" | "none"
    basis: list[str] = field(default_factory=list)
    reason: str | None = None  # set when depth_m is None, or readings disagreed


def _landmark_bracket(reading: ObjectReading) -> tuple[float, float, float] | None:
    key = (reading.object_type, reading.landmark)
    return REFERENCE_HEIGHTS_M.get(key)


def _single_reading_estimate(reading: ObjectReading) -> tuple[float, float, float] | None:
    """Returns (low, mid, high) metres implied by one reading, or None if unusable."""
    bracket = _landmark_bracket(reading)
    if bracket is None:
        return None
    low, mid, high = bracket

    if reading.waterline_relation == "at":
        return (low, mid, high)
    if reading.waterline_relation == "fully_submerged":
        # Depth is at least this landmark's height; we don't know how much
        # more, so report the landmark height as a floor (wide upper bound).
        return (high, high * 1.15, high * 1.6)
    if reading.waterline_relation == "above":
        # Waterline is somewhere above this landmark but the VLM didn't
        # name a higher one -- same floor logic as fully_submerged, less confident.
        return (high, high * 1.1, high * 1.4)
    if reading.waterline_relation == "below":
        # Only tells us an upper bound; not useful as a standalone estimate.
        return (0.0, low / 2, low)
    return None


def estimate_depth(readings: list[ObjectReading]) -> DepthEstimate:
    """Combines all reference-object readings for one frame into one estimate.

    Deliberately conservative: "below X" readings alone never produce a
    confident number (they only bound from above); "at X" readings from
    multiple objects are required to agree (overlapping brackets) before
    confidence is "high" -- a single object never earns "high".
    """
    if not readings:
        return DepthEstimate(None, None, None, "none", reason="no reference object identified in frame")

    at_or_submerged = [r for r in readings if r.waterline_relation in ("at", "fully_submerged", "above")]
    if not at_or_submerged:
        # only "below" readings -- we only have an upper bound, not a depth
        bounds = [b for r in readings if (b := _landmark_bracket(r)) is not None]
        if not bounds:
            return DepthEstimate(None, None, None, "none", reason="reference object(s) unrecognised")
        upper = min(b[0] for b in bounds)  # tightest "low" bound among them
        return DepthEstimate(
            None, 0.0, upper, "low",
            basis=[f"{r.object_type}/{r.landmark} ({r.waterline_relation})" for r in readings],
            reason="only upper-bound ('below') readings available; no positive depth estimate",
        )

    brackets = []
    basis = []
    for r in at_or_submerged:
        est = _single_reading_estimate(r)
        if est is None:
            continue
        brackets.append(est)
        basis.append(f"{r.object_type}/{r.landmark} ({r.waterline_relation}, vlm_conf={r.vlm_confidence})")

    if not brackets:
        return DepthEstimate(None, None, None, "none", reason="reference object(s) unrecognised")

    los = [b[0] for b in brackets]
    mids = [b[1] for b in brackets]
    his = [b[2] for b in brackets]
    overlap_lo, overlap_hi = max(los), min(his)
    agree = overlap_lo <= overlap_hi

    depth = sum(mids) / len(mids)
    low = min(los)
    high = max(his)

    if len(brackets) == 1:
        confidence = "medium" if at_or_submerged[0].vlm_confidence != "low" else "low"
    elif agree:
        confidence = "high"
    else:
        confidence = "low"  # multiple objects, but their implied depths don't overlap -- disagreement

    reason = None if agree or len(brackets) == 1 else (
        f"{len(brackets)} reference objects disagree "
        f"(ranges don't overlap: widest span {low:.2f}-{high:.2f} m) -- treat as low-confidence"
    )

    return DepthEstimate(round(depth, 3), round(low, 3), round(high, 3), confidence, basis, reason)
