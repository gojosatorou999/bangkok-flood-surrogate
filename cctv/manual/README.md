# Manual CCTV capture (NO_GO fallback)

If a source's legal review (`cctv/LEGAL_REVIEW.md`) comes back **NO_GO**, the automated archiver (T20) refuses to run against it — the legal gate (`cctv/legal_gate.py::require_go`) enforces this in code, not just by convention. This is the fallback: a human manually saves a handful of frames, and they get run through the exact same privacy pipeline before anything downstream ever sees them.

## How to capture frames manually

1. Open the camera feed in a browser (or whatever the source provides).
2. Save **at most 20 frames** per camera — screenshot, right-click-save-image, or a phone photo of a public display, whatever's available. Spread them out over time if you can (e.g. one every few minutes) rather than 20 in the same second — the point is to see how a road's flood state changes, not to have 20 copies of the same moment.
3. Put them all in one directory, named however you like (file order isn't used — only the fact that you captured them is).

## How to ingest them

```bash
python -m cctv.archiver.ingest_manual <directory> [--cam-id CAM_ID]
```

- `--cam-id` defaults to the directory's own name if you don't pass it — e.g. `python -m cctv.archiver.ingest_manual ./captures/BMAT-0012` infers `cam_id=BMAT-0012`.
- Every image goes through `blur_sensitive()` (face/plate blur) and the same resize/quality checks (`archiver.process_and_save`) as a live-captured frame — **before** anything is written to disk. Raw, unblurred bytes are never saved, same as the live path.
- Frames are written to the same `data/cctv/raw/{cam_id}/{YYYYMMDD}/...` / `data/cctv/thumbs/...` paths a live capture would use, with a meta row appended to `data/cctv/meta/cctv_frames_{YYYYMMDD}.jsonl` — `make cctv-compact` picks them up exactly like live frames.
- Only the first 20 images in a directory are used (alphabetical order), matching the "≤ 20 frames" cap above.

## Marking a camera as manual-only

If a camera's source is `NO_GO` (so it will only ever have manually-ingested frames, never live ones), record that in its scenario/registry metadata as `cctv_available: MANUAL_FRAMES` so downstream consumers (dashboard, classifier reports) can say so honestly rather than implying continuous live coverage.
