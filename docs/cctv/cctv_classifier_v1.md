# CCTV flood-severity classifier -- v1 report

*Visual flood severity proxy, never "depth".*

## Data

- Labelled frames (usable, NORMAL/WATERLOGGING/FLOODING/SEVERE_FLOODING): **0**
- Distinct cameras labelled: **0**
- Inter-rater kappa (double-labelled subset, ceiling for v1): N/A (no double-labelled overlap yet)

## Result

**insufficient labels: 0** across 0 camera(s) (need >= 20 labels across >= 3 cameras for an honest camera-held-out split). No probe was trained; shipping stays on zero-shot `clip-zs-v0` (`cctv/classifier/models/CHOSEN.txt` left unwritten).

## Limitations

- HU5 (frame labelling, 200-400 frames + a 50-frame double-label for kappa) has not produced enough labels yet to train or evaluate a probe. Re-run `python -m cctv.classifier.probe` once more labels exist.
- CCTV output is always a *visual flood severity proxy*, never a depth measurement.
- "Feasibility prototype -- not for flood warning."
