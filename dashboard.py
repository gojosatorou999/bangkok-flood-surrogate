"""End-user flood dashboard (page: dashboard.html, served at /dashboard).

Before a flood
  * the NOAA GFS weather forecast (weather_gfs.py): rain, temperature, humidity, wind, pressure for the last 24 h and the
    next 72 h. The tide is an assumption (high water at the rain peak: the only regime the model was trained on).
    If NOAA cannot be reached the old synthetic series is used instead and flagged as demo data,
  * the surrogate's depth maps for that forecast, reprojected onto a web map (EPSG:3857),
  * alerts for the districts forecast to flood, ranked by forecast depth and by how vulnerable the district is.
During a flood
  * the CCTV database (data/cctv/cctv_readings.csv, plus data/cctv/cctv_obs.parquet once the cctv/ classifier
    pipeline has run) as a depth heatmap and as a correction of the model's depth map,
  * the same alerts, escalated where cameras see more water than the model predicts. The CSV is re-read whenever
    it changes on disk, so appending readings (by hand, by the pipeline or through the page) updates the alerts.

CCTV depths are visual proxies from a zero-shot image classifier, not gauges. Free text is never composed here: alerts, the
timeline, warnings and CCTV exclusion reasons are returned as codes and numbers and worded by the page, so switching the
language needs no request.
"""
import io, json, math, os, re, shutil, threading, time
from pathlib import Path
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import torch

import flood_surrogate as fs
import weather_gfs

ICT = timezone(timedelta(hours=7))
CCTV_DIR = fs.APP_DIR / 'data' / 'cctv'
CCTV_CSV = CCTV_DIR / 'cctv_readings.csv'
CCTV_PIPELINE = CCTV_DIR / 'cctv_obs.parquet'          # written by `python -m cctv.classifier.write_obs`
REGISTRY_FILES = (fs.APP_DIR / 'cctv' / 'registry' / 'manual_cameras.json', fs.APP_DIR / 'cctv' / 'registry' / 'cameras.geojson')
THUMBS = CCTV_DIR / 'thumbs'      # privacy-processed frames written by cctv.archiver (downscaled, faces/plates blurred)
RAW = CCTV_DIR / 'raw'            # the same frames at up to 640 px (still blurred); shown in the lightbox
THRESHOLDS = fs.APP_DIR / 'configs' / 'thresholds.yaml'
PAGE = fs.APP_DIR / 'dashboard.html'
STATIC = fs.APP_DIR / 'static'
PAST_H, AHEAD_H = 24, 72
NEAR_KM = 1.5            # neighbourhood of a district used for its forecast depth
STAT_Q = 0.75            # a district's depth = depth exceeded on its deepest quarter (of that neighbourhood)
CCTV_NEAR_KM = 1.5       # a camera is evidence for its own district and for districts this close to it
MAP_W = 1000             # web-map overlay width (px)
MAP_W_HI = int(os.environ.get('FLOOD_MAP_W_HI') or (1800 if fs.WEB else 2400))   # smaller on the web box (RAM)          # high-resolution overlay width (px) used when zoomed in to the individual 150 m cells
MAX_3D_CELLS = 45000     # most polygons sent for the 3D flood layer (cells are merged in blocks until they fit)
TERRAIN_CACHE = 600      # terrain tiles kept in memory
PEAK_CAP = 20.0          # mm / 15 min; the largest burst in training was 24.5
CLUSTER_MIN = 50         # flooded patches smaller than this many 150 m cells (~1.1 km2) are dropped from every map and statistic
CLUSTER_THR = 0.10       # depth (m) at which neighbouring cells count as one flooded patch
DEMO_PRESET = 'heavy'    # the one demo dataset (synthetic monsoon-trough storm), pre-computed in the background
MARKERS_MAX = 14         # most district markers drawn on the map
REFRESH_S = 600          # how often the background thread asks NOAA for a newer cycle
CSV_COLUMNS = ['cam_id', 'ingested_date_ict', 'ingested_time_ict', 'ingested_ts_utc', 'real_capture_datetime_known', 'lat', 'lon',
               'location_method', 'predicted_class', 'estimated_water_depth_m', 'confidence_score', 'is_submerged',
               'water_pixel_pct', 'quality_flag', 'model_version', 'notes']

LEVEL_NAMES = ['No flooding', 'Watch', 'Warning', 'Severe']
CLASS_LEVEL = {'NORMAL': 0, 'WATERLOGGING': 1, 'FLOODING': 2, 'SEVERE_FLOODING': 3}

# Approximate district-office positions (WGS84): the 50 Bangkok khet plus the neighbouring districts inside the model
# domain. Used only to name and place alerts; the depth behind an alert is read from a 1.5 km disc around the point.
DISTRICTS = [
    ('Phra Nakhon', 13.7640, 100.4991), ('Dusit', 13.7770, 100.5126), ('Nong Chok', 13.8556, 100.8625),
    ('Bang Rak', 13.7302, 100.5241), ('Bang Khen', 13.8736, 100.5964), ('Bang Kapi', 13.7656, 100.6474),
    ('Pathum Wan', 13.7445, 100.5223), ('Pom Prap Sattru Phai', 13.7580, 100.5131), ('Phra Khanong', 13.7022, 100.6014),
    ('Min Buri', 13.8137, 100.7480), ('Lat Krabang', 13.7227, 100.7593), ('Yan Nawa', 13.6967, 100.5431),
    ('Samphanthawong', 13.7314, 100.5134), ('Phaya Thai', 13.7802, 100.5419), ('Thon Buri', 13.7247, 100.4858),
    ('Bangkok Yai', 13.7230, 100.4763), ('Huai Khwang', 13.7765, 100.5794), ('Khlong San', 13.7300, 100.5090),
    ('Taling Chan', 13.7770, 100.4565), ('Bangkok Noi', 13.7704, 100.4682), ('Bang Khun Thian', 13.6603, 100.4355),
    ('Phasi Charoen', 13.7148, 100.4370), ('Nong Khaem', 13.7046, 100.3496), ('Rat Burana', 13.6823, 100.5058),
    ('Bang Phlat', 13.7937, 100.5050), ('Din Daeng', 13.7699, 100.5529), ('Bueng Kum', 13.7853, 100.6690),
    ('Sathon', 13.7081, 100.5262), ('Bang Sue', 13.8093, 100.5374), ('Chatuchak', 13.8285, 100.5597),
    ('Bang Kho Laem', 13.6931, 100.5030), ('Prawet', 13.7170, 100.6947), ('Khlong Toei', 13.7081, 100.5840),
    ('Suan Luang', 13.7302, 100.6510), ('Chom Thong', 13.6773, 100.4844), ('Don Mueang', 13.9130, 100.5895),
    ('Ratchathewi', 13.7589, 100.5342), ('Lat Phrao', 13.8033, 100.6075), ('Watthana', 13.7421, 100.5859),
    ('Bang Khae', 13.6963, 100.4091), ('Lak Si', 13.8870, 100.5788), ('Sai Mai', 13.9195, 100.6458),
    ('Khan Na Yao', 13.8269, 100.6770), ('Saphan Sung', 13.7692, 100.6851), ('Wang Thonglang', 13.7802, 100.6062),
    ('Khlong Sam Wa', 13.8597, 100.7040), ('Bang Na', 13.6680, 100.6043), ('Thawi Watthana', 13.7881, 100.3622),
    ('Thung Khru', 13.6497, 100.4952), ('Bang Bon', 13.6600, 100.3800),
    ('Mueang Nonthaburi', 13.8621, 100.5144), ('Pak Kret', 13.9130, 100.4985), ('Mueang Samut Prakan', 13.5991, 100.5968),
    ('Phra Pradaeng', 13.6590, 100.5330), ('Bang Phli', 13.6060, 100.7065), ('Mueang Pathum Thani', 14.0208, 100.5250),
    ('Thanyaburi (Rangsit)', 13.9867, 100.6164), ('Lam Luk Ka', 13.9726, 100.7500),
]

PRESETS = OrderedDict([
    ('showers', 'Afternoon showers (typical October)'),
    ('heavy', 'Monsoon trough: heavy rain tomorrow evening'),
    ('ongoing', 'Storm in progress since last evening'),
    ('extreme', 'Tropical depression: extreme rain'),
])


# ------------------------------------------------------------------------------------------------ names
# The page words everything itself (en / th); the server only supplies codes, numbers and both spellings of a name.
DISTRICT_TH = {
    'Phra Nakhon': 'พระนคร', 'Dusit': 'ดุสิต', 'Nong Chok': 'หนองจอก', 'Bang Rak': 'บางรัก', 'Bang Khen': 'บางเขน',
    'Bang Kapi': 'บางกะปิ', 'Pathum Wan': 'ปทุมวัน', 'Pom Prap Sattru Phai': 'ป้อมปราบศัตรูพ่าย', 'Phra Khanong': 'พระโขนง',
    'Min Buri': 'มีนบุรี', 'Lat Krabang': 'ลาดกระบัง', 'Yan Nawa': 'ยานนาวา', 'Samphanthawong': 'สัมพันธวงศ์',
    'Phaya Thai': 'พญาไท', 'Thon Buri': 'ธนบุรี', 'Bangkok Yai': 'บางกอกใหญ่', 'Huai Khwang': 'ห้วยขวาง',
    'Khlong San': 'คลองสาน', 'Taling Chan': 'ตลิ่งชัน', 'Bangkok Noi': 'บางกอกน้อย', 'Bang Khun Thian': 'บางขุนเทียน',
    'Phasi Charoen': 'ภาษีเจริญ', 'Nong Khaem': 'หนองแขม', 'Rat Burana': 'ราษฎร์บูรณะ', 'Bang Phlat': 'บางพลัด',
    'Din Daeng': 'ดินแดง', 'Bueng Kum': 'บึงกุ่ม', 'Sathon': 'สาทร', 'Bang Sue': 'บางซื่อ', 'Chatuchak': 'จตุจักร',
    'Bang Kho Laem': 'บางคอแหลม', 'Prawet': 'ประเวศ', 'Khlong Toei': 'คลองเตย', 'Suan Luang': 'สวนหลวง',
    'Chom Thong': 'จอมทอง', 'Don Mueang': 'ดอนเมือง', 'Ratchathewi': 'ราชเทวี', 'Lat Phrao': 'ลาดพร้าว',
    'Watthana': 'วัฒนา', 'Bang Khae': 'บางแค', 'Lak Si': 'หลักสี่', 'Sai Mai': 'สายไหม', 'Khan Na Yao': 'คันนายาว',
    'Saphan Sung': 'สะพานสูง', 'Wang Thonglang': 'วังทองหลาง', 'Khlong Sam Wa': 'คลองสามวา', 'Bang Na': 'บางนา',
    'Thawi Watthana': 'ทวีวัฒนา', 'Thung Khru': 'ทุ่งครุ', 'Bang Bon': 'บางบอน', 'Mueang Nonthaburi': 'เมืองนนทบุรี',
    'Pak Kret': 'ปากเกร็ด', 'Mueang Samut Prakan': 'เมืองสมุทรปราการ', 'Phra Pradaeng': 'พระประแดง',
    'Bang Phli': 'บางพลี', 'Mueang Pathum Thani': 'เมืองปทุมธานี', 'Thanyaburi (Rangsit)': 'ธัญบุรี (รังสิต)',
    'Lam Luk Ka': 'ลำลูกกา',
}


