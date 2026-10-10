# Data gaps

Shared, append-only. Each teammate adds under their own heading; never edit another section.

## Varun

- **No public CCTV archive exists.** Unlike satellite or gauge data, there's no historical archive of Bangkok traffic CCTV frames to backfill from — the only way to ever get a real flood frame is to capture it live, during actual rain, once legal clearance (T10) and camera URLs (HU3) land. Missing this week's rain means waiting for the next one.
- **DDS archive depth is unknown.** How far back DDS's own road-flood/gauge history goes (if at all, beyond whatever's currently on the live page) isn't known without HU4 access to the real endpoints.
- **Camera headings are unknown for any real camera.** `cctv/registry/build_registry.py` has a `heading_deg` field in its schema, but no source for real values exists yet (HU2's camera CSV would need to supply it, or it stays `null`) — it matters for CCTV-to-road-geometry reasoning (T54) that this repo doesn't do today.
- **Real DDS payload format is unknown.** `ingest/dds.py`'s parser (T21) is written against a fixture sample, with `# TODO(HU4)` markers for adapting to the real payload once HU4 provides one saved real response per endpoint. Until then there's no way to know if the parser's assumptions about field names/structure hold.
- **Parent docs missing from the repo:** `docs/BANGKOK_FLOOD_POC_REQUIREMENTS_AND_WORKFLOW.md`, `docs/SCENARIO_SCHEMA.md`, `docs/TEAM_TASK_BOARD.md` are cited throughout `VARUN_IMPLEMENTATION.md` (§15.9, §17.10, SCENARIO_SCHEMA §3/§5, etc.) but were never placed in `docs/`. T01 fixtures reconstruct the few field lists this blocks from cross-references inside VARUN_IMPLEMENTATION.md itself — see `docs/assumptions.md` for each spot this was needed. Whoever holds these parent docs should drop them into `docs/` so later cards (T10 legal templates, T52 report, T53 handoff, T71 contract) can be checked against the real spec instead.
