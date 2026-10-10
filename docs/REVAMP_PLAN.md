# Dashboard revamp: 3-phase plan

Scope: `/dashboard` (Before flood + During flood) and the model workbench maps (`/`).
Status is tracked at the bottom. Each phase ends in something you can open and check.

## What was wrong (root causes found in the code)

| What you saw | Cause |
|---|---|
| Dots everywhere (grey, red, orange) | `drawDistricts()` draws all 58 district centres, including level 0 ("No flooding", grey), at the *district office* position, not where the water is |
| Blue speckle over the whole city | The surrogate (like ANUGA, which has no drains) ponds water in every 150 m depression; each isolated cell ≥ 0.15 m is painted |
| Fake weather | `synth_weather()` draws random rain cells from 4 presets |
| Language switch half-done and slow | `changeLang()` re-requests meta, forecast, alerts, cameras and CCTV, and the *server* composes the text. Static labels flip at once, server text arrives seconds later |
| Long alert paragraphs, buried in the side bar | `_message()` builds a paragraph per district |

## Phase 1: Real data and honest map (backend)

1. **NOAA GFS ingest** (`weather_gfs.py`)
   - Find the newest complete cycle in `nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/` (probe `.idx`).
   - Download hourly 0.25 degree subsets over the model domain (APCP, 2 m T, RH, 10 m wind, gust, MSLP), decode with `eccodes`, cache per cycle and hour on disk.
   - Past 24 h from the previous cycles' first 6 forecast hours, next 72 h from the newest cycle. Hourly rain is spread over four 15-min steps.
   - Builds the same weather dict the model already takes (rain mm/15 min + tide).
   - Fallback: if NOAA is unreachable the old synthetic series is used and the page says so in red.
2. **Forecast wiring**: the default forecast is the real one; refreshed in the background when a new cycle or a new hour arrives; progress reported at `/api/dash/status`.
3. **Patch filter**: flooded patches smaller than 50 connected 150 m cells (about 1.1 km²) are dropped. Tuned on the S2 test event (a neighbour-count filter was tried first and left the specks in the max-depth map). Used by overlays, 3D, district statistics, area series and the point read-out, so the map and the numbers agree.
3b. **Light-rain warning**: forecasts far weaker than the weakest training event are flagged, because the model only ever saw heavy events.
4. **Realistic alert points**: one marker per district that is actually flooded, placed on the deepest cell inside that district's 1.5 km disc, labelled with its depth. None for "No flooding".
5. **Language-neutral API**: alerts, timeline, warnings and CCTV exclusion reasons are returned as codes and numbers; no server-composed prose.

Check: `/api/dash/health` shows `forecast_source: gfs` and the cycle; the map has no isolated specks; markers sit on flooded areas.

## Phase 2: Dashboard layout and language (frontend)

| Request | Change |
|---|---|
| Alerts to the top, single line, animated dropdown | Header alert button with pulsing count badge, colour of the worst level; dropdown lists **all** districts, one line each, flooded first, with a filter box |
| Weather: 4-5 points only | Temperature and condition, rain next 24 h, rain next 72 h, wind, peak rain time. Days, charts, "synthetic" tag gone |
| Timeline under weather; accuracy under timeline | Side-bar order: Weather, Timeline, Model accuracy |
| Remove camera photos card and What-if | Both cards deleted (code and CSS) |
| Photo visible when a camera point is clicked | Map popup with the photo, class, depth, time, "details" |
| During flood: smaller CCTV window and readings, no accuracy | Compact camera card (100 px photo), compact readings table, accuracy card hidden |
| Grey spots | Level-0 district dots and the registry dots removed |
| Smooth, complete language switch | One synchronous re-render from cached data, no network call, fade; all text from the i18n tables |

Check: toggling EN/ไทย changes every visible string in one frame; nothing remains in the other language.

## Phase 3: Workbench maps (`/`)

- Replace the flat `<img>` maps with the same MapLibre stack as the dashboard: street/satellite basemap, pan and zoom to single cells, hover read-out, 2D/3D, side-by-side with ANUGA as two synced maps.
- New server endpoint renders any workbench layer (predicted, ANUGA, error, speed, max depth, terrain, curve number, Manning n, coast distance) in Web Mercator, with the same despeckle switch (on by default).
- Click a cell: time series as before; observation markers (CCTV/SAR) become map markers.
- Header/legend styling matched to the dashboard.

Check: the S2 test event shows on a real basemap, specks gone, zoom to cell level works, side-by-side stays in sync.

## Decisions I made (tell me if you want them different)

- **Tide is still an assumption.** GFS has no tide. The model needs one, so it is assumed high water at the rain peak (the only regime it was trained on). This is labelled on the page. A real gauge feed is the next data upgrade.
- **Synthetic scenarios are kept only as a hidden demo**: `/dashboard?demo=heavy` (also `showers`, `ongoing`, `extreme`) for presentations when real weather is dry. Not in the UI.
- **Camera registry toggle removed.** Cameras without a reading carried no information and were the grey dots.
- **A camera only raises the alert of its own district and districts within 1.5 km** (was 3 km), and camera-sourced alerts are not drawn as extra pills: the camera's photo marker is already there.
- **Old front-end files were replaced in place** (they were not under git). Backups of the previous `dashboard.py` and workbench `index.html` are in `docs/revamp_backup/`.

## Status

- [x] Phase 1: backend (NOAA GFS, patch filter, deepest-cell markers, language-neutral API)
- [x] Phase 2: dashboard layout and language
- [x] Phase 3: workbench maps (MapLibre, side-by-side, hover, basemaps, SAR layers)