def load_thresholds():
    import yaml
    t = (yaml.safe_load(THRESHOLDS.read_text()) or {}) if THRESHOLDS.exists() else {}
    bins = t.get('cctv_depth_proxy_bins_m') or {}
    return dict(watch=float(t.get('wet_threshold_m', 0.10)), warning=float((bins.get('FLOODING') or [0.15])[0]),
                severe=float((bins.get('SEVERE_FLOODING') or [0.30])[0]))


def km_between(lat1, lon1, lat2, lon2):
    return math.hypot((lat1 - lat2) * 110.574, (lon1 - lon2) * 111.320 * math.cos(math.radians((lat1 + lat2) / 2)))


def ict(ts):
    return ts.astimezone(ICT).strftime('%Y-%m-%d %H:%M')


# ------------------------------------------------------------------------------------------- weather
def condition(rate_mmh, gust_kmh, rh, hod):
    if rate_mmh >= 10 and gust_kmh >= 30: return 'Thunderstorm'
    if rate_mmh >= 7.6: return 'Heavy rain'
    if rate_mmh >= 2.5: return 'Moderate rain'
    if rate_mmh >= 0.5: return 'Light rain'
    return 'Overcast' if rh >= 88 else 'Partly cloudy' if 6 <= hod < 18 else 'Clear'


COND_RANK = ['Clear', 'Partly cloudy', 'Overcast', 'Light rain', 'Moderate rain', 'Heavy rain', 'Thunderstorm']


def synth_weather(preset='heavy', seed=1, now=None):
    """Synthetic 15-min weather for Bangkok: PAST_H hours before now (the "observed" part) and AHEAD_H hours ahead.
    Rain comes as convective cells (afternoon/evening, as in October) plus one organised event per preset."""
    if preset not in PRESETS:
        raise ValueError(f'unknown weather preset {preset!r}')
    now = (now or datetime.now(ICT)).astimezone(ICT)
    t_now = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
    start = t_now - timedelta(hours=PAST_H); now_idx = PAST_H * 4; T = (PAST_H + AHEAD_H) * 4 + 1
    rng = np.random.default_rng(seed); u = rng.uniform
    times = [start + timedelta(minutes=15 * k) for k in range(T)]
    hod = np.array([t.hour + t.minute / 60 for t in times])
    midnight = t_now.replace(hour=0, minute=0)
    at = lambda day, hour: int(round((midnight + timedelta(days=day, hours=hour) - start).total_seconds() / 900))
    rain = np.zeros(T)

    def cell(i0, total, dur_h, sharp=0.15):
        n = max(2, int(round(dur_h * 4))); i = np.arange(n); pk = u(0.3, 0.5) * (n - 1)
        w = np.exp(-np.abs(i - pk) / max(sharp * n, 0.6)) * rng.lognormal(0, 0.25, n)
        for k, v in zip(range(i0 - int(pk), i0 - int(pk) + n), total * w / w.sum()):
            if 0 <= k < T:
                rain[k] += v

    aft = lambda: u(14.5, 19.5)
    if preset == 'showers':
        cell(at(-1, aft()), u(6, 18), u(1.5, 3))
        for d, p in ((0, .7), (1, .8), (2, .6)):
            if u() < p:
                cell(at(d, aft()), u(12, 35), u(1.5, 3.5))
    elif preset == 'heavy':
        cell(at(-1, aft()), u(8, 20), u(1.5, 3)); cell(at(0, aft()), u(10, 25), u(1.5, 3))
        cell(at(1, u(17, 20)), u(95, 130), u(5, 7), 0.12)
        cell(at(2, aft()), u(15, 30), u(2, 3))
    elif preset == 'ongoing':
        cell(now_idx - int(u(5, 8) * 4), u(90, 120), u(6, 8))
        cell(now_idx + int(u(1, 3) * 4), u(15, 30), u(2, 4))
        cell(at(1, aft()), u(10, 25), u(2, 3)); cell(at(2, aft()), u(10, 25), u(2, 3))
    else:  # extreme
        cell(at(-1, aft()), u(15, 30), u(2, 3))
        base = at(0, u(20, 23))
        cell(base, u(110, 140), u(10, 12), 0.2); cell(base + int(u(14, 18) * 4), u(80, 110), u(8, 10), 0.2)
        cell(at(2, aft()), u(10, 25), u(2, 3))
    for _ in range(200):   # keep bursts inside the training range by spreading the excess to the neighbouring steps
        ex = np.maximum(rain - PEAK_CAP, 0)
        if ex.max() < 1e-6:
            break
        rain -= ex; rain[1:] += ex[:-1] / 2; rain[:-1] += ex[1:] / 2
    rain = np.round(rain, 3)

    rate = rain * 4                                                   # mm/h
    k = np.exp(-np.arange(16) / 6.0); wetf = 1 - np.exp(-np.convolve(rate, k / k.sum())[:T] / 5)   # 0 dry .. 1 heavy rain
    dix = np.array([(t.date() - start.date()).days for t in times]); dayoff = rng.normal(0, 0.6, dix.max() + 1)
    diurnal = np.sin(2 * np.pi * (hod - 9) / 24)
    temp = 29.4 + 3.4 * diurnal + dayoff[dix] - 4.5 * wetf + rng.normal(0, .15, T)
    rh = np.clip(77 - 14 * diurnal + 20 * wetf + rng.normal(0, 1, T), 45, 99)
    wind = np.clip(8 + 5 * np.clip(np.sin(2 * np.pi * (hod - 10) / 24), 0, None) + 24 * wetf + rng.normal(0, 1.2, T), 1, None)
    gust = wind * (1.35 + 0.5 * wetf)
    wdir = (225 + 20 * np.sin(2 * np.pi * hod / 24) + 40 * wetf + rng.normal(0, 8, T)) % 360
    storm = np.convolve(rate, np.ones(48) / 48, 'same')
    pressure = 1008.6 + 1.0 * np.cos(4 * np.pi * (hod - 10) / 24) - 0.35 * storm + rng.normal(0, .08, T)
    r1 = lambda a, n=1: np.round(a, n).tolist()
    return dict(times=[ict(t) for t in times], start=ict(start), now_idx=now_idx, T=T, rain=rain.tolist(), temp=r1(temp), rh=r1(rh, 0),
                wind=r1(wind), gust=r1(gust), wdir=r1(wdir, 0), pressure=r1(pressure),
                source=dict(kind='demo', preset=preset, seed=int(seed), reason='scenario'))


def complete_weather(w, high_tide_peak_shift_h=0.0):
    """Adds what the model and the page need on top of the measured/forecast series: weather condition per step, the tide
    (assumed: high water at the rain peak, the one regime the model was trained on) and the 'now' summary."""
    rain = np.asarray(w['rain'], float); T = len(rain); now = w['now_idx']
    times = [datetime.fromisoformat(t) for t in w['times']]
    rate1h = np.convolve(rain * 4, np.ones(4) / 4)[:T]
    w['cond'] = [condition(rate1h[i], w['gust'][i], w['rh'][i], times[i].hour + times[i].minute / 60) for i in range(T)]
    peak = int(np.argmax(rain[now:])) + now if rain[now:].max() > 0 else now + 4 * 12
    w['tide'] = np.round(fs.synth_tide(T, peak, 1.0, high_tide_peak_shift_h), 3).tolist()
    i = now
    w['current'] = dict(time=w['times'][i], temp=w['temp'][i], rh=int(w['rh'][i]), wind=w['wind'][i], gust=w['gust'][i], wdir=int(w['wdir'][i]),
                        pressure=w['pressure'][i], rain_1h=round(float(rain[max(0, i - 3):i + 1].sum()), 1),
                        rain_24h=round(float(rain[:i + 1].sum()), 1), tide=w['tide'][i], cond=w['cond'][i])
    steps = lambda h: slice(now + 1, now + 1 + 4 * h)
    mm_h = rate1h[now:]
    k = int(np.argmax(mm_h))
    w['rain_summary'] = dict(next6h=round(float(rain[steps(6)].sum()), 1), next24h=round(float(rain[steps(24)].sum()), 1),
                             next72h=round(float(rain[now + 1:].sum()), 1), peak_mm_h=round(float(mm_h[k]), 1), peak_time=w['times'][now + k],
                             peak_cond=w['cond'][now + k], past24h=round(float(rain[:now + 1].sum()), 1))
    return w


