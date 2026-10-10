# Sensor ingestion spec (O11)

**Status: design + stub only — no hardware exists in this POC.** `POST /ingest/v1/observations` (T80) validates and stores whatever's posted to it in exactly the shape described here, so a future device/bridge integration is a drop-in, not a redesign.

[ASSUMPTION] §19's own architecture diagram isn't available in this repo (the parent requirements doc is missing — same gap noted elsewhere in `docs/assumptions.md`). The pipeline below is reconstructed from what's referenced across this plan (the `POST /ingest/v1/observations` contract itself, T21's DDS scraping, the SCENARIO_SCHEMA station/observation shapes).

## Architecture

```
physical sensor (water level / rain / flow / camera)
        |  MQTT publish, TLS, per-device client cert
        v
MQTT broker  --  topic: floodguard/bkk/{site_id}/{sensor_type}/obs
        |
        v
MQTT -> HTTP bridge  ------------->  POST /ingest/v1/observations
        |                                   |  X-API-Key, JSON Schema validate,
        |                                   |  idempotency (site_id+ts+sensor_type)
        |                                   v
        |                           data/interim/ingest/obs_{YYYYMMDD}.jsonl  (POC store)
        |
        +-- virtual sensors (DDS / ThaiWater / TMD scrapers) also post here,
            normalized to the same payload shape -- see "Virtual-sensor
            mapping" below
```

In the POC, only the HTTP endpoint exists; the MQTT broker and bridge are pilot infrastructure (see "Pilot path"). Already-scraped public sources (T21) map into the same payload and post through the identical endpoint, so nothing downstream needs to know whether an observation came from real hardware or a scraper.

## MQTT topic convention

`floodguard/bkk/{site_id}/{sensor_type}/obs`

- `site_id`: `^BKK-(WL|RN|FL|CAM)-\d{4}$` — same pattern the HTTP payload's `site_id` enforces.
- `sensor_type`: `wl` (water level) | `rain` | `flow` | `cam`.

## Security

- TLS on every MQTT connection — broker-enforced, no plaintext fallback.
- Per-device client certificate (or at minimum a per-device username/password) issued at provisioning; never a secret shared across devices.
- The HTTP ingest endpoint separately requires `X-API-Key` (`FG_API_KEY_INGEST`). The MQTT→HTTP bridge holds that key; individual devices never see it.

## Payload + schema

One observation per MQTT message, in the same shape the HTTP endpoint validates (`dashboard/api/schemas/observation.schema.json`):

```json
{
  "site_id": "BKK-WL-0001",
  "sensor_type": "wl",
  "ts": "2026-09-25T10:00:00Z",
  "value": 0.42,
  "unit": "m",
  "datum": "MSL",
  "quality": "raw",
  "battery_v": 3.7,
  "fw": "1.2.0",
  "seq": 1042
}
```

| Field | Required | Notes |
|---|---|---|
| `site_id` | yes | `^BKK-(WL\|RN\|FL\|CAM)-\d{4}$` |
| `sensor_type` | yes | `wl \| rain \| flow \| cam` |
| `ts` | yes | ISO-8601 UTC, `Z` suffix |
| `value` | yes | numeric, already unit-normalized (see below) |
| `unit` | yes | `m \| mm \| m3s \| class` |
| `datum` | no | vertical datum for `wl` (e.g. `MSL`); omitted for non-level sensors |
| `quality` | yes | `raw` (device-reported, unfiltered) or `qc` (passed the checks below) |
| `battery_v`, `fw`, `seq` | no | device health / message-ordering metadata |

## Unit / datum normalization

Devices and scrapers normalize *before* publishing — the backend only validates, it never converts:

- **Water level (`wl`)** → meters, relative to **MSL** (mean sea level). A device reporting depth relative to its own sensor must apply its known sensor-to-MSL offset before publishing.
- **Rain (`rain`)** → millimeters, per-interval (a total, not an hourly rate) — matches the `mm` unit already used for DDS rain gauges and the 07:00–07:00 ICT daily-window convention noted in `docs/assumptions.md`.
- **Flow (`flow`)** → cubic meters/second (`m3s`).
- **CCTV (`cam`)** → `class` unit, one of the CCTV classifier's five classes (`NORMAL`, `WATERLOGGING`, `FLOODING`, `SEVERE_FLOODING`, `UNUSABLE`) — lets a camera "sensor" report just its classification without the full image pipeline.
- **Timestamps** → UTC with a `Z` suffix, always — never local ICT (Agent rule 7).

## QC flags

Computed by the device when possible (`quality: "qc"`); otherwise the ingest pipeline computes them before anything downstream trusts a `raw` value:

- **Range** — value outside the sensor type's physically plausible span (e.g. negative rain, a water level far outside the gauge's calibrated range).
- **Rate-of-change** — an implausible jump between consecutive readings from the same `site_id`, faster than the physical system could actually move.
- **Flatline** — N consecutive identical readings from the same `site_id`; usually a stuck or dead sensor, not a genuine plateau.
- **Battery** — `battery_v` below a device-specific low-battery threshold; downstream consumers should discount readings from that device.

A failed QC check is metadata for downstream consumers (dashboard, validation) to weigh, not a reason to reject the observation at ingest — rejection at `/ingest/v1/observations` is for schema/auth/idempotency failures only.

## Virtual-sensor mapping (DDS / ThaiWater / TMD)

Already-scraped public sources (T21's DDS road-flood/gauge snapshotter; ThaiWater, TMD if added later) are "virtual sensors": a small adapter maps each source's native record into the observation payload above and posts it through the identical `/ingest/v1/observations` endpoint (or, at pilot scale, publishes to the identical MQTT topic convention under a `site_id` prefix reserved for virtual sources). One ingestion path, one schema, real hardware or not.

## Pilot path (post-POC)

- **Broker**: EMQX or Mosquitto, TLS-only, per-device client certs issued at provisioning.
- **Bridge**: a small service subscribing to `floodguard/bkk/#`, applying the QC flags above, and posting batches to `/ingest/v1/observations`.
- **Store**: TimescaleDB or PostGIS (time-series + spatial in one engine), replacing the POC's flat `data/interim/ingest/obs_{YYYYMMDD}.jsonl` files.
- **No hardware in this POC** — everything above is design only, exercised end to end by posting synthetic/manual observations through the HTTP endpoint (`tests/varun/test_ingest.py`).
