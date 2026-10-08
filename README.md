# Bangkok Flood Surrogate

A neural emulator of an ANUGA rain + tide flood model for Bangkok, with a web UI. Given a rain series (mm per 15 min, uniform over the domain) and a Gulf tide series, it predicts water depth and flow speed on a 150 m grid (508 × 662 cells, EPSG:32647) at every 15-minute step. A 6-day event takes about 25 s on an RTX 4060.

It can also take field observations (CCTV depth readings and Sentinel-1 SAR flood maps), check them against the model and each other, and fine-tune itself against them ("self-calibration") without drifting away from the ANUGA physics.

## Layout

| Path | What it is |
|---|---|
| `flood_surrogate.py` | Data prep, U-Net model, training, evaluation, and the HTTP server (stdlib `http.server`, no web framework) |
| `calibration.py` | Observations (CCTV, SAR), validation checks, calibration rounds, model versions |
| `index.html` | The whole frontend: one file of HTML, CSS and vanilla JS, no build step, no dependencies |
| `cache/unet_film.pt` | Trained model (ANUGA-trained base, "v0") |
| `cache/metrics.json` | Accuracy against ANUGA per scenario (shown in the UI) |
| `cache/index.json` | Rain/tide series and start times of the 17 ANUGA scenarios |
| `data/` | Static layers (terrain, Manning n, curve number, …) and the rain/tide CSVs of every event |

Not in the repo (too big): `cache/*_depth.npy` / `*_speed.npy`, the 6.9 GB decompressed ANUGA results. Without them the app still runs every prediction; it just can't show the "ANUGA depth / error" comparison layers, and calibration rounds are disabled. They are rebuilt with `python flood_surrogate.py cache` on a machine that has the full `surrogate_dataset/`.

## Run

```bash
pip install -r requirements.txt        # CUDA build of torch for GPU: see pytorch.org
python flood_surrogate.py serve        # http://localhost:8000
```

Runs on an NVIDIA GPU when PyTorch sees one (bf16), otherwise on the CPU (much slower: about 4 s per time step).
Other commands: `train [--steps 7000] [--holdout S2,D4,L3,M3 | none]`, `eval`, `cache`.

## Model accuracy (held-out events S2, D4, L3, M3, never seen in training)

Depth RMSE 1.4 cm over all cells (3.7 cm where flooded), flood-extent CSI 0.91 at ≥ 0.15 m, peak flooded area −6 %. It inherits ANUGA's limits: uniform rain, synthetic tide, no pumps or sewers, 90 m terrain.

## Frontend notes

The UI has two views, switched in the header:

* **Simulate**: choose an input (ANUGA scenario, `data/inputs` event, design storm, pasted series), run, then browse maps (time slider, layers, side-by-side, click a cell for its time series), charts and downloads.
* **Observations & calibration**: events, CCTV readings (single or CSV import), Sentinel-1 uploads, the observation table with checks and status, model versions and calibration rounds.

All maps are PNGs rendered by the server (`/api/frame`, `/api/obs/png`), 662 × 508 px, transparent outside the model domain; row 0 is the north edge. A click at fraction (fx, fy) of the image is cell `row = floor(fy * 508)`, `col = floor(fx * 662)`. Colours for the legends come from `/api/meta` → `legends`.

## HTTP API

All JSON unless noted. Errors return HTTP 400 with `{"error": "..."}`.

### Simulation

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /api/meta` | | scenarios, input events, uploaded events, accuracy metrics, legends (CSS gradients), grid size, device, active model version, training range |
| `POST /api/run` | `{type:"scenario", sid}` · `{type:"inputs", sid, tide:"HT"\|"LT"}` · `{type:"event", id}` · `{type:"design", total_mm, duration_h, peak_pct, shape:"peaked"\|"triangular"\|"uniform", tail_h, lead_h, tide_amp, tide_shift_h}` · `{type:"custom", rain:"0 1 5 …", tide:"…"}` | `id` (run id, the server keeps the last 3), `T`, `hours[]`, `rain[]`, `tide[]`, `area_pred[]`, `area05_pred[]`, `area_true[]` (when ANUGA results exist), `summary`, `metrics` (when ANUGA results exist), `warnings[]`, `observations[]` |
| `GET /api/frame` | `run, layer, t, thr, obs` → PNG. Layers: `pred truth error speed truth_speed maxpred maxtruth`, static `dem cn manning coast base`, Sentinel-1 `sarcmp sarext sardepth` (with `obs=<id>`) | image/png |
| `GET /api/point` | `run, r, c` | depth series at a cell (`pred[]`, `truth[]`, `speed[]`) plus the cell's terrain, curve number, Manning n and UTM coordinates |
| `GET /api/download` | `run, what=series\|maxpred\|maxtruth` | CSV time series, or max-depth ESRI ASCII grid |

### Observations and calibration

| Method & path | Body / query | Returns |
|---|---|---|
| `POST /api/upload` | raw file body, header `X-Filename` (URI-encoded) | `{id, name, bytes}`: pass `id` to the calls below |
| `GET /api/obs/state` | | `events[]`, `observations[]`, `versions[]`, `rounds[]`, `active`, `auto`, `status` |
| `POST /api/obs/event` | `{name, rain_file, tide_file?}` (CSV ids; rain at 15-min steps, mm per 15 min) | `{id}` (e.g. `C1`) |
| `POST /api/obs/cctv` | `{event_id, time_local, lat, lon` *or* `row, col, depth_m, depth_low_m?, depth_high_m?, confidence?, before_depth_m?, camera?, notes?, before_file?, after_file?}` | the observation, with `checks[]` and `status` |
| `POST /api/obs/cctv_batch` | `{csv_file, images:{filename: id}, event_id?}`; CSV columns `lat, lon, time_local, depth_m` + the optional ones above (`before_image`/`after_image` = file names) | `{added, errors[], ids[]}` |
| `POST /api/obs/sar` | `{event_id, time_utc, mode:"backscatter"\|"mask", post_file, pre_file?, label?}` (GeoTIFF ids) | the observation, with SAR stats, `model_compare` and `checks[]` |
| `POST /api/obs/status` | `{id, status:"accepted"\|"flagged"\|"rejected"\|"auto"}` | the observation |
| `POST /api/obs/delete` | `{id}` | `{ok}` |
| `GET /api/obs/png` | `id, what=extent\|depth\|compare` | image/png of a SAR observation |
| `GET /api/obs/file` | `id` | an uploaded image (CCTV before/after) |
| `POST /api/calib/run` | `{steps?, anchor?, lr?, force?}`; starts a round in the background | `{started}`; poll `GET /api/calib/status` → `{state:"idle"\|"running"\|"error", msg, progress, round}` |
| `POST /api/calib/auto` | `{on}` | `{auto}` |
| `POST /api/calib/activate` | `{id}` (model version, e.g. `v0`) | `{active}` |

Observation checks: each entry is `{name, ok: true|false|null, severity: "hard"|"soft", detail}`. Auto status is `rejected` if a hard check fails, `flagged` (half weight in calibration) if a soft one fails, else `accepted`; `status_user` overrides it.
