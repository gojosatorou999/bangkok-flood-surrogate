"""Real weather for the dashboard: NOAA GFS 0.25 degree forecasts from NOMADS.

Source: https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.<YYYYMMDD>/<CC>/atmos/gfs.t<CC>z.pgrb2.0p25.f<HHH>
The full files are ~500 MB each, so the small per-hour subset (domain box, 7 variables, ~2 KB) is requested from
NOMADS' own filter service for the same file; if that fails, the needed GRIB messages are range-read from the file
using its .idx. Nothing is invented: if NOAA cannot be reached, `fetch_weather` raises GfsError and the dashboard says so.

Timeline: PAST_H hours before the current hour (taken from the first 6 forecast hours of the earlier cycles, the usual
stand-in for analysed rain) and AHEAD_H hours after it (newest cycle). Hourly rain is the domain mean of the GFS cells
in the model box, spread evenly over four 15-minute steps.
"""
import concurrent.futures as cf
import io
import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

NOMADS = 'https://nomads.ncep.noaa.gov'
PROD = NOMADS + '/pub/data/nccf/com/gfs/prod'
FILTER = NOMADS + '/cgi-bin/filter_gfs_0p25.pl'
UA = 'bangkok-flood-dashboard/1.0 (research prototype)'
ICT = timezone(timedelta(hours=7))
UTC = timezone.utc
MAX_HOURLY = 120            # GFS 0.25 degree output is hourly to f120
WORKERS = 4                 # NOMADS asks clients to stay well under 120 requests / minute
SHORT = {'tp': 'tp', '2t': 't2m', '2r': 'rh', '10u': 'u10', '10v': 'v10', 'gust': 'gust', 'prmsl': 'prmsl'}


_DECODE_LOCK = threading.Lock()      # eccodes parses its definition files lazily and is not thread-safe


class GfsError(RuntimeError):
    pass


