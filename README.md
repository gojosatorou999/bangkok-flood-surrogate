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

## Flood dashboard (`/dashboard`)

An end-user view (`dashboard.html`, `static/dash/`, `dashboard.py`) on a MapLibre web map, with two modes:

* **Before flood**: real weather from **NOAA GFS** (`weather_gfs.py`): the past 24 h and the next 72 h of rain, temperature, humidity, wind and pressure for the model domain. The newest published cycle on `nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/` is found automatically, hourly 0.25° subsets are downloaded (≈ 100 small files, cached in `cache/gfs/`) and the surrogate runs on the rain (~45 s on an RTX 4060). A background thread asks NOAA every 10 min and recomputes when a new cycle or a new hour arrives; open pages pick it up by themselves. **The tide is an assumption** (GFS has none): high water at the rain peak, the one regime the model was trained on. If NOAA cannot be reached the page says so and shows a synthetic demo storm; `/dashboard?demo=heavy` (also `showers`, `ongoing`, `extreme`) forces a demo storm for presentations.
  The header's **alert button** (pulsing, coloured by the worst level) opens a list of every district, flooded ones first. Map markers are drawn only for flooded districts, on the deepest cell inside the district, at most 14.
* **During flood**: the CCTV database as a **depth heatmap** and as a **model + CCTV correction** layer. Alerts are escalated where cameras see more water than the model. A camera marker opens a popup with its photo.

**Map filter.** The model, like ANUGA without drains, ponds water in every depression. Flooded patches smaller than 50 cells of 150 m (≈ 1.1 km²) are dropped from every map, statistic and alert (`CLUSTER_MIN` in `dashboard.py`). **Light rain.** Forecasts far weaker than the weakest training event are flagged on the page: the model has no experience there and its small patches are unreliable.

Dashboard depths are flood water *above the dry-weather level*. A no-rain run gives the normal water in rivers, canals and the tidal coast; it is cached in `cache/dash_dry_max_<version>.npy` and subtracted. Alert thresholds come from `configs/thresholds.yaml` (watch ≥ 0.10 m, warning ≥ 0.15 m, severe ≥ 0.30 m). Districts are rated on the flood depth over their lowest quarter within 1.5 km, ranked by depth × a vulnerability index (low ground, sealed surfaces, close to the coast). A camera is evidence for its own district and for districts within 1.5 km.

**Language.** The server returns codes and numbers and both spellings of a name; all wording is in `static/dash/i18n.js`, so EN / ไทย is one synchronous re-render with no request.

The CCTV database is `data/cctv/cctv_readings.csv` (columns as in `cctv_image_details.csv`), plus `data/cctv/cctv_obs.parquet` once the classifier pipeline has run. The server re-reads it whenever the file changes, and the page polls every 15 s. Readings can also be added from the page (CSV import, or one reading by hand), and the alerts update immediately. Readings without a location, unusable frames, and the same photo filed under two camera ids are left off the map and listed with the reason.

| Method & path | Returns |
|---|---|
| `GET /api/dash/meta` | map bounds, districts (both spellings) with vulnerability, legends, thresholds, demo scenario ids |
| `GET /api/dash/forecast[?demo=]` | weather series + `rain_summary`, `current`, `source` (NOAA cycle / demo), flooded-area series, warnings as codes |
| `GET /api/dash/status`, `GET /api/dash/health` | loading stage (fetch / model / ready), forecast id and source, device |
| `GET /api/dash/overlay?kind=depth\|max\|cctv\|fused&t=&thr=&sigma=` | Web-Mercator PNG for the map's image source |
| `GET /api/dash/alerts?phase=before\|during&t=` | districts with level, depth, onset, deepest-cell position, CCTV evidence; counts; timeline as structured items |
| `GET /api/dash/cctv`, `GET /api/dash/cctv/version` | readings with exclusion reasons as codes and model depth at each camera; change counter |
| `GET /api/dash/point?lat=&lon=` | forecast flood-depth series at a point |
| `GET /api/dash/wb_frame?run=&layer=&t=&thr=&clean=`, `wb_cell`, `wb_sar` | workbench layers as Web-Mercator PNG; the cell under a point with its series; Sentinel-1 layers |
| `POST /api/dash/cctv/upload` (raw CSV), `POST /api/dash/cctv/add` (`{cam_id, lat, lon, depth_m, cls?, confidence?, notes?}`) | merge readings into the CSV |