# ------------------------------------------------------------------------------------------------ CCTV database
def _num(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _bool(v):
    return None if v is None or str(v).strip() == '' or str(v).lower() == 'nan' else str(v).strip().lower() in ('true', '1', 'yes')


def _parse_utc(row):
    s = str(row.get('ingested_ts_utc') or '').strip()
    if s and s.lower() != 'nan':
        return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(timezone.utc)
    d, t = row.get('ingested_date_ict'), row.get('ingested_time_ict')
    if d and t:
        return datetime.fromisoformat(f'{d} {t}').replace(tzinfo=ICT).astimezone(timezone.utc)
    raise ValueError('needs ingested_ts_utc, or ingested_date_ict + ingested_time_ict')


class CctvDb:
    """CCTV readings from the CSV database and, if present, the cctv/ classifier pipeline output. Reloads on change."""

    def __init__(s, dash):
        s.dash = dash; s.lock = threading.RLock(); s.sig = None; s.version = 0; s.readings = []; s.loaded = None; s.notes = []

    @staticmethod
    def _sig():
        return tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in (CCTV_CSV, CCTV_PIPELINE))

    def refresh(s):
        sig = s._sig()
        if sig == s.sig:
            return
        with s.lock:
            notes = []; csv_rows = s._read_csv(notes); pipe_rows = s._read_pipeline(notes)
            # a frame the classifier pipeline has scored is the same frame its CSV export lists: keep the pipeline row
            # (it carries the class probabilities); rows entered by hand or from other models stay.
            have = {r['cam_id'] for r in pipe_rows}
            keep = [r for r in csv_rows if not (r['cam_id'] in have and str(r['model_version']).lower().startswith('clip'))]
            if len(keep) != len(csv_rows):
                notes.append(dict(code='pipeline_replaced', n=len(csv_rows) - len(keep)))
            s.readings = s._clean(keep + pipe_rows); s.sig = sig; s.version += 1; s.notes = notes
            s.loaded = datetime.now(ICT).strftime('%Y-%m-%d %H:%M:%S')

    def _read_csv(s, notes):
        import pandas as pd
        if not CCTV_CSV.exists():
            notes.append(dict(code='csv_missing', name=CCTV_CSV.name)); return []
        out = []
        for i, row in pd.read_csv(CCTV_CSV, dtype=str, keep_default_na=False).iterrows():
            row = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            try:
                ts = _parse_utc(row)
            except Exception as e:
                notes.append(dict(code='csv_row', row=i + 2, why=str(e))); continue
            out.append(dict(cam_id=row.get('cam_id') or f'row{i + 2}', source='CSV', ts=ts,
                            capture_known=bool(_bool(row.get('real_capture_datetime_known'))),
                            lat=_num(row.get('lat')), lon=_num(row.get('lon')), loc_method=row.get('location_method') or '',
                            cls=(row.get('predicted_class') or '').upper(), depth=_num(row.get('estimated_water_depth_m')),
                            conf=_num(row.get('confidence_score')), submerged=_bool(row.get('is_submerged')),
                            wpct=_num(row.get('water_pixel_pct')), quality=row.get('quality_flag') or 'OK',
                            model_version=row.get('model_version') or '', notes=row.get('notes') or ''))
        return out

    @staticmethod
    def _registry():
        reg = {}
        for p in REGISTRY_FILES:
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding='utf-8'))
            for f in (data.get('features', []) if isinstance(data, dict) else data):
                pr = f.get('properties', f)
                reg.setdefault(pr['cam_id'], dict(lat=pr.get('lat'), lon=pr.get('lon'), loc_method=pr.get('loc_method') or '',
                                                  is_mock=bool(pr.get('is_mock'))))
        return reg

    def _read_pipeline(s, notes):
        if not CCTV_PIPELINE.exists():
            return []
        try:
            import pandas as pd
            df = pd.read_parquet(CCTV_PIPELINE)
        except Exception as e:
            notes.append(dict(code='pipeline_unreadable', name=CCTV_PIPELINE.name, why=str(e))); return []
        reg = s._registry(); out = []
        for _, r in df.iterrows():
            g = reg.get(r['cam_id'], {}); cls = r.get('class_smoothed') or r.get('class')
            probs = [r.get(c) for c in ('p_normal', 'p_waterlogging', 'p_flooding', 'p_severe')]
            out.append(dict(cam_id=r['cam_id'], source='CLIP pipeline', ts=datetime.fromisoformat(str(r['ts_utc']).replace('Z', '+00:00')).astimezone(timezone.utc),
                            capture_known=True, lat=_num(g.get('lat')), lon=_num(g.get('lon')),
                            loc_method=g.get('loc_method') or 'UNKNOWN [DATA GAP]', cls=str(cls).upper(), depth=_num(r.get('depth_proxy_m')),
                            conf=max((_num(p) or 0) for p in probs), submerged=_bool(r.get('is_submerged')), wpct=_num(r.get('water_pixel_pct')),
                            quality=r.get('quality_flag') or 'OK', model_version=r.get('model_version') or '',
                            probs={k: _num(r.get(f'p_{k}')) for k in ('normal', 'waterlogging', 'flooding', 'severe', 'unusable')},
                            notes='MOCK camera position' if g.get('is_mock') else ''))
        return out

    def _clean(s, rows):
        d = s.dash; th = d.th
        rows.sort(key=lambda r: r['ts'])
        seen = {}
        for r in rows:
            r['time_ict'] = ict(r['ts']); r['ts_utc'] = r.pop('ts').strftime('%Y-%m-%dT%H:%M:%SZ')
            r['level'] = CLASS_LEVEL.get(r['cls']); r['reasons'] = []
            m = re.search(r'DUPLICATE SOURCE IMAGE of ([A-Za-z0-9_-]+)', r['notes'] or '')
            r['dup_of'] = m.group(1) if m else None
            r['placeholder_location'] = 'PLACEHOLDER' in (r['loc_method'] or '').upper() or 'MOCK' in (r['loc_method'] or '').upper()
            if r['depth'] is None and r['level'] is not None:   # class only: use the middle of its depth band
                r['depth'] = {0: 0.0, 1: (th['watch'] + th['warning']) / 2, 2: (th['warning'] + th['severe']) / 2, 3: th['severe']}[r['level']]
            if r['level'] is None or r['quality'].upper() != 'OK':
                r['reasons'].append(dict(code='unusable', cls=r['cls'] or '?', quality=r['quality']))
            if r['lat'] is None or r['lon'] is None:
                r['reasons'].append(dict(code='no_location'))
            else:
                rc = d.cell_of(r['lat'], r['lon'])
                if rc is None:
                    r['reasons'].append(dict(code='outside'))
                else:
                    r['row'], r['col'] = rc
            if not r['reasons']:   # the same photo ingested under two cam_ids must not count twice
                sig = (r['cls'], r['depth'], r['conf'], r['wpct'])
                if sig in seen and seen[sig] != r['cam_id']:
                    r['reasons'].append(dict(code='same_image', of=seen[sig]))
                seen.setdefault(sig, r['cam_id'])
            if r['dup_of'] and r['reasons']:
                r['reasons'].append(dict(code='duplicate', of=r['dup_of']))
            r['used'] = not r['reasons']
            if r['used']:
                dk = [km_between(r['lat'], r['lon'], la, lo) for _, la, lo in DISTRICTS]
                j = int(np.argmin(dk)); r['district'] = DISTRICTS[j][0]; r['district_id'] = j; r['district_km'] = round(dk[j], 2)
        return rows

    def latest(s):
        """Newest usable reading of every camera."""
        out = {}
        for r in s.readings:
            if r['used'] and (r['cam_id'] not in out or r['ts_utc'] >= out[r['cam_id']]['ts_utc']):
                out[r['cam_id']] = r
        return list(out.values())

    def write_rows(s, new):
        """Merge rows (dicts with CSV_COLUMNS keys) into the CSV; same cam_id + ingested_ts_utc replaces the old row."""
        import pandas as pd
        with s.lock:
            old = pd.read_csv(CCTV_CSV, dtype=str, keep_default_na=False) if CCTV_CSV.exists() else pd.DataFrame(columns=CSV_COLUMNS)
            df = pd.concat([old, pd.DataFrame(new, dtype=str)], ignore_index=True).fillna('')
            df = df.drop_duplicates(subset=['cam_id', 'ingested_ts_utc'], keep='last')
            cols = CSV_COLUMNS + [c for c in df.columns if c not in CSV_COLUMNS]
            CCTV_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CCTV_CSV.with_suffix('.tmp'); df.reindex(columns=cols).to_csv(tmp, index=False, encoding='utf-8'); tmp.replace(CCTV_CSV)
        s.refresh()

    def import_csv(s, raw):
        import pandas as pd
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
        df.columns = [c.strip().lower() for c in df.columns]
        missing = [c for c in ('cam_id', 'predicted_class') if c not in df.columns]
        if missing:
            raise ValueError(f'CSV is missing column(s): {", ".join(missing)} (expected the cctv_image_details.csv layout)')
        rows, errors = [], []
        for i, r in df.iterrows():
            r = r.to_dict()
            try:
                ts = _parse_utc(r)
            except Exception as e:
                errors.append(f'row {i + 2}: {e}'); continue
            r['ingested_ts_utc'] = ts.strftime('%Y-%m-%dT%H:%M:%SZ')
            loc = ts.astimezone(ICT)
            r['ingested_date_ict'] = r.get('ingested_date_ict') or loc.strftime('%Y-%m-%d'); r['ingested_time_ict'] = r.get('ingested_time_ict') or loc.strftime('%H:%M:%S')
            rows.append(r)
        if rows:
            s.write_rows(rows)
        return dict(added=len(rows), errors=errors, version=s.version)

    def add_reading(s, spec):
        cam = re.sub(r'[^A-Za-z0-9_-]', '', str(spec.get('cam_id') or '')) or f"FIELD-{datetime.now(ICT):%H%M%S}"
        lat, lon = _num(spec.get('lat')), _num(spec.get('lon')); depth = _num(spec.get('depth_m'))
        if lat is None or lon is None:
            raise ValueError('enter the camera latitude and longitude')
        if s.dash.cell_of(lat, lon) is None:
            raise ValueError(f'{lat:.4f}, {lon:.4f} is outside the model domain')
        cls = (spec.get('cls') or '').upper()
        if cls not in CLASS_LEVEL:
            if depth is None:
                raise ValueError('enter a depth or pick a class')
            th = s.dash.th
            cls = 'SEVERE_FLOODING' if depth >= th['severe'] else 'FLOODING' if depth >= th['warning'] else 'WATERLOGGING' if depth >= 0.05 else 'NORMAL'
        now = datetime.now(timezone.utc); loc = now.astimezone(ICT)
        s.write_rows([dict(cam_id=cam, ingested_date_ict=loc.strftime('%Y-%m-%d'), ingested_time_ict=loc.strftime('%H:%M:%S'),
                           ingested_ts_utc=now.strftime('%Y-%m-%dT%H:%M:%SZ'), real_capture_datetime_known='True', lat=f'{lat:.6f}', lon=f'{lon:.6f}',
                           location_method='MANUAL_ENTRY', predicted_class=cls, estimated_water_depth_m='' if depth is None else f'{depth:.3f}',
                           confidence_score=f"{float(spec.get('confidence') or 0.8):.2f}", is_submerged=str(bool(spec.get('submerged'))),
                           water_pixel_pct='', quality_flag='OK', model_version='manual', notes=str(spec.get('notes') or '')[:200])])
        return dict(version=s.version)


# ------------------------------------------------------------------------------------------------ bundle encoding
def _pack_depth(dep):
    """(T,H,W) float16 metres -> whole centimetres, stored as differences between consecutive steps: 250 MB -> ~7 MB compressed.
    The rounding (<= 0.5 cm) is far below the model's own error (1.4 cm RMSE)."""
    cm = np.clip(np.rint(dep.astype('float32') * 100), 0, 65535).astype('int32')
    d = np.diff(cm, axis=0, prepend=cm[:1] * 0)
    return d.astype('int16') if (d.min() >= -32768 and d.max() <= 32767) else d


def _unpack_depth(d):
    out = np.empty(d.shape, np.float16)
    for r in range(0, d.shape[1], 64):            # row blocks keep the int32 temporaries small
        out[:, r:r + 64] = (np.cumsum(d[:, r:r + 64].astype('int32'), axis=0) / 100.0).astype(np.float16)
    return out