def _open(url, method='GET', headers=None, timeout=45, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, method=method, headers={'User-Agent': UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, (r.read() if method != 'HEAD' else b'')
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):      # file not published (yet)
                return e.code, b''
            last = e
        except Exception as e:
            last = e
        time.sleep(1.5 * (k + 1))
    raise GfsError(f'{url}: {last}')


def _paths(c, fh):
    d, h = c.strftime('%Y%m%d'), c.strftime('%H')
    return f'gfs.{d}/{h}/atmos', f'gfs.t{h}z.pgrb2.0p25.f{fh:03d}'


def available(c, fh):
    sub, name = _paths(c, fh)
    st, _ = _open(f'{PROD}/{sub}/{name}.idx', 'HEAD', timeout=20, tries=2)
    return st == 200


def floor_cycle(t):
    t = t.astimezone(UTC)
    return t.replace(hour=t.hour // 6 * 6, minute=0, second=0, microsecond=0)


def find_cycle(end_utc, now_utc=None):
    """Newest cycle that has published every hour needed to reach end_utc."""
    now_utc = now_utc or datetime.now(UTC)
    c0 = floor_cycle(now_utc)
    for k in range(0, 9):
        c = c0 - timedelta(hours=6 * k)
        need = math.ceil((end_utc - c).total_seconds() / 3600)
        if need > MAX_HOURLY:
            break
        if available(c, max(need, 1)):
            return c, need
    raise GfsError('no GFS cycle with the needed forecast hours is available on NOMADS')


# ---------------------------------------------------------------------------------------------- decoding
def _decode(blob, box):
    """GRIB2 bytes -> {'tp': mm accumulated from 0, 't2m': C, ...} averaged over the grid nodes inside box."""
    from eccodes import (codes_get, codes_get_array, codes_get_values, codes_new_from_message, codes_release)
    la0, la1, lo0, lo1 = box
    out, pos = {}, 0
    while True:
        i = blob.find(b'GRIB', pos)
        if i < 0:
            break
        ln = int.from_bytes(blob[i + 8:i + 16], 'big')
        g = codes_new_from_message(blob[i:i + ln]); pos = i + ln
        try:
            sn = codes_get(g, 'shortName')
            if sn not in SHORT or (sn == 'tp' and codes_get(g, 'startStep') != 0):
                continue
            if SHORT[sn] in out:
                continue
            lat, lon, v = codes_get_array(g, 'latitudes'), codes_get_array(g, 'longitudes'), codes_get_values(g)
            lon = np.where(lon > 180, lon - 360, lon)
            m = (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
            if not m.any():
                raise GfsError('GFS subset does not cover the model domain')
            out[SHORT[sn]] = float(np.mean(v[m]))
        finally:
            codes_release(g)
    for k, v in (('t2m', -273.15), ('prmsl', 0)):
        if k in out:
            out[k] = out[k] + v if k == 't2m' else out[k] / 100.0
    miss = [k for k in SHORT.values() if k not in out]
    if miss:
        raise GfsError(f'GFS message(s) missing: {", ".join(miss)}')
    return out


def _filter_url(c, fh, pad_box):
    sub, name = _paths(c, fh)
    la0, la1, lo0, lo1 = pad_box
    q = dict(file=name, dir='/' + sub, var_APCP='on', var_TMP='on', var_RH='on', var_UGRD='on', var_VGRD='on', var_PRMSL='on', var_GUST='on',
             lev_surface='on', lev_2_m_above_ground='on', lev_10_m_above_ground='on', lev_mean_sea_level='on', subregion='',
             leftlon=f'{lo0:.2f}', rightlon=f'{lo1:.2f}', toplat=f'{la1:.2f}', bottomlat=f'{la0:.2f}')
    return FILTER + '?' + urllib.parse.urlencode(q)


def _range_blob(c, fh, pad_box):
    """Fallback: read just the wanted messages of the full file with HTTP range requests, crop to the box."""
    sub, name = _paths(c, fh)
    st, idx = _open(f'{PROD}/{sub}/{name}.idx')
    if st != 200:
        raise GfsError(f'{name}.idx not available')
    rows = [ln.split(':') for ln in idx.decode().splitlines() if ln.strip()]
    want = {('APCP', 'surface'), ('TMP', '2 m above ground'), ('RH', '2 m above ground'), ('UGRD', '10 m above ground'),
            ('VGRD', '10 m above ground'), ('PRMSL', 'mean sea level'), ('GUST', 'surface')}
    parts = []
    for n, r in enumerate(rows):
        if (r[3], r[4]) in want and not (r[3] == 'APCP' and not r[5].startswith('0-')):
            a = int(r[1]); b = int(rows[n + 1][1]) - 1 if n + 1 < len(rows) else ''
            s, blob = _open(f'{PROD}/{sub}/{name}', headers={'Range': f'bytes={a}-{b}'}, timeout=90)
            if s not in (200, 206):
                raise GfsError(f'range read failed for {name}')
            parts.append(blob)
    return b''.join(parts)


class Gfs:
    def __init__(self, cache_dir, box):
        """box = (lat0, lat1, lon0, lon1) of the model domain."""
        self.dir = Path(cache_dir); self.dir.mkdir(parents=True, exist_ok=True)
        la0, la1, lo0, lo1 = box
        self.box = (la0 - 0.125, la1 + 0.125, lo0 - 0.125, lo1 + 0.125)          # nodes whose 0.25 degree cell touches the domain
        self.pad = (la0 - 0.3, la1 + 0.3, lo0 - 0.3, lo1 + 0.3)
        self.tag = f'{la0:.2f}_{la1:.2f}_{lo0:.2f}_{lo1:.2f}'

    def _cache(self, c, fh):
        return self.dir / f'{c:%Y%m%d%H}_f{fh:03d}_{self.tag}.json'

    def hour(self, c, fh):
        p = self._cache(c, fh)
        if p.exists():
            return json.loads(p.read_text())
        st, blob = _open(_filter_url(c, fh, self.pad))
        if st != 200 or not blob.startswith(b'GRIB'):
            blob = _range_blob(c, fh, self.pad)
        with _DECODE_LOCK:
            v = _decode(blob, self.box)
        tmp = p.with_suffix('.tmp'); tmp.write_text(json.dumps(v)); tmp.replace(p)
        return v

    def prune(self, keep_hours=36):
        """Drop cached subsets older than keep_hours: the forecast needs the newest cycle plus the 24 h before it, so older
        files are never read again. Keeps the disk usage flat day after day."""
        lim = time.time() - keep_hours * 3600
        for p in self.dir.glob('*.json'):
            if p.stat().st_mtime < lim:
                p.unlink(missing_ok=True)

    # ------------------------------------------------------------------------------------------ public
    def key(self, now_ict=None, past_h=24, ahead_h=72):
        """(cycle, anchor hour): changes when NOAA publishes a new cycle or the hour turns. Cheap (1-2 HEAD requests)."""
        anchor = (now_ict or datetime.now(ICT)).astimezone(ICT).replace(minute=0, second=0, microsecond=0)
        c, need = find_cycle((anchor + timedelta(hours=ahead_h)).astimezone(UTC))
        return c, anchor, need

    def weather(self, now_ict=None, past_h=24, ahead_h=72, progress=None):
        c, anchor, need = self.key(now_ict, past_h, ahead_h)
        start, end = anchor - timedelta(hours=past_h), anchor + timedelta(hours=ahead_h)
        hours = [start + timedelta(hours=k) for k in range(past_h + ahead_h + 1)]       # valid times (ICT), hourly
        src = {}                                                                          # valid hour -> (cycle, fh)
        for v in hours:
            vu = v.astimezone(UTC)
            src[v] = (c, int((vu - c).total_seconds() // 3600)) if vu > c else (floor_cycle(vu - timedelta(hours=1)), None)
        for v, (cc, fh) in list(src.items()):
            if fh is None:
                src[v] = (cc, int((v.astimezone(UTC) - cc).total_seconds() // 3600))
        need_files = set()
        for cc, fh in src.values():
            need_files.add((cc, fh))
            if fh > 1:
                need_files.add((cc, fh - 1))           # the previous accumulation, to take hourly differences
        tasks = sorted(need_files, key=lambda x: (x[0], x[1]))
        done = [0]; data = {}; gaps = []

        def get(t):
            try:
                return t, self.hour(*t), None
            except Exception as e:                      # noqa: BLE001
                return t, None, e
        with cf.ThreadPoolExecutor(WORKERS) as ex:
            for t, v, err in ex.map(get, tasks):
                done[0] += 1
                if progress:
                    progress(done[0], len(tasks))
                if v is None:
                    if t[0] > c - timedelta(hours=1):
                        raise GfsError(f'GFS {t[0]:%Y-%m-%d %HZ} f{t[1]:03d}: {err}')
                    gaps.append(t)
                else:
                    data[t] = v
        n = len(hours)
        arr = {k: np.full(n, np.nan) for k in ('t2m', 'rh', 'u10', 'v10', 'gust', 'prmsl', 'rain')}
        for i, v in enumerate(hours):
            cc, fh = src[v]
            d = data.get((cc, fh))
            if d is None:
                continue
            for k in ('t2m', 'rh', 'u10', 'v10', 'gust', 'prmsl'):
                arr[k][i] = d[k]
            prev = data.get((cc, fh - 1))['tp'] if fh > 1 and (cc, fh - 1) in data else (0.0 if fh == 1 else None)
            if prev is not None:
                arr['rain'][i] = max(d['tp'] - prev, 0.0)
        for k in arr:                                    # holes (a missing old file) -> neighbours; rain -> 0
            a = arr[k]; bad = np.isnan(a)
            if bad.all():
                raise GfsError('no GFS data could be read')
            if bad.any():
                a[bad] = 0.0 if k == 'rain' else np.interp(np.flatnonzero(bad), np.flatnonzero(~bad), a[~bad])
        # hourly -> 15 min
        T = (past_h + ahead_h) * 4 + 1
        tq = np.arange(T) / 4.0
        lin = {k: np.interp(tq, np.arange(n), arr[k]) for k in ('t2m', 'rh', 'u10', 'v10', 'gust', 'prmsl')}
        rain = np.zeros(T)
        for i in range(n):                               # hour ending at hours[i] -> steps (i-1, i]
            for q in range(4):
                k = (i - 1) * 4 + 1 + q
                if 0 <= k < T:
                    rain[k] += arr['rain'][i] / 4.0
        rain[0] = arr['rain'][0] / 4.0
        sp = np.hypot(lin['u10'], lin['v10']) * 3.6
        wdir = (np.degrees(np.arctan2(-lin['u10'], -lin['v10'])) + 360) % 360       # direction the wind blows FROM
        times = [(start + timedelta(minutes=15 * k)).strftime('%Y-%m-%d %H:%M') for k in range(T)]
        return dict(times=times, start=times[0], T=T, now_idx=past_h * 4, rain=np.round(rain, 3).tolist(),
                    temp=np.round(lin['t2m'], 1).tolist(), rh=np.round(np.clip(lin['rh'], 0, 100), 0).tolist(),
                    wind=np.round(sp, 1).tolist(), gust=np.round(lin['gust'] * 3.6, 1).tolist(), wdir=np.round(wdir, 0).tolist(),
                    pressure=np.round(lin['prmsl'], 1).tolist(),
                    source=dict(kind='gfs', cycle=c.strftime('%Y-%m-%d %H') + 'Z', cycle_ict=c.astimezone(ICT).strftime('%Y-%m-%d %H:%M'),
                                fetched=datetime.now(ICT).strftime('%Y-%m-%d %H:%M'), files=len(tasks), gaps=len(gaps), max_fh=need,
                                url=PROD + '/'))