MapLibre GL is vendored in `static/maplibre/`. Basemap tiles (OpenFreeMap / Esri / CARTO / OSM) and NOAA need internet. NOAA GRIB decoding needs `eccodes` (`pip install eccodes`, wheel includes the binary).

## Deployment (Vercel + AWS)

`FLOOD_MODE=full|worker|web` splits the app so that only a short GPU job needs a GPU: a **worker** computes the NOAA-driven
forecast 4 times a day and publishes a ~17 MB bundle, a small CPU **web** server serves the API from it, and the static pages
go to Vercel. Old forecasts and NOAA files are replaced, never accumulated. Step-by-step guide, IAM policies, systemd units,
Caddy HTTPS, schedule and cost table: [`deploy/DEPLOY.md`](deploy/DEPLOY.md). `python deploy/build_frontend.py` builds the Vercel
output; `vercel.json` holds the build settings and the `/api` rewrite to the backend.

## CCTV pipeline (from Bangkok-Flood-POC)

`cctv/`, `configs/`, `ingest/`, `validation/cctv/` and `docs/cctv/` are copied unchanged from [varunmax7/Bangkok-Flood-POC](https://github.com/varunmax7/Bangkok-Flood-POC): camera registry, legal gate, privacy-preserving archiver and manual ingest, CLIP zero-shot classifier (`cctv_obs.parquet`), labelling app, DDS ingest, and the CCTV-vs-model comparison helpers. Run them from this folder (they use paths relative to it), for example `python -m cctv.archiver.ingest_manual <dir>` and then `python -m cctv.classifier.write_obs`. They need the optional packages listed in `requirements.txt`. The archiver refuses to run until `cctv/legal_status.yaml` says `GO` for the source.

## Model accuracy (held-out events S2, D4, L3, M3, never seen in training)

Depth RMSE 1.4 cm over all cells (3.7 cm where flooded), flood-extent CSI 0.91 at ≥ 0.15 m, peak flooded area −6 %. It inherits ANUGA's limits: uniform rain, synthetic tide, no pumps or sewers, 90 m terrain.

## Frontend notes

The UI has two views, switched in the header:

* **Simulate**: choose an input (ANUGA scenario, `data/inputs` event, design storm, pasted series), run, then browse maps on a real basemap (time slider, layers, basemap choice, side-by-side with ANUGA as two synced maps, hover and click a cell for its values and time series, isolated-patch filter), charts and downloads.
* **Observations & calibration**: events, CCTV readings (single or CSV import), Sentinel-1 uploads, the observation table with checks and status, model versions and calibration rounds.

Workbench maps are MapLibre maps (`static/dash/wbmap.js`) with server-rendered Web-Mercator PNG overlays (`/api/dash/wb_frame`). The older native-grid PNGs (`/api/frame`, `/api/obs/png`, 662 × 508 px, row 0 north) are still served. Colours for the legends come from `/api/meta` → `legends`.

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

## Dashboard v2 (3D map, EN/ไทย, before/after)

* **Language**: `EN | ไทย` switch in both `/` (workbench) and `/dashboard`; shared choice (`localStorage fd_lang`, or `?lang=th`). Server-composed text (alerts, timeline, warnings, scenario names) is localised by the backend via `?lang=`.
* **Map** (MapLibre GL, vendored in `static/maplibre/`): 2D/3D, terrain from the model DEM (`/api/dash/terrain/{z}/{x}/{y}.png`), extruded flood water (`/api/dash/flood3d`, viewport-limited), 3D buildings, Streets/Satellite/Light/Dark/OSM basemaps (Thai or English labels), zoom to 22 with a 3200 px nearest-neighbour overlay (`res=hi`) so each 150 m cell is a visible block; hover shows the cell (`/api/dash/cell`).
* **Before / after**: swipe compare — no flood vs flood, model vs model+CCTV, now vs selected time.
* **What-if**: rain scale, duration stretch, tide offset re-run the surrogate (`/api/dash/forecast?rain_scale=&stretch=&tide_offset=`).
* **Cameras**: registry (`/api/dash/cameras`), privacy-processed photos (`/api/dash/cctv/image`), class probabilities, depth gauge, lightbox. Photos come from `my_manual_images/` via `python -m cctv.archiver.ingest_manual my_manual_images/camN --cam-id MANUAL-000N`, then `python -m cctv.classifier.write_obs`.
* `/api/dash/health` backs the online/offline pill. Restart the server after pulling this change.