# ---------------------------------------------------------------------------------------------------- dashboard
class Dashboard:
    def __init__(s, app):
        from pyproj import Transformer
        s.app = app; s.S = app.S; s.mask = app.mask; s.H, s.W = s.mask.shape
        s.xs, s.ys = s.S['x'], s.S['y']; s.dx, s.dy = s.xs[1] - s.xs[0], s.ys[1] - s.ys[0]
        s.to_utm = Transformer.from_crs('EPSG:4326', 'EPSG:32647', always_xy=True)
        s.to_ll = Transformer.from_crs('EPSG:32647', 'EPSG:4326', always_xy=True)
        s.th = load_thresholds()
        s._tl = threading.local(); s._fc = None; s.slots = {}; s._lazy = {}; s._hot = {}; s.wb_cache = OrderedDict(); s.fc_lock = threading.Lock(); s.png_cache = OrderedDict(); s.terr_cache = OrderedDict()
        s.dem_fill = np.nan_to_num(np.asarray(s.S['raw']['dem_m'], dtype='float32'), nan=0.0)
        s._web_grid(); s._districts()
        from matplotlib import colormaps
        heat = colormaps['YlOrRd'](np.linspace(0.12, 1, 256))[:, :3] * 255
        s.heat_lut = fs.to_dev(heat); s.heat_css = fs.Renderer._css(colormaps['YlOrRd'])
        s.cctv = CctvDb(s); s.cctv.refresh()
        s.web = fs.WEB; s._bundle_created = None
        s.dry = None; s.dry_version = None; s.dry_baseline()
        s.gfs = weather_gfs.Gfs(fs.CACHE / 'gfs', (s.bounds[0][0], s.bounds[1][0], s.bounds[0][1], s.bounds[1][1]))
        s.mode = 'gfs'; s.stage = dict(code='idle'); s.feed_error = None
        if s.web:         # no model here: show whatever the worker last published, and pick up new bundles
            threading.Thread(target=s._watch_bundle, daemon=True).start()
        elif fs.MODE == 'full':
            threading.Thread(target=s._follow_noaa, daemon=True).start()

    @property
    def fc(s):
        """The forecast this request belongs to (the page sends `fc=<id>`), else the one currently on show."""
        return getattr(s._tl, 'fc', None) or s._fc

    @fc.setter
    def fc(s, v):
        s._fc = v

    @staticmethod
    def _park(fc):
        """Move a forecast's big tensors to CPU RAM: only the forecast on show needs to live on the 8 GB GPU."""
        if fs.DEV.type != 'cuda':
            return
        if fc is not None and not fc.get('parked'):
            for k in ('dep', 'keep', 'maxf'):
                fc[k] = fc[k].cpu()
            fc['parked'] = True

    @staticmethod
    def _unpark(fc):
        if fc is not None and fc.get('parked'):
            for k in ('dep', 'keep', 'maxf'):
                fc[k] = fc[k].to(fs.DEV)
            fc['parked'] = False

    def _activate(s, fc):
        """Show this forecast: bring it onto the GPU and move the others off it."""
        s._unpark(fc)
        s.fc = fc
        for o in list(s.slots.values()):
            if o is not fc:
                s._park(o)
        if fs.DEV.type == 'cuda':
            torch.cuda.empty_cache()

    def _follow_noaa(s):
        """Background: compute the first forecast, then check NOAA every REFRESH_S for a newer cycle (or a new hour)."""
        while True:
            try:
                s.forecast(refresh=True)              # keeps the live slot fresh even while a demo is on screen
                if 'demo' not in s.slots:             # warm the demo once (parked in CPU RAM), so the Demo button is instant
                    s.forecast(demo=DEMO_PRESET, refresh=True)
            except Exception as e:                       # noqa: BLE001
                print(f'dashboard: forecast refresh failed: {e}', flush=True)
            time.sleep(REFRESH_S)

    # ---------------------------------------------------------------- bundles (worker -> web)
    def export_bundle(s, dest=None):
        """Write the live and demo forecasts and the dry-weather baseline to one directory (compressed, ~tens of MB), replacing
        the previous bundle atomically. Yesterday's forecast is gone the moment today's is published."""
        dest = Path(dest or fs.BUNDLE_DIR); tmp = dest.with_name(dest.name + '.tmp'); old = dest.with_name(dest.name + '.old')
        shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
        man = dict(format=1, created=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), model_version=s.app.obs.db['active'], slots={})
        for slot, fc in s.slots.items():
            name = {'gfs': 'live', 'demo': 'demo'}.get(slot, slot)
            np.savez_compressed(tmp / f'{name}.npz', dep_cm_delta=_pack_depth(fc['dep'].cpu().numpy()), keep=fc['keep'].cpu().numpy(),
                                maxf=fc['maxf'].cpu().numpy(), stat=np.asarray(fc['stat']), frac=np.asarray(fc['frac']))
            (tmp / f'{name}.json').write_text(json.dumps(dict(key=list(fc['key']), id=fc['id'], out=fc['out'])), encoding='utf-8')
            man['slots'][slot] = dict(file=name, id=fc['id'], key=list(fc['key']), kind=fc['out']['source']['kind'])
        np.save(tmp / 'dry.npy', s.dry.cpu().numpy())
        (tmp / 'manifest.json').write_text(json.dumps(man, indent=1), encoding='utf-8')
        shutil.rmtree(old, ignore_errors=True)
        if dest.exists():
            dest.rename(old)
        tmp.rename(dest)
        shutil.rmtree(old, ignore_errors=True)
        return dest

    def import_bundle(s, src=None):
        """Load the bundle a worker published (no-op if it has not changed). Returns True when something new was loaded."""
        src = Path(src or fs.BUNDLE_DIR); mf = src / 'manifest.json'
        if not mf.exists():
            return False
        man = json.loads(mf.read_text(encoding='utf-8'))
        if man.get('created') == s._bundle_created:
            return False
        slots = {}; lazy = {}
        for slot, m in man['slots'].items():
            if s.web and slot != 'gfs':        # only the live forecast is resident; the demo is read from disk when someone asks for it
                lazy[slot] = (src, m)
            else:
                slots[slot] = s._load_slot(src, m)
        if (src / 'dry.npy').exists():
            s.dry = fs.to_dev(np.load(src / 'dry.npy')); s.dry_version = s.app.obs.db['active']
        with s.fc_lock:
            prev = s.fc['out']['source']['kind'] if s.fc else None
            s.slots = slots; s._lazy = lazy
            pick = slots.get('demo') if (s.mode == 'demo' and 'demo' in slots) else slots.get('gfs') or next(iter(slots.values()), None)
            s.fc = pick
            s.png_cache.clear(); s.wb_cache.clear(); s._hot.clear()
            s._bundle_created = man['created']; s.stage = dict(code='ready'); s.feed_error = None
        print(f"dashboard: loaded bundle {man['created']} ({', '.join(slots)}), model {man.get('model_version')}", flush=True)
        return True

    @staticmethod
    def _load_slot(src, m):
        z = np.load(src / f"{m['file']}.npz"); meta = json.loads((src / f"{m['file']}.json").read_text(encoding='utf-8'))
        dep = _unpack_depth(z['dep_cm_delta']) if 'dep_cm_delta' in z.files else z['dep']
        return dict(key=tuple(meta['key']), id=meta['id'], dep=torch.from_numpy(dep).to(fs.DEV), keep=torch.from_numpy(z['keep']).to(fs.DEV),
                    maxf=torch.from_numpy(z['maxf']).to(fs.DEV), stat=z['stat'], frac=z['frac'], w=meta['out'], out=meta['out'])

    def _watch_bundle(s):
        s._progress('wait')
        while True:
            try:
                s.import_bundle()
                d = s.slots.get('demo')                  # the demo is rarely used: free its ~370 MB after 10 idle minutes
                if d is not None and s.fc is not d and 'demo' in s._lazy and time.time() - d.get('used', 0) > 600:
                    with s.fc_lock:
                        s.slots.pop('demo', None)
                    s._hot.clear(); s.png_cache.clear()
                    import gc; gc.collect()
            except Exception as e:                       # noqa: BLE001  half-written or missing: try again next round
                print(f'dashboard: bundle not loaded: {e}', flush=True)
            time.sleep(30)

    def dry_baseline(s):
        """Highest dry-weather water level of every cell (rivers, canals, tidal coast) over a full synthetic tide cycle.
        Dashboard depths are measured above it, so only rain-driven flooding raises alerts. Cached per model version."""
        ver = s.app.obs.db['active']
        if s.dry is not None and s.dry_version == ver:
            return s.dry
        path = fs.CACHE / f'dash_dry_max_{ver}.npy'
        if path.exists():
            s.dry = fs.to_dev(np.load(path)); s.dry_version = ver; return s.dry
        if fs.WEB:      # no inference here: the worker's bundle carries it (import_bundle replaces this placeholder)
            bp = fs.BUNDLE_DIR / 'dry.npy'
            s.dry = fs.to_dev(np.load(bp)) if bp.exists() else torch.zeros((s.H, s.W), device=fs.DEV)
            s.dry_version = ver
            return s.dry
        print(f'dashboard: computing the dry-weather water level for model {ver} (once) ...', flush=True)
        sur = s.app.sur; T = 4 * 72 + 1; tide = fs.synth_tide(T, T // 2, 1.0, 0.0)
        G = torch.from_numpy((fs.forcing_features(np.zeros(T), tide) - sur.mu) / sur.sd).to(fs.DEV)[96::2]   # after 24 h spin-up, every 30 min
        mx = torch.zeros((s.H, s.W), device=fs.DEV)
        with torch.no_grad(), sur.lock:
            for a in range(0, len(G), 8):
                g = G[a:a + 8]
                with torch.autocast(**fs.AMP):
                    out = sur.model(sur.X.expand(len(g), -1, -1, -1), g)
                mx = torch.maximum(mx, (fs.from_target(out.float()[:, 0, :s.H, :s.W]) * sur.mask_t).amax(0))
        np.save(path, mx.cpu().numpy()); s.dry = mx; s.dry_version = ver
        return mx

    @staticmethod
    def _patches(wet):
        """(H,W) bool -> the cells that belong to a flooded patch of at least CLUSTER_MIN cells (8-neighbour connectivity)."""
        from scipy import ndimage as ndi
        lab, n = ndi.label(wet, structure=np.ones((3, 3), int))
        if n == 0:
            return wet
        sz = np.bincount(lab.ravel()); sz[0] = 0
        return (sz >= CLUSTER_MIN)[lab]

    def keep_mask(s, f):
        """f: (H,W) flood depth tensor -> bool tensor of cells that are part of a real flooded patch. The model, like ANUGA
        without drains, ponds water in every depression, which shows as thousands of isolated 150 m specks; those are not
        what a flood map should show, so only connected patches of >= CLUSTER_MIN cells are kept."""
        wet = ((f >= CLUSTER_THR) & s.app.mask_t).cpu().numpy()
        if not wet.any():
            return torch.zeros_like(f, dtype=torch.bool)
        return torch.from_numpy(s._patches(wet)).to(f.device)

    def excess(s, depth):
        """Flood water above the dry-weather level for one (H,W) depth tensor, specks removed."""
        f = (depth.float() - s.dry).clamp(min=0)
        return f * s.keep_mask(f)

    def ex_t(s, fc, t):
        """Flood depth shown on the map at forecast step t (uses the keep-mask computed once per forecast)."""
        return (fc['dep'][t].float() - s.dry).clamp(min=0) * fc['keep'][t]

    def series_at(s, fc, r, c):
        """Flood depth shown at cell (r, c) for every step: (T,) numpy."""
        v = (fc['dep'][:, r, c].float() - s.dry[r, c]).clamp(min=0) * fc['keep'][:, r, c]
        return v.cpu().numpy()

    # ---------------------------------------------------------------- geometry
    def cell_of(s, lat, lon):
        x, y = s.to_utm.transform(lon, lat)
        c, r = int(round((x - s.xs[0]) / s.dx)), int(round((y - s.ys[0]) / s.dy))
        return (r, c) if 0 <= r < s.H and 0 <= c < s.W and s.mask[r, c] else None

    def _grid(s, W):
        """Lookup from the pixels of a Web-Mercator image W px wide (what a map's image source stretches) to model cells.
        The image covers the model domain's lon/lat bounding box; every web pixel takes the value of the nearest cell."""
        x0, x1 = s.xs[0] - s.dx / 2, s.xs[-1] + s.dx / 2; y0, y1 = s.ys[0] - s.dy / 2, s.ys[-1] + s.dy / 2
        e = np.linspace(0, 1, 200)
        bx = np.r_[x0 + (x1 - x0) * e, np.full(200, x1), x1 - (x1 - x0) * e, np.full(200, x0)]
        by = np.r_[np.full(200, y0), y0 + (y1 - y0) * e, np.full(200, y1), y1 - (y1 - y0) * e]
        blon, blat = s.to_ll.transform(bx, by)
        lon0, lon1, lat0, lat1 = blon.min(), blon.max(), blat.min(), blat.max()
        my = lambda lat: np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
        H = int(round(W * (my(lat1) - my(lat0)) / (np.radians(lon1) - np.radians(lon0))))
        lon = lon0 + (np.arange(W) + .5) / W * (lon1 - lon0)
        lat = np.degrees(2 * np.arctan(np.exp(my(lat1) - (np.arange(H) + .5) / H * (my(lat1) - my(lat0)))) - np.pi / 2)
        r = np.empty((H, W), np.int32); c = np.empty((H, W), np.int32); ok = np.empty((H, W), bool)
        for a in range(0, H, 128):                      # in row blocks: the full-size float64 temporaries would be ~0.5 GB
            LON, LAT = np.meshgrid(lon, lat[a:a + 128])
            X, Y = s.to_utm.transform(LON, LAT)
            cc = np.round((X - s.xs[0]) / s.dx).astype(np.int32); rr = np.round((Y - s.ys[0]) / s.dy).astype(np.int32)
            k = (rr >= 0) & (rr < s.H) & (cc >= 0) & (cc < s.W)
            rr = np.clip(rr, 0, s.H - 1); cc = np.clip(cc, 0, s.W - 1)
            r[a:a + 128], c[a:a + 128], ok[a:a + 128] = rr, cc, k & s.mask[rr, cc]
        dev = fs.DEV
        # lat is one value per row and lon one per column: kept as (H,1) and (1,W) vectors, broadcast where needed
        g = SimpleNamespace(W=W, H=H, r=torch.from_numpy(r).to(dev), c=torch.from_numpy(c).to(dev), ok=torch.from_numpy(ok).to(dev),
                            lat=torch.from_numpy(lat.astype('float32'))[:, None].to(dev), lon=torch.from_numpy(lon.astype('float32'))[None, :].to(dev),
                            bounds=[[float(lat0), float(lon0)], [float(lat1), float(lon1)]])
        return g, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def _web_grid(s):
        s.grid, corners = s._grid(MAP_W)
        s.bounds = s.grid.bounds; s._hi = None; s._hi_lock = threading.Lock()
        s.outline = [[float(la), float(lo)] for lo, la in (s.to_ll.transform(x, y) for x, y in corners)]

    def grid_for(s, res):
        """res 'hi': the same image at MAP_W_HI px wide, so that at the highest zoom every 150 m model cell is a visible block."""
        if res != 'hi':
            return s.grid
        with s._hi_lock:
            if s._hi is None:
                s._hi = s._grid(MAP_W_HI)[0]
            return s._hi

    def _districts(s):
        """Cells within NEAR_KM of every district, padded into (L, K) index tensors, and a vulnerability index."""
        rad = int(math.ceil(NEAR_KM / 0.15)); off = [(a, b) for a in range(-rad, rad + 1) for b in range(-rad, rad + 1) if (a * a + b * b) * 0.0225 <= NEAR_KM ** 2]
        raw = s.S['raw']; cells, keep = [], []
        for i, (name, lat, lon) in enumerate(DISTRICTS):
            x, y = s.to_utm.transform(lon, lat); r0, c0 = int(round((y - s.ys[0]) / s.dy)), int(round((x - s.xs[0]) / s.dx))
            cs = [(r0 + a, c0 + b) for a, b in off if 0 <= r0 + a < s.H and 0 <= c0 + b < s.W and s.mask[r0 + a, c0 + b]]
            if len(cs) >= 5:
                cells.append(cs); keep.append(i)
        s.dist = [dict(id=j, name=DISTRICTS[i][0], name_th=DISTRICT_TH.get(DISTRICTS[i][0], DISTRICTS[i][0]), lat=DISTRICTS[i][1],
                       lon=DISTRICTS[i][2]) for j, i in enumerate(keep)]
        K = max(len(c) for c in cells); L = len(cells)
        R = np.zeros((L, K), int); C = np.zeros((L, K), int); V = np.zeros((L, K), bool)
        for j, cs in enumerate(cells):
            R[j, :len(cs)], C[j, :len(cs)] = zip(*cs); V[j, :len(cs)] = True
        s.d_r, s.d_c, s.d_ok = (torch.from_numpy(a).to(fs.DEV) for a in (R, C, V))
        dem = np.array([raw['dem_m'][R[j, V[j]], C[j, V[j]]].mean() for j in range(L)])
        cn = np.array([raw['curve_number'][R[j, V[j]], C[j, V[j]]].mean() for j in range(L)])
        coast = np.array([raw['dist_to_coast_km'][R[j, V[j]], C[j, V[j]]].mean() for j in range(L)])
        rank = lambda a: (np.argsort(np.argsort(a)) + 0.5) / len(a)
        vul = 0.5 * rank(-dem) + 0.3 * rank(cn) + 0.2 * rank(-coast)
        for j, d in enumerate(s.dist):
            d.update(dem=round(float(dem[j]), 2), cn=round(float(cn[j]), 1), coast_km=round(float(coast[j]), 1), vuln=round(float(vul[j]), 3),
                     vuln_label='High' if vul[j] >= 0.66 else 'Moderate' if vul[j] >= 0.33 else 'Low')

    # ---------------------------------------------------------------- forecast
    def _progress(s, code, done=0, total=0):
        s.stage = dict(code=code, done=done, total=total, since=time.time())

    def forecast(s, demo=None, seed=1, refresh=False):
        """The flood forecast the dashboard shows. Default: NOAA GFS weather for the current hour. A page request returns
        the one in memory; the background thread (refresh=True) asks NOAA for a newer cycle or hour and recomputes.
        demo=<preset> runs a synthetic storm instead (dashboard?demo=heavy)."""
        if demo and demo not in PRESETS:
            raise ValueError(f'unknown demo scenario {demo!r}')
        if s.web:
            name = 'demo' if demo else 'gfs'
            cur = s.slots.get(name)
            if cur is None and name in s._lazy:
                with s.fc_lock:
                    if name not in s.slots:
                        s.slots[name] = s._load_slot(*s._lazy[name])
                cur = s.slots[name]
            if cur is None:
                raise RuntimeError('No forecast published yet: the worker has not produced a bundle. Try again in a few minutes.')
            cur['used'] = time.time()
            if not refresh:
                s.mode = 'demo' if demo else 'gfs'; s.fc = cur
            return cur['out']
        slot = 'demo' if demo else 'gfs'              # the live and the demo forecast are kept side by side: switching is instant
        if not refresh:
            s.mode = slot                              # a page chose it; the background refresh never changes what is shown
        cur = s.slots.get(slot)
        if demo and cur is not None and cur['key'][:3] == ('demo', demo, int(seed)):
            if s.mode == slot and s.fc is not cur:
                s._activate(cur)
            return cur['out']
        if not demo and not refresh and cur is not None and cur['key'][0] == 'gfs':
            if s.mode == slot and s.fc is not cur:
                s._activate(cur)
            return cur['out']
        with s.fc_lock:
            if demo:
                w = synth_weather(demo, int(seed)); key = ('demo', demo, int(seed), w['start'])
            else:
                try:
                    s._progress('fetch')
                    w = s.gfs.weather(progress=lambda d, n: s._progress('fetch', d, n))
                    src = w['source']; key = ('gfs', src['cycle'], w['times'][w['now_idx']])
                    s.feed_error = None
                    s.gfs.prune(keep_hours=int(os.environ.get('FLOOD_KEEP_HOURS', '36')))
                except Exception as e:                   # noqa: BLE001
                    s.feed_error = f'{type(e).__name__}: {e}'
                    print(f'dashboard: NOAA GFS unavailable: {e}', flush=True)
                    if cur is not None:                  # keep the forecast we have, and say that it is not fresh
                        s.stage = dict(code='ready'); cur['out']['source'] = dict(cur['out']['source'], error=s.feed_error)
                        if s.mode == slot and s.fc is not cur:
                            s._activate(cur)
                        return cur['out']
                    w = synth_weather('showers', 1); w['source']['reason'] = 'noaa_unreachable'; key = ('demo', 'showers', 1, w['start'])
            if cur is not None and cur['key'] == key:
                s.stage = dict(code='ready')
                if s.mode == slot and s.fc is not cur:
                    s._activate(cur)
                return cur['out']
            w = complete_weather(w)
            s._progress('model')
            rain, tide = np.asarray(w['rain']), np.asarray(w['tide'])
            if fs.DEV.type == 'cuda':
                torch.cuda.empty_cache()                 # hand cached blocks back before the big allocation
            t0 = time.time(); dep, spd = s.app.sur.predict(rain, tide); del spd
            if fs.DEV.type == 'cuda':
                torch.cuda.synchronize()
            secs = time.time() - t0; T = len(rain); now = w['now_idx']; m = s.app.mask_t
            st, fr, a15, a50, keeps = [], [], [], [], []; mx = None
            with torch.no_grad():
                for a in range(0, T, 48):
                    raw = (dep[a:a + 48].float() - s.dry).clamp(min=0)     # (n, H, W)
                    kp = torch.stack([s.keep_mask(x) for x in raw]); keeps.append(kp)
                    ex = raw * kp
                    if a + len(ex) > now:                                   # peak over the forecast = peak of what is drawn
                        part = ex[max(now - a, 0):].amax(0); mx = part if mx is None else torch.maximum(mx, part)
                    g = ex[:, s.d_r, s.d_c]
                    st.append(torch.nanquantile(torch.where(s.d_ok, g, torch.nan), STAT_Q, dim=2))
                    fr.append(((g >= s.th['warning'] - fs.EPS) & s.d_ok).sum(2) / s.d_ok.sum(1))
                    dm = ex[:, m]
                    a15.append((dm >= fs.THR - fs.EPS).sum(1)); a50.append((dm >= 0.5 - fs.EPS).sum(1))
                    del raw, ex, g, dm
                keep = torch.cat(keeps); maxf = mx
            st = torch.cat(st).cpu().numpy(); fr = torch.cat(fr).cpu().numpy()
            a15 = (torch.cat(a15).double() * fs.CELL_KM2).cpu().numpy(); a50 = (torch.cat(a50).double() * fs.CELL_KM2).cpu().numpy()
            tr = s.app.train_range; warn = []
            if rain.sum() > tr['total'] * 1.05: warn.append(dict(code='total', a=round(float(rain.sum()), 1), b=round(float(tr['total']), 1)))
            if rain.max() > tr['peak'] * 1.05: warn.append(dict(code='peak', a=round(float(rain.max()), 1), b=round(float(tr['peak']), 1)))
            lo = s.weakest_trained_mm_h(); hr = float(np.convolve(rain[now:], np.ones(4), 'valid').max()) if len(rain[now:]) >= 4 else 0.0
            if hr < 0.5 * lo:    # the forecast is far weaker than any event the model has seen: its output is an extrapolation
                warn.append(dict(code='light', a=round(hr, 1), b=round(lo, 1)))
            fid = f"{key[0]}-{int(time.time())}"
            pk = now + int(np.argmax(a15[now:]))
            out = dict(w, id=fid, predict_seconds=round(secs, 1), area_km2=np.round(a15, 2).tolist(), area05_km2=np.round(a50, 2).tolist(),
                       warnings=warn, summary=dict(peak_area=round(float(a15[now:].max()), 1), peak_area05=round(float(a50[now:].max()), 1),
                                                   peak_time=w['times'][pk], peak_idx=pk, rain_ahead=round(float(rain[now:].sum()), 1),
                                                   max_depth_p99=round(torch.quantile(maxf[m], 0.99).item(), 2)))
            out['source'] = dict(w['source'], error=s.feed_error)
            new = dict(key=key, id=fid, dep=dep, keep=keep, maxf=maxf, stat=st, frac=fr, w=w, out=out)
            old = s.slots.get(slot)
            s.slots[slot] = new
            if s.mode == slot or s.fc is None:
                s._activate(new)                       # on screen: on the GPU, every other forecast moves to CPU RAM
            else:
                s._park(new)
            del old                                    # the replaced forecast of this slot is freed here
            s.png_cache.clear()
            if fs.DEV.type == 'cuda':
                torch.cuda.empty_cache()
                print(f'dashboard: forecast {fid} ready: predict {secs:.0f} s, total {time.time() - t0:.0f} s, '
                      f'GPU {torch.cuda.memory_allocated() / 2**30:.2f} GiB in use, {torch.cuda.memory_reserved() / 2**30:.2f} GiB reserved', flush=True)
            s.stage = dict(code='ready')
            return out

    def weakest_trained_mm_h(s):
        """Strongest hour of rain (mm/h) in the weakest training event: below this the model has no experience."""
        if getattr(s, '_weak', None) is None:
            hs = [float(np.convolve(np.asarray(s.app.index[k]['rain']), np.ones(4), 'valid').max()) for k in s.app.sur.meta['train_ids']]
            s._weak = min(hs) if hs else 0.0
        return s._weak

    def _need_fc(s):
        fc = s.fc
        if fc is None:
            raise KeyError('no forecast yet: load the dashboard (or POST /api/dash/forecast) first')
        return fc

    def model_at(s, fc, r, c, t):
        """Flood depth the map shows at (r, c) at step t: the deepest of the 3 x 3 cells around it."""
        a, b = max(r - 1, 0), max(c - 1, 0)
        ex = (fc['dep'][t, a:r + 2, b:c + 2].float() - s.dry[a:r + 2, b:c + 2]).clamp(min=0) * fc['keep'][t, a:r + 2, b:c + 2]
        return float(ex.max().item())

    def step_of(s, fc, time_ict):
        t0 = datetime.fromisoformat(fc['w']['times'][0]); k = int(round((datetime.fromisoformat(time_ict) - t0).total_seconds() / 900))
        return k if 0 <= k < fc['w']['T'] else None

    # ---------------------------------------------------------------- map overlays (PNG, Web Mercator)
    def overlay(s, kind, t=None, thr=fs.THR, sigma_km=1.5, res='lo'):
        s.cctv.refresh(); fc = s.fc; g = s.grid_for(res)
        key = (fc['id'] if fc else None, kind, t, round(thr, 3), round(sigma_km, 2), s.cctv.version, g.W)
        if key in s.png_cache:
            s.png_cache.move_to_end(key); return s.png_cache[key]
        with torch.no_grad():
            img = torch.zeros(g.r.shape + (4,), device=fs.DEV)
            if kind in ('depth', 'max', 'fused'):
                fc = s._need_fc(); t = int(np.clip(fc['w']['now_idx'] if t is None else t, 0, fc['w']['T'] - 1))
                field = fc['maxf'] if kind == 'max' else s.ex_t(fc, t)
                v = field[g.r, g.c]
                if kind == 'fused':
                    corr, _ = s._cctv_field(sigma_km, g, fc, t)
                    if corr is not None:
                        v = (v + corr).clamp(min=0)
                s._paint(img, v, g.ok & (v >= thr - fs.EPS), s.app.R.lut['depth'],
                         (torch.log(v.clamp(min=1e-3) / fs.THR) / math.log(3.0 / fs.THR)).clamp(0, 1))
            elif kind == 'cctv':
                dep, peak = s._cctv_field(sigma_km, g)
                if dep is not None:
                    show = peak >= 0.03
                    s._paint(img, dep, show, s.heat_lut, (dep / 1.2).clamp(0, 1), alpha=((peak - 0.03) / 0.97).clamp(0, 1) ** 0.5 * 0.85)
            else:
                raise KeyError(f'unknown overlay {kind!r}')
            png = fs.Renderer._encode(img)
        s.png_cache[key] = png
        while len(s.png_cache) > 160:
            s.png_cache.popitem(last=False)
        return png

    @staticmethod
    def _paint(img, v, show, lut, t, alpha=None):
        rgb = lut[(t * 255).round().long()]
        a = (85 + 145 * t) if alpha is None else alpha * 255   # shallow water lets the city show through
        img[..., :3] = torch.where(show[..., None], rgb, img[..., :3])
        img[..., 3] = torch.where(show, a, img[..., 3])

    def _cctv_field(s, sigma_km, g, fc=None, t=None):
        """Gaussian-kernel field of the newest reading of each camera on the web grid g.
        Without fc: (interpolated depth, kernel peak). With fc: (correction to add to the model depth at step t, kernel sum)."""
        cams = s.cctv.latest()
        if not cams:
            return None, None
        shape = g.r.shape
        num = torch.zeros(shape, device=fs.DEV); den = torch.zeros(shape, device=fs.DEV); peak = torch.zeros(shape, device=fs.DEV)
        kx = 111.320 * torch.cos(torch.deg2rad(g.lat))
        for c in cams:
            k = torch.exp(-(((g.lat - c['lat']) * 110.574) ** 2 + ((g.lon - c['lon']) * kx) ** 2) / (2 * sigma_km ** 2))
            if fc is None:
                w = k * max(c['conf'] or 0.5, 0.2); num += w * c['depth']; den += w; peak = torch.maximum(peak, k)
            else:
                num += k * (c['depth'] - s.model_at(fc, c['row'], c['col'], t)); den += k
        if fc is None:
            return num / den.clamp(min=1e-12), peak
        return num / den.clamp(min=1.0), den

    # ---------------------------------------------------------------- alerts
    def level_of(s, depth):
        th = s.th
        return 3 if depth >= th['severe'] else 2 if depth >= th['warning'] else 1 if depth >= th['watch'] else 0

    def hotspots(s, fc, field, key):
        """Deepest cell inside every district's disc: (lat, lon, depth) arrays. This is where a marker belongs."""
        if key in s._hot:
            return s._hot[key]
        with torch.no_grad():
            g = torch.where(s.d_ok, field[s.d_r, s.d_c], torch.full_like(s.d_r, -1, dtype=torch.float32))
            val, idx = g.max(1)
            rr = s.d_r.gather(1, idx[:, None])[:, 0].cpu().numpy(); cc = s.d_c.gather(1, idx[:, None])[:, 0].cpu().numpy()
        lon, lat = s.to_ll.transform(s.xs[cc], s.ys[rr])
        out = (np.round(lat, 5), np.round(lon, 5), val.cpu().numpy())
        if len(s._hot) > 64:
            s._hot.clear()
        s._hot[key] = out
        return out

    def alerts(s, phase='before', t=None):
        s.cctv.refresh(); fc = s.fc; th = s.th
        cams = s.cctv.latest() if phase == 'during' else []
        now = fc['w']['now_idx'] if fc else None; times = fc['w']['times'] if fc else None
        hot = None
        if fc and phase == 'during':
            t = int(np.clip(now if t is None else t, 0, fc['w']['T'] - 1))
        if fc:
            hot = s.hotspots(fc, fc['maxf'] if phase == 'before' else s.ex_t(fc, t), (fc['id'], phase, t if phase == 'during' else None))
        out = []
        for d in s.dist:
            a = dict(d, depth=None, model_level=0, cctv=[]); i = d['id']
            if fc is not None:
                ser = fc['stat'][:, i]
                if phase == 'before':
                    fut = ser[now:]; k = int(np.argmax(fut)); a['depth'] = round(float(fut[k]), 3); a['model_level'] = s.level_of(fut[k])
                    a['flooded_pct'] = round(100 * float(fc['frac'][now:, i].max()))
                    on = np.nonzero(fut >= th['watch'])[0]
                    if len(on):
                        a.update(peak_time=times[now + k], onset_time=times[now + int(on[0])], hours_to_onset=round(float(on[0]) * 0.25, 2))
                else:
                    a['depth'] = round(float(ser[t]), 3); a['model_level'] = s.level_of(ser[t]); a['flooded_pct'] = round(100 * float(fc['frac'][t, i]))
                    nxt = float(ser[t:t + 25].max()); a.update(next6h=round(nxt, 3), outlook_level=s.level_of(nxt))
                if a['model_level'] and hot[2][i] >= th['watch']:
                    a.update(hot_lat=float(hot[0][i]), hot_lon=float(hot[1][i]), hot_depth=round(float(hot[2][i]), 3))
            for c in cams:
                dkm = km_between(d['lat'], d['lon'], c['lat'], c['lon'])
                if dkm <= CCTV_NEAR_KM or c['district_id'] == i:
                    a['cctv'].append(dict(cam_id=c['cam_id'], cls=c['cls'], level=c['level'], depth=c['depth'], conf=c['conf'], km=round(dkm, 2),
                                          submerged=c['submerged'], time=c['time_ict'], placeholder=c['placeholder_location'],
                                          lat=c['lat'], lon=c['lon']))
            a['cctv'].sort(key=lambda e: (-e['level'], e['km']))
            a['cctv_level'] = max([e['level'] for e in a['cctv']], default=0)
            a['level'] = max(a['model_level'], a['cctv_level'])
            if a['cctv_level'] > a['model_level'] and a['cctv']:   # camera evidence outranks the model: mark where the camera is
                e = a['cctv'][0]; a.update(hot_lat=e['lat'], hot_lon=e['lon'], hot_depth=e['depth'])
            a['source'] = ('cctv' if a['cctv_level'] > a['model_level'] else 'model+cctv' if a['cctv_level'] == a['model_level'] and a['level'] else
                           'model' if a['level'] else '')
            cdepth = max([e['depth'] or 0 for e in a['cctv'] if e['km'] <= CCTV_NEAR_KM], default=0)
            a['risk'] = round(max(a['depth'] or 0, cdepth if phase == 'during' else 0) * (0.6 + 0.8 * d['vuln']), 4)
            out.append(a)
        out.sort(key=lambda a: (-a['level'], -a['risk'], -a['vuln']))
        counts = {n: sum(a['level'] == k for a in out) for k, n in enumerate(LEVEL_NAMES)}   # keyed by the English level names
        feed = []
        if phase == 'during':
            for c in sorted(cams, key=lambda c: c['ts_utc'], reverse=True):
                feed.append(dict(time=c['time_ict'], level=c['level'], kind='cctv', cam_id=c['cam_id'], cls=c['cls'], depth=c['depth'],
                                 submerged=bool(c['submerged']), district=c['district'], district_th=DISTRICT_TH.get(c['district'], c['district'])))
            if fc:
                for a in out:
                    if a.get('outlook_level', 0) > a['model_level']:
                        k = int(np.argmax(fc['stat'][t:t + 25, a['id']] >= [0, th['watch'], th['warning'], th['severe']][a['outlook_level']]))
                        feed.append(dict(time=times[t + k], level=a['outlook_level'], kind='rising', district=a['name'], district_th=a['name_th'],
                                         next6h=a['next6h']))
        else:
            for a in out:
                if a['model_level'] and a.get('onset_time'):
                    feed.append(dict(time=a['onset_time'], level=a['model_level'], kind='onset', district=a['name'], district_th=a['name_th'],
                                     depth=a['depth'], peak_time=a['peak_time']))
            feed.sort(key=lambda f: f['time'])
        return dict(phase=phase, t=t, time=times[t] if fc and t is not None else None, alerts=out, counts=counts, feed=feed[:40],
                    cctv_version=s.cctv.version, forecast_id=fc['id'] if fc else None)

    # ---------------------------------------------------------------- JSON views
    def meta(s):
        rl = s.app.R.legend('depth')
        lat0, lon0 = s.bounds[0]; lat1, lon1 = s.bounds[1]
        return dict(bounds=s.bounds, outline=s.outline, center=[round((lon0 + lon1) / 2, 5), round((lat0 + lat1) / 2, 5)],
                    demos=list(PRESETS), thresholds=s.th, legends=dict(depth=rl, cctv=dict(cmap=s.heat_css, lo=0, hi=1.2, unit='m (CCTV visual estimate)')),
                    districts=list(s.dist), near_km=NEAR_KM, cctv_near_km=CCTV_NEAR_KM, level_names_en=LEVEL_NAMES,
                    model_version=s.app.obs.db['active'], grid=[s.H, s.W], cell_m=abs(float(s.dx)), map_px=dict(lo=s.grid.W, hi=MAP_W_HI),
                    horizon=dict(past_h=PAST_H, ahead_h=AHEAD_H), accuracy=s.app.metrics, patches=dict(min_cells=CLUSTER_MIN, thr=CLUSTER_THR),
                    device=torch.cuda.get_device_name(0) if fs.DEV.type == 'cuda' else 'CPU', now=datetime.now(ICT).strftime('%Y-%m-%d %H:%M'))

    def health(s):
        s.cctv.refresh(); fc = s.fc
        return dict(status='ok', model_version=s.app.obs.db['active'], device=torch.cuda.get_device_name(0) if fs.DEV.type == 'cuda' else 'CPU',
                    forecast_ready=fc is not None, forecast_id=fc['id'] if fc else None, forecast_source=fc['out']['source'] if fc else None,
                    stage=s.stage, feed_error=s.feed_error, cctv_version=s.cctv.version,
                    cctv_readings=len(s.cctv.readings), cameras_registered=len(s.camera_registry()), images=len(s._images()),
                    time=datetime.now(ICT).strftime('%Y-%m-%d %H:%M:%S'))

    # ---------------------------------------------------------------- camera registry and photos
    @staticmethod
    def _images():
        """Newest privacy-processed (downscaled, face/plate-blurred) frame of every camera that has one."""
        out = {}
        for cam in sorted(THUMBS.glob('*')) if THUMBS.exists() else []:
            if not cam.is_dir():
                continue
            files = sorted(cam.glob('*/*.jpg'))
            if files:
                raw = RAW / cam.name / files[-1].parent.name / files[-1].name
                out[cam.name] = dict(thumb=files[-1], full=raw if raw.exists() else files[-1])
        return out

    def camera_registry(s):
        """Every camera the project knows about (manual captures + the registry), with bilingual names."""
        reg = {}
        for p in REGISTRY_FILES:
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding='utf-8'))
            for f in (data.get('features', []) if isinstance(data, dict) else data):
                pr = dict(f.get('properties', f))
                if pr.get('lat') is None or pr.get('lon') is None:
                    g = f.get('geometry') or {}
                    if g.get('coordinates'):
                        pr['lon'], pr['lat'] = g['coordinates'][:2]
                reg.setdefault(pr['cam_id'], pr)
        return reg

    def cameras(s):
        s.cctv.refresh(); imgs = s._images(); latest = {r['cam_id']: r for r in s.cctv.latest()}
        feats = []
        for cam, pr in s.camera_registry().items():
            lat, lon = _num(pr.get('lat')), _num(pr.get('lon'))
            if lat is None or lon is None:
                continue
            r = latest.get(cam)
            nm = pr.get('name_en') or pr.get('name_th') or cam
            feats.append(dict(type='Feature', geometry=dict(type='Point', coordinates=[lon, lat]),
                              properties=dict(cam_id=cam, name=nm, name_en=pr.get('name_en'), name_th=pr.get('name_th'), source=pr.get('source') or ('MANUAL' if cam.startswith('MANUAL') else ''),
                                              road_name=pr.get('road_name'), heading_deg=pr.get('heading_deg'), loc_method=pr.get('loc_method'),
                                              is_mock=bool(pr.get('is_mock')), has_reading=r is not None, cls=r['cls'] if r else None,
                                              depth=r['depth'] if r else None, has_image=cam in imgs,
                                              in_domain=s.cell_of(lat, lon) is not None)))
        return dict(type='FeatureCollection', features=feats)

    def image_file(s, cam, full=False):
        im = s._images().get(re.sub(r'[^A-Za-z0-9_-]', '', cam))
        if im is None:
            raise KeyError('no image for this camera')
        return im['full' if full else 'thumb'].read_bytes()

    # ---------------------------------------------------------------- terrain, 3D flood and the cell under the pointer
    def terrain_tile(s, z, x, y):
        """Terrarium-encoded elevation tile (what MapLibre's raster-dem source reads) built from the model's own DEM, so the 3D
        ground and the flood depths always agree. Outside the model domain the ground is 0 m."""
        key = (z, x, y)
        if key in s.terr_cache:
            s.terr_cache.move_to_end(key); return s.terr_cache[key]
        from scipy.ndimage import map_coordinates
        from PIL import Image
        n = 2 ** z; px = (np.arange(256) + 0.5) / 256
        lon = (x + px) / n * 360 - 180; lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + px) / n))))
        LON, LAT = np.meshgrid(lon, lat); X, Y = s.to_utm.transform(LON, LAT)
        rr, cc = (Y - s.ys[0]) / s.dy, (X - s.xs[0]) / s.dx
        h = map_coordinates(s.dem_fill, [rr, cc], order=1, mode='nearest')
        inside = (rr >= -0.5) & (rr <= s.H - 0.5) & (cc >= -0.5) & (cc <= s.W - 0.5)
        h = np.where(inside, h, 0.0); v = np.clip(h + 32768.0, 0, 65535.99)
        rgb = np.stack([np.floor(v / 256), np.floor(v) % 256, np.floor((v - np.floor(v)) * 256)], -1).astype(np.uint8)
        buf = io.BytesIO(); Image.fromarray(rgb, 'RGB').save(buf, 'PNG', compress_level=1); png = buf.getvalue()
        s.terr_cache[key] = png
        while len(s.terr_cache) > TERRAIN_CACHE:
            s.terr_cache.popitem(last=False)
        return png

    def flood3d(s, kind='depth', t=None, thr=fs.THR, block=0, bbox=None):
        """Flooded cells as GeoJSON polygons (properties: d = flood depth in m) for the 3D extrusion layer. With bbox
        (west, south, east, north in degrees) only the cells in view are sent. Neighbouring cells are merged in blocks (deepest
        value kept) until at most MAX_3D_CELLS polygons remain, so zoomed in every 150 m cell is its own column."""
        fc = s._need_fc(); t = int(np.clip(fc['w']['now_idx'] if t is None else t, 0, fc['w']['T'] - 1))
        r0, r1, c0, c1 = 0, s.H, 0, s.W
        if bbox:
            w_, s_, e_, n_ = bbox
            X, Y = s.to_utm.transform([w_, e_, e_, w_], [s_, s_, n_, n_])
            cols, rows = (np.asarray(X) - s.xs[0]) / s.dx, (np.asarray(Y) - s.ys[0]) / s.dy
            c0, c1 = max(0, int(np.floor(cols.min())) - 2), min(s.W, int(np.ceil(cols.max())) + 3)
            r0, r1 = max(0, int(np.floor(rows.min())) - 2), min(s.H, int(np.ceil(rows.max())) + 3)
            if r1 <= r0 or c1 <= c0:
                return json.dumps(dict(type='FeatureCollection', features=[], block=1, n=0, t=t, kind=kind)).encode()
        key = ('3d', fc['id'], kind, t, round(thr, 3), block, r0, r1, c0, c1)
        if key in s.png_cache:
            s.png_cache.move_to_end(key); return s.png_cache[key]
        with torch.no_grad():
            f = (fc['maxf'] if kind == 'max' else s.ex_t(fc, t)).float()
            f = torch.where(s.app.mask_t, f, torch.zeros_like(f))[r0:r1, c0:c1].cpu().numpy()
        h, w = f.shape; b = max(1, int(block or 1))
        while True:
            Hc, Wc = -(-h // b), -(-w // b)
            pad = np.zeros((Hc * b, Wc * b), np.float32); pad[:h, :w] = f
            m = pad.reshape(Hc, b, Wc, b).max((1, 3))
            ii, jj = np.nonzero(m >= thr - fs.EPS)
            if len(ii) <= MAX_3D_CELLS or b >= 8:
                break
            b += 1
        # corners of block (i, j) in UTM, then WGS84
        x0 = s.xs[0] + (c0 + jj * b - 0.5) * s.dx; x1 = s.xs[0] + (c0 + (jj + 1) * b - 0.5) * s.dx
        y0 = s.ys[0] + (r0 + ii * b - 0.5) * s.dy; y1 = s.ys[0] + (r0 + (ii + 1) * b - 0.5) * s.dy
        xs_, ys_ = np.stack([x0, x1, x1, x0]), np.stack([y0, y0, y1, y1])
        lo, la = s.to_ll.transform(xs_, ys_)
        d = np.round(m[ii, jj], 3)
        feats = []
        for k in range(len(ii)):
            ring = [[round(float(lo[q, k]), 5), round(float(la[q, k]), 5)] for q in range(4)]; ring.append(ring[0])
            feats.append(dict(type='Feature', properties=dict(d=float(d[k])), geometry=dict(type='Polygon', coordinates=[ring])))
        out = json.dumps(dict(type='FeatureCollection', features=feats, block=b, cell_m=abs(float(s.dx)) * b, n=len(feats), t=t,
                              time=fc['w']['times'][t], kind=kind)).encode()
        s.png_cache[key] = out
        return out

    # ---------------------------------------------------------------- workbench maps (same web grid as the dashboard)
    def wb_frame(s, rid, layer, t, thr, obs, res='lo', clean=True):
        """Any workbench layer as a Web-Mercator PNG on a transparent background (what the workbench's MapLibre map stretches)."""
        key = ('wb', rid, layer, t, round(thr, 3), obs, res, bool(clean), s.app.obs.db['active'])
        if key in s.wb_cache:
            s.wb_cache.move_to_end(key); return s.wb_cache[key]
        g = s.grid_for(res)
        with torch.no_grad():
            n = s.app.frame(rid, layer, t, thr, obs, raw=True, clean=clean)           # (H,W,4) on the 150 m grid
            img = n[g.r, g.c].clone()
            img[..., 3] = torch.where(g.ok, img[..., 3], torch.zeros_like(img[..., 3]))
            png = fs.Renderer._encode(img)
        s.wb_cache[key] = png
        while len(s.wb_cache) > 120:
            s.wb_cache.popitem(last=False)
        return png

    def wb_sar(s, oid, what, res='lo'):
        """A Sentinel-1 observation layer (extent / depth / compare with the active model) as a Web-Mercator PNG."""
        what = {'extent': 'extent', 'depth': 'depth', 'compare': 'compare', 'sarext': 'extent', 'sardepth': 'depth', 'sarcmp': 'compare'}[what]
        key = ('sar', oid, what, res, s.app.obs.db['active'])
        if key in s.wb_cache:
            s.wb_cache.move_to_end(key); return s.wb_cache[key]
        g = s.grid_for(res)
        with torch.no_grad():
            n = s.app.obs.sar_png(oid, what, raw=True)
            img = n[g.r, g.c].clone()
            img[..., 3] = torch.where(g.ok, img[..., 3], torch.zeros_like(img[..., 3]))
            png = fs.Renderer._encode(img)
        s.wb_cache[key] = png
        return png

    def wb_cell(s, rid, lat, lon):
        """The 150 m cell under a lat/lon for a workbench run: its footprint and the whole depth series (surrogate / ANUGA)."""
        rc = s.cell_of(lat, lon)
        if rc is None:
            return dict(valid=False, lat=lat, lon=lon)
        r, c = rc
        out = s.app.point(rid, r, c)
        x0, x1 = s.xs[c] - s.dx / 2, s.xs[c] + s.dx / 2; y0, y1 = s.ys[r] - s.dy / 2, s.ys[r] + s.dy / 2
        lo, la = s.to_ll.transform([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0])
        cl, ca = s.to_ll.transform(s.xs[c], s.ys[r])
        out.update(ring=[[float(a), float(b)] for a, b in zip(lo, la)], lat=float(ca), lon=float(cl), size_m=abs(float(s.dx)))
        return out

    def cell(s, lat, lon, t=None):
        """What is under the pointer: the model cell (its footprint), ground, land cover, flood depth now and at the peak."""
        rc = s.cell_of(lat, lon)
        if rc is None:
            return dict(valid=False, lat=lat, lon=lon)
        r, c = rc; raw = s.S['raw']; fc = s.fc
        x0, x1 = s.xs[c] - s.dx / 2, s.xs[c] + s.dx / 2; y0, y1 = s.ys[r] - s.dy / 2, s.ys[r] + s.dy / 2
        lo, la = s.to_ll.transform([x0, x1, x1, x0, x0], [y0, y0, y1, y1, y0])
        cl, ca = s.to_ll.transform(s.xs[c], s.ys[r])
        out = dict(valid=True, row=r, col=c, lat=float(ca), lon=float(cl), size_m=abs(float(s.dx)),
                   ring=[[float(a), float(b)] for a, b in zip(lo, la)], dem=round(float(raw['dem_m'][r, c]), 2),
                   cn=round(float(raw['curve_number'][r, c]), 1), manning=round(float(raw['manning_n'][r, c]), 3),
                   coast_km=round(float(raw['dist_to_coast_km'][r, c]), 1), normal_water=round(float(s.dry[r, c]), 2))
        if fc is not None:
            t = int(np.clip(fc['w']['now_idx'] if t is None else t, 0, fc['w']['T'] - 1)); now = fc['w']['now_idx']
            ser = s.series_at(fc, r, c)
            out.update(t=t, time=fc['w']['times'][t], depth=round(float(ser[t]), 3), peak=round(float(ser[now:].max()), 3),
                       peak_time=fc['w']['times'][now + int(ser[now:].argmax())])
        return out

    def cctv_state(s):
        s.cctv.refresh(); fc = s.fc; rows = []; imgs = s._images(); reg = s.camera_registry()
        for r in sorted(s.cctv.readings, key=lambda r: r['ts_utc'], reverse=True):
            r = dict(r)
            g = reg.get(r['cam_id']) or {}
            r['name'] = g.get('name_en') or r['cam_id']; r['name_th'] = g.get('name_th') or r['name']
            r['has_image'] = r['cam_id'] in imgs
            if r.get('district'):
                r['district_th'] = DISTRICT_TH.get(r['district'], r['district'])
            if fc and r['used']:
                r['model_now'] = round(s.model_at(fc, r['row'], r['col'], fc['w']['now_idx']), 3)
                k = s.step_of(fc, r['time_ict'])
                r['model_at_reading'] = None if k is None else round(s.model_at(fc, r['row'], r['col'], k), 3)
            rows.append(r)
        used = [r for r in rows if r['used']]
        counts = {c: sum(r['cls'] == c for r in s.cctv.latest()) for c in CLASS_LEVEL}
        return dict(version=s.cctv.version, loaded=s.cctv.loaded, notes=s.cctv.notes, readings=rows, n_used=len(used),
                    n_cameras=len(s.cctv.latest()), n_excluded=len(rows) - len(used), counts=counts,
                    latest=max((r['time_ict'] for r in used), default=None),
                    files=[p.name for p in (CCTV_CSV, CCTV_PIPELINE) if p.exists()])

    def point(s, lat, lon):
        fc = s._need_fc(); rc = s.cell_of(lat, lon)
        if rc is None:
            return dict(lat=lat, lon=lon, valid=False)
        r, c = rc; raw = s.S['raw']
        d = s.series_at(fc, r, c)
        dk = [km_between(lat, lon, la, lo) for _, la, lo in DISTRICTS]; j = int(np.argmin(dk))
        return dict(lat=lat, lon=lon, valid=True, row=r, col=c, depth=np.round(d, 3).tolist(), dem=round(float(raw['dem_m'][r, c]), 2),
                    cn=round(float(raw['curve_number'][r, c]), 1), normal_water=round(float(s.dry[r, c]), 2),
                    near=DISTRICTS[j][0], near_th=DISTRICT_TH.get(DISTRICTS[j][0], DISTRICTS[j][0]), near_km=round(dk[j], 1))

    # ---------------------------------------------------------------- HTTP (called from flood_surrogate's handler)
    CT = {'.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml',
          '.json': 'application/json', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.map': 'application/json',
          '.woff2': 'font/woff2', '.ico': 'image/x-icon', '.html': 'text/html; charset=utf-8'}

    def _fc_args(s, src):
        """Forecast arguments from a query dict or a JSON body: only the hidden demo scenario can be chosen."""
        return dict(demo=src.get('demo') or None, seed=int(src.get('seed', 1) or 1))

    def get(s, path, q):
        """-> (body, content type, extra headers) or None when the path is not the dashboard's."""
        if path in ('/dashboard', '/dashboard.html'):
            return PAGE.read_bytes(), 'text/html; charset=utf-8', None
        s._tl.fc = None                      # a page names its forecast, so another tab switching live/demo cannot change its answers
        if q.get('fc'):
            for sl in list(s.slots.values()):
                if sl['id'] == q['fc'] and not sl.get('parked'):
                    s._tl.fc = sl
                    sl['used'] = time.time()
        if path.startswith('/static/'):
            p = (STATIC / path[len('/static/'):]).resolve()
            if STATIC.resolve() not in p.parents or not p.is_file():
                raise KeyError('not found')
            return p.read_bytes(), s.CT.get(p.suffix.lower(), 'application/octet-stream'), {'Cache-Control': 'no-cache'}
        if path == '/api/dash/health':
            return s.health(), 'application/json', None
        if path == '/api/dash/status':
            return dict(stage=s.stage, feed_error=s.feed_error, forecast_id=s.fc['id'] if s.fc else None), 'application/json', None
        if path == '/api/dash/meta':
            return s.meta(), 'application/json', None
        if path == '/api/dash/forecast':
            return s.forecast(**s._fc_args(q)), 'application/json', {'Cache-Control': 'public, max-age=20, s-maxage=60'} if s.web else None
        if path == '/api/dash/overlay':
            t = int(q['t']) if q.get('t') not in (None, '') else None
            png = s.overlay(q.get('kind', 'depth'), t, float(q.get('thr', fs.THR)), float(q.get('sigma', 1.5)), q.get('res', 'lo'))
            return png, 'image/png', {'Cache-Control': 'public, max-age=3600, s-maxage=86400'}   # the URL carries the forecast id
        if path == '/api/dash/flood3d':
            t = int(q['t']) if q.get('t') not in (None, '') else None
            bb = [float(v) for v in q['bbox'].split(',')] if q.get('bbox') else None
            return s.flood3d(q.get('kind', 'depth'), t, float(q.get('thr', fs.THR)), int(q.get('block', 0) or 0), bb), 'application/json', None
        m = re.fullmatch(r'/api/dash/terrain/(\d+)/(\d+)/(\d+)\.png', path)
        if m:
            z, x, y = map(int, m.groups())
            return s.terrain_tile(z, x, y), 'image/png', {'Cache-Control': 'public, max-age=86400, s-maxage=604800'}
        if path == '/api/dash/wb_frame':
            png = s.wb_frame(q.get('run', ''), q.get('layer', 'pred'), int(q.get('t', 0)), float(q.get('thr', fs.THR)), q.get('obs') or None,
                             q.get('res', 'lo'), q.get('clean', '1') not in ('0', 'false'))
            return png, 'image/png', {'Cache-Control': 'no-store'}
        if path == '/api/dash/wb_sar':
            return s.wb_sar(q['id'], q.get('what', 'extent'), q.get('res', 'lo')), 'image/png', {'Cache-Control': 'no-store'}
        if path == '/api/dash/wb_cell':
            return s.wb_cell(q['run'], float(q['lat']), float(q['lon'])), 'application/json', None
        if path == '/api/dash/cell':
            t = int(q['t']) if q.get('t') not in (None, '') else None
            return s.cell(float(q['lat']), float(q['lon']), t), 'application/json', None
        if path == '/api/dash/alerts':
            t = int(q['t']) if q.get('t') not in (None, '') else None
            return s.alerts(q.get('phase', 'before'), t), 'application/json', {'Cache-Control': 'public, max-age=10, s-maxage=30'} if s.web else None
        if path == '/api/dash/cctv':
            return s.cctv_state(), 'application/json', None
        if path == '/api/dash/cameras':
            return s.cameras(), 'application/json', None
        if path == '/api/dash/cctv/image':
            return s.image_file(q.get('cam', ''), q.get('full') in ('1', 'true')), 'image/jpeg', {'Cache-Control': 'max-age=300'}
        if path == '/api/dash/point':
            return s.point(float(q['lat']), float(q['lon'])), 'application/json', None
        if path == '/api/dash/cctv/version':
            s.cctv.refresh(); return dict(version=s.cctv.version), 'application/json', None
        return None

    def post(s, path, raw):
        if path == '/api/dash/forecast':
            b = json.loads(raw or b'{}'); return s.forecast(**s._fc_args(b))
        if path == '/api/dash/cctv/upload':
            return s.cctv.import_csv(raw)
        if path == '/api/dash/cctv/add':
            return s.cctv.add_reading(json.loads(raw or b'{}'))
        return None
