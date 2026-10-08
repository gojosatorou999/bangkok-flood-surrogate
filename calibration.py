"""Observations and self-calibration for the Bangkok flood surrogate.

  * CCTV readings (water depth at a camera, estimated by the user's own image pipeline; images optional) -> validated.
  * Sentinel-1 SAR GeoTIFFs -> flood extent on the 150 m grid (Otsu threshold, optional pre-event change detection),
    plus an approximate depth map from the extent edges and the terrain (FwDET-style).
  * Calibration rounds: fine-tune a copy of the active model on the GPU against the accepted observations while an
    anchor loss keeps it faithful to the ANUGA runs; validate on held-out observations (CCTV points and SAR map
    blocks) and promote the candidate only if it beats the active model there without drifting from ANUGA.
Everything lives in surrogate_app/observations/ (db.json + uploaded files) and cache/versions/ (model versions).
"""
import copy, json, math, re, threading, time, uuid
from datetime import datetime, timedelta

import numpy as np
import torch
import torch.nn.functional as F

import flood_surrogate as fs

OBS_DIR = fs.APP_DIR / 'observations'
FILES = OBS_DIR / 'files'
SAR_DIR = OBS_DIR / 'sar'
DB_PATH = OBS_DIR / 'db.json'
VER_DIR = fs.CACHE / 'versions'
URBAN_CN = 90                         # curve number above which a cell is treated as dense urban (SAR-blind)
Y_THR = math.log1p(10 * fs.THR)       # flood threshold in the model's output space log1p(10 d)
SAR_WINDOW_STEPS = 48                 # CCTV <-> SAR cross-check window: +-12 h
FINE = 5                              # SAR is classified on a 30 m grid (150 m / 5), then aggregated

def parse_time(s):
    return datetime.fromisoformat(str(s).strip().replace('T', ' ')[:19])


def now():
    return time.strftime('%Y-%m-%d %H:%M:%S')


class ObsManager:
    def __init__(s, app):
        s.app = app; s.sur = app.sur; s.S = app.S
        s.mask = app.S['mask']; s.mask_t = app.mask_t; s.H, s.W = s.mask.shape
        s.xs, s.ys = app.S['x'], app.S['y']
        s.cn = app.S['raw']['curve_number']; s.dem = app.S['raw']['dem_m']
        s.urban_t = torch.from_numpy(s.cn >= URBAN_CN).to(fs.DEV)
        for d in (OBS_DIR, FILES, SAR_DIR, VER_DIR):
            d.mkdir(parents=True, exist_ok=True)
        s.lock = threading.RLock(); s.calib_lock = threading.Lock()
        s.db = json.loads(DB_PATH.read_text()) if DB_PATH.exists() else {}
        s.db.setdefault('events', {}); s.db.setdefault('observations', {}); s.db.setdefault('rounds', [])
        s.db.setdefault('versions', [dict(id='v0', created=s.sur.meta.get('trained'), note='ANUGA-trained base model', promoted=True)])
        s.db.setdefault('active', 'v0'); s.db.setdefault('auto', False)
        s.status = dict(state='idle', msg='', progress=0.0, round=None)
        s.pending = False; s.worker = None
        s._forcing = {}; s._feats = {}; s._sar = {}
        from pyproj import Transformer
        s.to_utm = Transformer.from_crs('EPSG:4326', 'EPSG:32647', always_xy=True)
        s.to_ll = Transformer.from_crs('EPSG:32647', 'EPSG:4326', always_xy=True)
        s.base_state = copy.deepcopy(s.sur.model.state_dict())
        if s.db['active'] != 'v0':
            try:
                s._load_version(s.db['active'])
            except Exception as e:
                print(f'could not load model version {s.db["active"]}: {e}; using v0', flush=True); s.db['active'] = 'v0'
        s.save()

    # ------------------------------------------------------------------ storage
    def save(s):
        with s.lock:
            tmp = DB_PATH.with_suffix('.tmp'); tmp.write_text(json.dumps(s.db, indent=1)); tmp.replace(DB_PATH)

    def save_upload(s, name, rfile, length):
        if length > 2 * 1024 ** 3:
            raise ValueError('file larger than 2 GB')
        fid = uuid.uuid4().hex[:12]; safe = re.sub(r'[^A-Za-z0-9._-]', '_', name)[-80:] or 'file'
        path = FILES / f'{fid}_{safe}'
        with open(path, 'wb') as f:
            left = length
            while left > 0:
                chunk = rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk); left -= len(chunk)
        return dict(id=fid, name=safe, bytes=path.stat().st_size)

    def file_path(s, fid):
        if not fid or not re.fullmatch(r'[0-9a-f]{12}', fid):
            raise KeyError('bad file id')
        hits = list(FILES.glob(f'{fid}_*'))
        if not hits:
            raise KeyError('uploaded file not found; upload it again')
        return hits[0]

    # ------------------------------------------------------------------ events & geometry
    def forcing(s, eid):
        if eid in s.app.index:
            v = s.app.index[eid]; return np.asarray(v['rain']), np.asarray(v['tide']), v['start']
        if eid in s.db['events']:
            e = s.db['events'][eid]; return np.asarray(e['rain']), np.asarray(e['tide']), e['start']
        if eid in s.app.input_ids:
            if eid not in s._forcing:
                s._forcing[eid] = fs.read_inputs(eid, 'HT')
            return s._forcing[eid]
        raise KeyError(f'unknown event {eid}')

    def feats(s, eid):
        if eid not in s._feats:
            rain, tide, _ = s.forcing(eid)
            s._feats[eid] = torch.from_numpy((fs.forcing_features(rain, tide) - s.sur.mu) / s.sur.sd).to(fs.DEV)
        return s._feats[eid]

    def events(s):
        out = []
        ids = list(s.app.index) + [i for i in s.app.input_ids if i not in s.app.index] + list(s.db['events'])
        nobs = {}
        for o in s.db['observations'].values():
            nobs[o['event_id']] = nobs.get(o['event_id'], 0) + 1
        for eid in ids:
            rain, tide, start = s.forcing(eid); st = parse_time(start)
            src = 'ANUGA dataset' if eid in s.app.index else 'custom upload' if eid in s.db['events'] else 'inputs/ (no ANUGA run)'
            name = s.db['events'][eid]['name'] if eid in s.db['events'] else eid
            out.append(dict(id=eid, name=name, source=src, start=st.strftime('%Y-%m-%d %H:%M'),
                            end=(st + timedelta(minutes=15 * (len(rain) - 1))).strftime('%Y-%m-%d %H:%M'), T=len(rain),
                            rain_total=round(float(rain.sum()), 1), n_obs=nobs.get(eid, 0)))
        return out

    def step_of(s, eid, when_local):
        rain, _, start = s.forcing(eid); t0 = parse_time(start); t = parse_time(when_local)
        k = int(round((t - t0).total_seconds() / 900))
        if not 0 <= k < len(rain):
            end = t0 + timedelta(minutes=15 * (len(rain) - 1))
            raise ValueError(f'{t:%Y-%m-%d %H:%M} is outside event {eid} ({t0:%Y-%m-%d %H:%M} .. {end:%Y-%m-%d %H:%M} local time)')
        return k

    def locate(s, spec):
        if spec.get('lat') not in (None, '') and spec.get('lon') not in (None, ''):
            lat, lon = float(spec['lat']), float(spec['lon'])
            x, y = s.to_utm.transform(lon, lat)
            c = int(round((x - s.xs[0]) / (s.xs[1] - s.xs[0]))); r = int(round((y - s.ys[0]) / (s.ys[1] - s.ys[0])))
        else:
            r, c = int(spec['row']), int(spec['col'])
            lon, lat = s.to_ll.transform(float(s.xs[min(max(c, 0), s.W - 1)]), float(s.ys[min(max(r, 0), s.H - 1)]))
        if not (0 <= r < s.H and 0 <= c < s.W):
            raise ValueError(f'location {lat:.5f}, {lon:.5f} is outside the model grid')
        return r, c, float(lat), float(lon)

    def create_event(s, spec):
        import pandas as pd
        rain = pd.read_csv(s.file_path(spec['rain_file']))
        tcol = next((c for c in rain.columns if 'time' in c.lower() or 'date' in c.lower()), rain.columns[0])
        vcol = next((c for c in rain.columns if 'precip' in c.lower() or 'rain' in c.lower()), rain.columns[-1])
        times = pd.to_datetime(rain[tcol]); r = rain[vcol].astype(float).clip(lower=0).values
        if len(r) < 2:
            raise ValueError('rain CSV needs at least 2 rows')
        dt = (times.iloc[1] - times.iloc[0]).total_seconds()
        if abs(dt - 900) > 1:
            raise ValueError(f'rain CSV must be at 15-min steps (found {dt / 60:g} min); values are mm per 15 min')
        r = np.r_[r, r[-1]]                                   # same one-step extension as build_dataset.py
        el = np.arange(len(r)) * fs.DT_H
        if spec.get('tide_file'):
            td = pd.read_csv(s.file_path(spec['tide_file']))
            tt = pd.to_datetime(td[next((c for c in td.columns if 'time' in c.lower() or 'date' in c.lower()), td.columns[0])])
            tv = td[next((c for c in td.columns if 'stage' in c.lower() or 'tide' in c.lower() or 'level' in c.lower()), td.columns[-1])].astype(float)
            th = (tt - times.iloc[0]).dt.total_seconds().values / 3600
            tide = np.interp(el, th, tv.values)
        else:
            tide = fs.synth_tide(len(r), int(np.argmax(r)))
        with s.lock:
            n = 1 + sum(1 for k in s.db['events'] if k.startswith('C'))
            eid = f'C{n}'
            while eid in s.db['events']:
                n += 1; eid = f'C{n}'
            s.db['events'][eid] = dict(name=spec.get('name') or eid, start=times.iloc[0].strftime('%Y-%m-%d %H:%M'),
                                       rain=np.round(r, 4).tolist(), tide=np.round(tide, 4).tolist(),
                                       tide_source='uploaded' if spec.get('tide_file') else 'synthetic HT at rain peak', created=now())
            s.save()
        return eid

    # ------------------------------------------------------------------ model helpers
    @torch.no_grad()
    def predict_steps(s, eid, steps, model=None):
        """Depth (m) at the given steps of an event, (n,H,W) on the GPU."""
        model = model or s.sur.model; G = s.feats(eid)[torch.as_tensor(steps, device=fs.DEV)]
        outs = []
        with s.sur.lock:
            for a in range(0, len(G), 8):
                g = G[a:a + 8]
                with torch.autocast(**fs.AMP):
                    o = model(s.sur.X.expand(len(g), -1, -1, -1), g)
                outs.append(fs.from_target(o.float()[:, 0, :s.H, :s.W]) * s.mask_t)
        return torch.cat(outs)

    def _load_version(s, vid):
        if vid == 'v0':
            state = s.base_state
        else:
            state = torch.load(VER_DIR / f'{vid}.pt', map_location=fs.DEV, weights_only=False)['state']
        with s.sur.lock:
            s.sur.model.load_state_dict(state); s.sur.model.eval()

    # ------------------------------------------------------------------ CCTV observations (depths supplied by the user's analysis)
    def _cctv_record(s, d, eid=None):
        eid = d.get('event_id') or eid
        if not eid:
            raise ValueError('event_id missing')
        when = parse_time(d['time_local']); step = s.step_of(eid, when.strftime('%Y-%m-%d %H:%M')); r, c, lat, lon = s.locate(d)
        num = lambda k, default=None: float(d[k]) if d.get(k) not in (None, '') else default
        depth = num('depth_m')
        if depth is None:
            raise ValueError('depth_m missing')
        depth = max(depth, 0.); spread = max(0.10, 0.25 * depth)
        lo, hi = num('depth_low_m', max(depth - spread, 0.)), num('depth_high_m', depth + spread)
        lo, hi = min(lo, depth), max(hi, depth)
        o = dict(id='o' + uuid.uuid4().hex[:8], type='cctv', event_id=eid, step=step, time_local=when.strftime('%Y-%m-%d %H:%M'),
                 row=r, col=c, lat=lat, lon=lon, camera=d.get('camera', ''), notes=d.get('notes', ''),
                 files=dict(before=d.get('before_file') or None, after=d.get('after_file') or None),
                 depth_m=depth, depth_low=lo, depth_high=hi, confidence=float(np.clip(num('confidence', 0.7), 0, 1)),
                 before_depth_m=num('before_depth_m'), created=now(), status_user=None)
        return o

    def add_cctv(s, spec):
        o = s._cctv_record(spec)
        s.validate(o)
        with s.lock:
            s.db['observations'][o['id']] = o; s.save()
        s.revalidate_event(o['event_id'], skip=o['id'])
        s.maybe_auto()
        return o

    def add_cctv_batch(s, spec):
        """CSV with one row per camera reading. Columns (case-insensitive): lat, lon (or row, col), time_local, depth_m;
        optional: event_id, depth_low_m, depth_high_m, confidence, before_depth_m, camera, notes, before_image, after_image."""
        import pandas as pd
        df = pd.read_csv(s.file_path(spec['csv_file'])); df.columns = [c.strip().lower() for c in df.columns]
        alias = {'time': 'time_local', 'datetime': 'time_local', 'datetime_local': 'time_local', 'timestamp': 'time_local',
                 'depth': 'depth_m', 'latitude': 'lat', 'longitude': 'lon', 'lng': 'lon', 'event': 'event_id'}
        df = df.rename(columns={k: v for k, v in alias.items() if k in df.columns and v not in df.columns})
        images = spec.get('images') or {}                       # original filename -> uploaded file id
        made, errors = [], []
        for i, row in df.iterrows():
            d = {k: (None if pd.isna(v) else v) for k, v in row.items()}
            for k in ('before_image', 'after_image'):
                if d.get(k):
                    fid = images.get(str(d[k])) or images.get(re.split(r'[\\/]', str(d[k]))[-1])
                    d[k.replace('image', 'file')] = fid
                    if not fid:
                        errors.append(f'row {i + 2}: image {d[k]} was not uploaded (kept the reading without it)')
            try:
                o = s._cctv_record(d, spec.get('event_id')); made.append(o)
            except Exception as e:
                errors.append(f'row {i + 2}: {e}')
        with s.lock:
            for o in made:
                s.db['observations'][o['id']] = o
            s.save()
        for eid in {o['event_id'] for o in made}:
            s.revalidate_event(eid)
        s.maybe_auto()
        return dict(added=len(made), errors=errors, ids=[o['id'] for o in made])

    # ------------------------------------------------------------------ Sentinel-1 SAR
    def _fine_grid(s):
        from rasterio.transform import Affine
        cell = float(abs(s.xs[1] - s.xs[0])); left = float(s.xs.min()) - cell / 2; top = float(s.ys.max()) + cell / 2
        return Affine(cell / FINE, 0, left, 0, -cell / FINE, top), s.H * FINE, s.W * FINE, s.ys[0] < s.ys[-1]

    def _read_raster(s, path, mode):
        import rasterio
        from rasterio.warp import reproject, Resampling
        tr, Hf, Wf, flip = s._fine_grid()
        dst = np.full((Hf, Wf), np.nan, 'float32')
        with rasterio.open(path) as src:
            if src.crs is None:
                raise ValueError(f'{path.name} has no coordinate reference system; export a georeferenced GeoTIFF')
            nod = src.nodata
            reproject(source=rasterio.band(src, 1), destination=dst, src_transform=src.transform, src_crs=src.crs,
                      src_nodata=nod if nod is not None else (0 if mode == 'backscatter' else None),
                      dst_transform=tr, dst_crs='EPSG:32647', dst_nodata=np.nan,
                      resampling=Resampling.average if mode == 'backscatter' else Resampling.nearest)
        if flip:
            dst = dst[::-1].copy()
        return dst

    @staticmethod
    def _to_db(v):
        f = v[np.isfinite(v)]
        if f.size < 100:
            raise ValueError('the image has almost no valid pixels over the model domain (wrong area or nodata?)')
        med, p95 = np.median(f), np.percentile(f, 95)
        if med < 0:
            return v, 'dB'
        if 0 < med and p95 < 3:
            return 10 * np.log10(np.maximum(v, 1e-6)), 'linear sigma0 -> dB'
        if f.max() > 3 and np.allclose(f, np.round(f)) and f.max() <= 255:
            raise ValueError('values look like an 8-bit rendered picture; export calibrated sigma0 (linear or dB) or a water mask GeoTIFF')
        raise ValueError(f'unrecognised backscatter values (median {med:.3g}); expected sigma0 in dB (negative) or linear (0-1)')

    @staticmethod
    def _otsu(x):
        lo, hi = -35., 5.
        h = torch.histc(x.clamp(lo, hi), bins=256, min=lo, max=hi).double(); c = torch.linspace(lo, hi, 256, device=x.device, dtype=torch.float64)
        w0 = torch.cumsum(h, 0); w1 = h.sum() - w0; m0 = torch.cumsum(h * c, 0) / w0.clamp(min=1); m1 = ((h * c).sum() - torch.cumsum(h * c, 0)) / w1.clamp(min=1)
        return float(c[torch.argmax(w0 * w1 * (m0 - m1) ** 2)])

    def add_sar(s, spec):
        eid = spec['event_id']; t_utc = parse_time(spec['time_utc']); t_loc = t_utc + timedelta(hours=7)
        step = s.step_of(eid, t_loc.strftime('%Y-%m-%d %H:%M')); mode = spec.get('mode', 'backscatter')
        post = s._read_raster(s.file_path(spec['post_file']), mode)
        pre = s._read_raster(s.file_path(spec['pre_file']), mode) if spec.get('pre_file') else None
        info = dict(mode=mode, pre_event=pre is not None)
        dev = fs.DEV
        if mode == 'backscatter':
            post, info['units'] = s._to_db(post)
            P = torch.from_numpy(post).to(dev); valid = torch.isfinite(P)
            thr = s._otsu(P[valid]); info['otsu_db'] = round(thr, 2)
            thr_used = float(np.clip(thr, -24, -14)) if np.isfinite(thr) else -18.0; info['threshold_db'] = round(thr_used, 2)
            water = valid & (P < thr_used)
            if pre is not None:
                pre, _ = s._to_db(pre)
                Q = torch.from_numpy(pre).to(dev); vq = torch.isfinite(Q)
                tq = float(np.clip(s._otsu(Q[vq]), -24, -14)); diff = P - Q
                pre_water = vq & (Q < tq)
                drop = vq & (diff < -3)
                flood = water & (~pre_water | drop)
                perm = water & pre_water & ~drop
                valid = valid & vq
            else:
                flood = water; perm = torch.zeros_like(water)
        else:
            P = torch.from_numpy(post).to(dev); valid = torch.isfinite(P)
            hi = 128 if float(P[valid].max()) > 1.5 else 0.5
            flood = valid & (P >= hi); perm = torch.zeros_like(flood); info['mask_threshold'] = hi
        # 3x3 majority filter removes speckle, then aggregate 5x5 fine cells -> 150 m fractions
        maj = lambda b: F.avg_pool2d(b.float()[None, None], 3, 1, 1)[0, 0] > 0.5
        flood = maj(flood) & valid; perm = maj(perm) & valid
        pool = lambda b: F.avg_pool2d(b.float()[None, None], FINE)[0, 0]
        cover = pool(valid); frac = pool(flood) / cover.clamp(min=1e-6); permf = pool(perm) / cover.clamp(min=1e-6)
        m = s.mask_t & (cover >= 0.5)
        if int(m.sum()) < 0.1 * int(s.mask_t.sum()):
            raise ValueError(f'the image covers only {100 * int(m.sum()) / int(s.mask_t.sum()):.0f}% of the model domain (need 10%)')
        frac = torch.where(m, frac, torch.zeros_like(frac)); permf = torch.where(m, permf, torch.zeros_like(permf))
        depth = s._fwdet((frac >= 0.5) & m & (permf < 0.5))
        oid = 'o' + uuid.uuid4().hex[:8]
        np.savez_compressed(SAR_DIR / f'{oid}.npz', frac=frac.cpu().numpy().astype('float16'), cover=cover.cpu().numpy().astype('float16'),
                            perm=permf.cpu().numpy().astype('float16'), depth=depth.astype('float16'))
        wet = (frac >= 0.5) & m & (permf < 0.5)
        info.update(covered_km2=round(int(m.sum()) * fs.CELL_KM2, 1), flooded_km2=round(int(wet.sum()) * fs.CELL_KM2, 1),
                    flooded_pct_of_covered=round(100 * int(wet.sum()) / max(int(m.sum()), 1), 1),
                    permanent_water_km2=round(int(((permf >= 0.5) & m).sum()) * fs.CELL_KM2, 1),
                    depth_p90_m=round(float(np.percentile(depth[depth > 0], 90)), 2) if (depth > 0).any() else 0.0)
        o = dict(id=oid, type='sar', event_id=eid, step=step, time_utc=t_utc.strftime('%Y-%m-%d %H:%M'), time_local=t_loc.strftime('%Y-%m-%d %H:%M'),
                 files=dict(post=spec['post_file'], pre=spec.get('pre_file')), sar=info, created=now(), status_user=None,
                 label=spec.get('label', ''))
        s.validate(o)
        with s.lock:
            s.db['observations'][oid] = o; s.save()
        s.revalidate_event(eid, skip=oid)
        s.maybe_auto()
        return o

    def _fwdet(s, wet_t):
        """Approximate depth from a flood extent: water surface = 90th pct of terrain on each patch's dry boundary."""
        import pandas as pd
        from scipy import ndimage
        wet = wet_t.cpu().numpy(); dem = s.dem
        lab, n = ndimage.label(wet, structure=np.ones((3, 3)))
        if n == 0:
            return np.zeros(wet.shape, 'float32')
        dil = ndimage.grey_dilation(lab, size=3); bnd = (~wet) & (dil > 0) & s.mask
        wse = pd.Series(dem[bnd]).groupby(dil[bnd]).quantile(0.9)
        top = pd.Series(dem[wet]).groupby(lab[wet]).max()
        table = np.zeros(n + 1, 'float32'); table[top.index] = top.values; table[wse.index] = wse.values
        return np.where(wet, np.clip(table[lab] - dem, 0, 3), 0).astype('float32')

    def sar_arrays(s, oid):
        if oid not in s._sar:
            z = np.load(SAR_DIR / f'{oid}.npz')
            s._sar[oid] = {k: torch.from_numpy(z[k].astype('float32')).to(fs.DEV) for k in z.files}
        return s._sar[oid]

    # ------------------------------------------------------------------ validation of observations
    def validate(s, o, pred=None):
        checks = []
        add = lambda name, ok, sev, detail='': checks.append(dict(name=name, ok=ok, severity=sev, detail=detail))
        if o['type'] == 'cctv':
            r, c = o['row'], o['col']; d = o['depth_m']
            add('Inside model domain', bool(s.mask[r, c]), 'hard')
            conf = o['confidence']
            add('Confidence >= 0.4', conf >= 0.4, 'hard' if conf < 0.25 else 'soft', f'{conf:.2f}')
            add('Depth range <= 1 m wide', o['depth_high'] - o['depth_low'] <= 1.0, 'soft', f"{o['depth_low']:.2f}-{o['depth_high']:.2f} m")
            if o.get('before_depth_m') is not None:
                add('Before depth <= after depth', o['before_depth_m'] <= d + 0.05, 'soft', f"before {o['before_depth_m']:.2f} m")
            if pred is None:
                pred = s.predict_steps(o['event_id'], [o['step']])[0]
            win = pred[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2]
            lo, hi = float(win.min()), float(win.max()); gap = max(lo - d, d - hi, 0)
            add('Within 1.5 m of the active model', gap <= 1.5, 'soft', f'model {lo:.2f}-{hi:.2f} m around the cell')
            sar = s.nearest_sar(o['event_id'], o['step'], r, c)
            if sar is None:
                add('Sentinel-1 cross-check', None, 'soft', 'no SAR image of this event within 12 h covering this cell')
            else:
                A = s.sar_arrays(sar['id']); fmax = float(A['frac'][max(r - 1, 0):r + 2, max(c - 1, 0):c + 2].max())
                urban = s.cn[r, c] >= URBAN_CN; cw, sw = d >= fs.THR, fmax >= 0.3
                if cw == sw:
                    add('Agrees with Sentinel-1', True, 'soft', f"SAR {sar['time_local']}: wet fraction {fmax:.2f}")
                elif cw and urban:
                    add('Agrees with Sentinel-1', None, 'soft', 'SAR says dry, but this is dense urban (SAR cannot see water between buildings)')
                else:
                    add('Agrees with Sentinel-1', False, 'soft', f"SAR {sar['time_local']}: wet fraction {fmax:.2f} vs CCTV {d:.2f} m")
        else:
            I = o['sar']
            add('Covers >= 10% of the domain', True, 'hard', f"{I['covered_km2']} km2")
            if I['mode'] == 'backscatter':
                otsu = I.get('otsu_db')
                add('Otsu threshold plausible (-24..-14 dB)', otsu is not None and -24 <= otsu <= -14, 'soft', f'{otsu} dB')
                add('Pre-event image (removes permanent water)', I['pre_event'], 'soft', '' if I['pre_event'] else 'rivers/ponds may count as flood')
            add('Flooded share < 60% of covered area', I['flooded_pct_of_covered'] < 60, 'soft', f"{I['flooded_pct_of_covered']}%")
            m = s.compare_sar(o, pred)
            o['model_compare'] = m
            add('Overlaps the active model (CSI >= 0.15)', m['csi_nonurban'] >= 0.15, 'soft',
                f"CSI {m['csi_nonurban']:.2f} (non-urban cells); a near-zero value hints at a wrong time or event")
        o['checks'] = checks
        auto = 'rejected' if any(c['ok'] is False and c['severity'] == 'hard' for c in checks) else \
            'flagged' if any(c['ok'] is False for c in checks) else 'accepted'
        o['status_auto'] = auto; o['status'] = o.get('status_user') or auto
        return o

    def nearest_sar(s, eid, step, r, c):
        best = None
        for o in s.db['observations'].values():
            if o['type'] != 'sar' or o['event_id'] != eid or o['status'] == 'rejected' or abs(o['step'] - step) > SAR_WINDOW_STEPS:
                continue
            if float(s.sar_arrays(o['id'])['cover'][r, c]) < 0.5:
                continue
            if best is None or abs(o['step'] - step) < abs(best['step'] - step):
                best = o
        return best

    def compare_sar(s, o, pred=None):
        A = s.sar_arrays(o['id'])
        if pred is None:
            pred = s.predict_steps(o['event_id'], [o['step']])[0]
        base = s.mask_t & (A['cover'] >= 0.5) & (A['perm'] < 0.5)
        sw, mw = A['frac'] >= 0.5, pred >= fs.THR - fs.EPS
        nu = base & ~s.urban_t
        h, mi, fa = [int(x.sum()) for x in (nu & sw & mw, nu & sw & ~mw, nu & ~sw & mw)]
        uh, um = int((base & s.urban_t & sw & mw).sum()), int((base & s.urban_t & sw & ~mw).sum())
        return dict(csi_nonurban=round(h / max(h + mi + fa, 1), 3), pod_nonurban=round(h / max(h + mi, 1), 3),
                    far_nonurban=round(fa / max(h + fa, 1), 3), pod_urban=round(uh / max(uh + um, 1), 3),
                    model_flooded_km2=round(int((base & mw).sum()) * fs.CELL_KM2, 1), sar_flooded_km2=round(int((base & sw).sum()) * fs.CELL_KM2, 1))

    def revalidate_event(s, eid, skip=None):
        obs = [o for o in s.db['observations'].values() if o['event_id'] == eid and o['id'] != skip]
        if not obs:
            return
        steps = sorted({o['step'] for o in obs}); P = s.predict_steps(eid, steps); at = {k: i for i, k in enumerate(steps)}
        with s.lock:
            for o in obs:
                s.validate(o, P[at[o['step']]])
            s.save()

    def revalidate_all(s):
        for eid in {o['event_id'] for o in s.db['observations'].values()}:
            s.revalidate_event(eid)

    def set_status(s, oid, status):
        with s.lock:
            o = s.db['observations'][oid]
            o['status_user'] = None if status in (None, '', 'auto') else status
            o['status'] = o['status_user'] or o['status_auto']; s.save()
        s.maybe_auto()
        return o

    def delete(s, oid):
        with s.lock:
            o = s.db['observations'].pop(oid); s.save()
        s._sar.pop(oid, None)
        if o['type'] == 'sar':
            (SAR_DIR / f'{oid}.npz').unlink(missing_ok=True)
            s.revalidate_event(o['event_id'])

    def for_event(s, eid):
        return [s.public(o) for o in s.db['observations'].values() if o['event_id'] == eid]

    @staticmethod
    def public(o):
        return {k: v for k, v in o.items()}

    # ------------------------------------------------------------------ calibration
    def build_units(s, obs, seed):
        """Group observations by (event, step); split CCTV points and SAR map blocks into train / validation."""
        rng = np.random.default_rng(seed)
        B = 24; vb = rng.random((s.H // B + 1, s.W // B + 1)) < 0.3
        valmask = torch.from_numpy(np.kron(vb, np.ones((B, B), bool))[:s.H, :s.W]).to(fs.DEV)
        cctv = [o for o in obs if o['type'] == 'cctv']
        nval = int(round(0.3 * len(cctv))) if len(cctv) >= 3 else 0
        val_ids = set(o['id'] for o in rng.permutation(np.array(cctv, dtype=object))[:nval]) if nval else set()
        groups = {}
        for o in obs:
            g = groups.setdefault((o['event_id'], o['step']), dict(event=o['event_id'], step=o['step'], sar=[], cctv=[]))
            w = 1.0 if o['status'] == 'accepted' else 0.5
            if o['type'] == 'sar':
                A = s.sar_arrays(o['id'])
                base = (s.mask_t & (A['cover'] >= 0.5) & (A['perm'] < 0.5)).float() * A['cover']
                dry_urban = (A['frac'] < 0.5) & s.urban_t
                base = torch.where(dry_urban, base * 0.3, base)       # SAR is near-blind to water between buildings
                g['sar'].append(dict(id=o['id'], frac=A['frac'], w_train=base * (~valmask).float(), w_val=base * valmask.float(),
                                     nonurban=~s.urban_t, weight=w))
            else:
                y = math.log1p(10 * o['depth_m'])
                sig = (math.log1p(10 * o['depth_high']) - math.log1p(10 * o['depth_low'])) / 2 + 0.05
                g['cctv'].append(dict(id=o['id'], r=o['row'], c=o['col'], y=y, sig=sig, depth=o['depth_m'], lo=o['depth_low'],
                                      hi=o['depth_high'], weight=w * max(o['confidence'], 0.2), split='val' if o['id'] in val_ids else 'train'))
        return list(groups.values())

    @staticmethod
    def obs_loss(raw, g, split):
        """raw: (H,W) model output in log1p(10 d) space for one frame."""
        tot, n = raw.new_zeros(()), 0.
        for a in g['sar']:
            w = a['w_train'] if split == 'train' else a['w_val']
            if float(w.sum()) < 1:
                continue
            wet = a['frac'] >= 0.5
            bal = torch.where(wet, 0.5 / (w * wet).sum().clamp(min=1), 0.5 / (w * ~wet).sum().clamp(min=1))
            bce = F.binary_cross_entropy_with_logits((raw - Y_THR) / 0.1, a['frac'], reduction='none')
            tot = tot + (bce * w * bal).sum() * a['weight']; n += a['weight']
        for p in g['cctv']:
            if p['split'] != split:
                continue
            tot = tot + F.huber_loss(raw[p['r'], p['c']] / p['sig'], raw.new_tensor(p['y'] / p['sig'])) * p['weight']; n += p['weight']
        return tot / n if n else None

    @torch.no_grad()
    def eval_units(s, model, units, split):
        h = mi = fa = uh = um = 0; ae = []; inside = []
        for g in units:
            if not any(float((a['w_val'] if split == 'val' else a['w_train']).sum()) >= 1 for a in g['sar']) and \
                    not any(p['split'] == split for p in g['cctv']):
                continue
            pred = s.predict_steps(g['event'], [g['step']], model)[0]; mw = pred >= fs.THR - fs.EPS
            for a in g['sar']:
                w = (a['w_val'] if split == 'val' else a['w_train']) > 0; sw = a['frac'] >= 0.5
                nu = w & a['nonurban']; u = w & ~a['nonurban']
                h += int((nu & sw & mw).sum()); mi += int((nu & sw & ~mw).sum()); fa += int((nu & ~sw & mw).sum())
                uh += int((u & sw & mw).sum()); um += int((u & sw & ~mw).sum())
            for p in g['cctv']:
                if p['split'] == split:
                    v = float(pred[p['r'], p['c']]); ae.append(abs(v - p['depth'])); inside.append(p['lo'] - 0.05 <= v <= p['hi'] + 0.05)
        out = dict(n_sar_cells=h + mi + fa, n_cctv=len(ae))
        parts = []
        if h + mi + fa:
            out.update(sar_csi=round(h / (h + mi + fa), 4), sar_pod=round(h / max(h + mi, 1), 4), sar_far=round(fa / max(h + fa, 1), 4),
                       sar_pod_urban=round(uh / max(uh + um, 1), 4))
            parts.append(1 - out['sar_csi'])
        if ae:
            out.update(cctv_mae_m=round(float(np.mean(ae)), 4), cctv_in_range=round(float(np.mean(inside)), 3))
            parts.append(min(out['cctv_mae_m'] / 0.5, 1.0))
        out['score'] = round(float(np.mean(parts)), 4) if parts else None
        return out

    @torch.no_grad()
    def fidelity(s, model):
        """Depth RMSE (m) vs ANUGA on 48 fixed frames of the held-out ANUGA scenarios: guards against drifting from the physics."""
        ids = s.sur.meta.get('test_ids') or list(s.app.index)[:4]
        rng = np.random.default_rng(123); pairs = [(sid, int(rng.integers(s.app.index[sid]['T']))) for sid in rng.choice(ids, 48)]
        se = n = 0.
        for sid in sorted(set(p[0] for p in pairs)):
            steps = [t for q, t in pairs if q == sid]
            pred = s.predict_steps(sid, steps, model)
            D = np.load(fs.CACHE / f'{sid}_depth.npy', mmap_mode='r')
            truth = fs.to_dev(D[steps]) / 100
            e = (pred - truth)[:, s.mask_t]; se += float((e ** 2).sum()); n += e.numel()
        return round(math.sqrt(se / n), 5)

    def calibrate(s, steps=300, anchor=1.0, lr=5e-5, force=False, source='manual'):
        if not s.calib_lock.acquire(blocking=False):
            raise RuntimeError('a calibration round is already running')
        try:
            return s._calibrate(int(steps), float(anchor), float(lr), bool(force), source)
        except Exception as e:
            s.status = dict(state='error', msg=f'{type(e).__name__}: {e}', progress=0.0, round=None)
            raise
        finally:
            s.calib_lock.release()

    def _calibrate(s, steps, anchor, lr, force, source):
        t0 = time.time()
        obs = [o for o in s.db['observations'].values() if o['status'] in ('accepted', 'flagged')]
        if not obs:
            raise ValueError('no accepted or flagged observations to calibrate against')
        if not all((fs.CACHE / f'{k}_depth.npy').exists() for k in s.app.index):
            raise ValueError('calibration needs the ANUGA cache (cache/*_depth.npy); run `python flood_surrogate.py cache` '
                             'on a machine that has the full surrogate_dataset/')
        rno = len(s.db['rounds']) + 1
        s.status = dict(state='running', msg='preparing', progress=0.0, round=rno)
        units = s.build_units(obs, seed=rno)
        train_units = [g for g in units if any(float(a['w_train'].sum()) >= 1 for a in g['sar']) or any(p['split'] == 'train' for p in g['cctv'])]
        if not train_units:
            raise ValueError('no observations left for training after the validation split')
        s.app.clear_runs()
        if fs.DEV.type == 'cuda':
            torch.cuda.empty_cache()
        active = s.sur.model
        cand = copy.deepcopy(active).train()
        idx = s.app.index; tr_ids = [k for k in s.sur.meta['train_ids'] if k in idx]
        dep = {k: np.load(fs.CACHE / f'{k}_depth.npy', mmap_mode='r') for k in tr_ids}
        spd = {k: np.load(fs.CACHE / f'{k}_speed.npy', mmap_mode='r') for k in tr_ids}
        mask_p = fs.pad(s.mask_t.float())
        opt = torch.optim.AdamW(cand.parameters(), lr=lr, weight_decay=0)
        rng = np.random.default_rng(rno)
        hist = []
        with s.sur.lock:   # holds the GPU: predictions in the UI wait until the round is done
            X2 = s.sur.X.expand(2, -1, -1, -1)
            for it in range(steps):
                g = train_units[rng.integers(len(train_units))]
                sid = tr_ids[rng.integers(len(tr_ids))]; t = int(rng.integers(idx[sid]['T']))
                G = torch.stack([s.feats(g['event'])[g['step']], s.feats(sid)[t]])
                with torch.autocast(**fs.AMP):
                    out = cand(X2, G).float()
                lo = s.obs_loss(out[0, 0, :s.H, :s.W], g, 'train')
                d = fs.pad(fs.to_dev(dep[sid][t])); v = fs.pad(fs.to_dev(spd[sid][t]))
                w = mask_p * (1 + 4 * (d >= 15))
                la = (w * ((out[1, 0] - fs.to_target(d)) ** 2 + 0.5 * (out[1, 1] - fs.to_target(v)) ** 2)).sum() / w.sum()
                loss = (lo if lo is not None else 0) + anchor * la
                opt.zero_grad(set_to_none=True); loss.backward()
                torch.nn.utils.clip_grad_norm_(cand.parameters(), 1.0); opt.step()
                hist.append((float(lo) if lo is not None else None, float(la)))
                if it % 10 == 0:
                    s.status.update(msg=f'fine-tuning step {it}/{steps}', progress=0.85 * it / steps)
        cand.eval()
        s.status.update(msg='validating against held-out observations and ANUGA', progress=0.88)
        val_a, val_c = s.eval_units(active, units, 'val'), s.eval_units(cand, units, 'val')
        trn_a, trn_c = s.eval_units(active, units, 'train'), s.eval_units(cand, units, 'train')
        fid_a, fid_c = s.fidelity(active), s.fidelity(cand)
        fid_ok = fid_c <= max(fid_a * 1.5, fid_a + 0.005)
        if val_a['score'] is None:
            improved = None
            reason = 'no independent validation data (add a SAR image or at least 3 CCTV points)'
        else:
            improved = val_c['score'] < val_a['score'] - 0.002
            reason = (f"validation score {val_a['score']:.3f} -> {val_c['score']:.3f} "
                      f"({'better' if improved else 'not better'}); ANUGA RMSE {fid_a * 100:.2f} -> {fid_c * 100:.2f} cm ({'ok' if fid_ok else 'drifted too far'})")
        promote = bool(force) or bool(improved and fid_ok)
        vid = f'v{1 + max(int(v["id"][1:]) for v in s.db["versions"])}'
        torch.save(dict(state=cand.state_dict(), **{k: v for k, v in s.sur.meta.items()}, calibrated_from=s.db['active'],
                        created=now(), n_obs=len(obs)), VER_DIR / f'{vid}.pt')
        rec = dict(round=rno, version=vid, parent=s.db['active'], created=now(), source=source, steps=steps, anchor=anchor, lr=lr,
                   n_obs=len(obs), n_sar=sum(o['type'] == 'sar' for o in obs), n_cctv=sum(o['type'] == 'cctv' for o in obs),
                   val_active=val_a, val_candidate=val_c, train_active=trn_a, train_candidate=trn_c,
                   anuga_rmse_active=fid_a, anuga_rmse_candidate=fid_c, promoted=promote, forced=bool(force and not improved),
                   reason=reason, minutes=round((time.time() - t0) / 60, 2),
                   final_loss_obs=next((h[0] for h in reversed(hist) if h[0] is not None), None), final_loss_anchor=hist[-1][1] if hist else None)
        with s.lock:
            s.db['versions'].append(dict(id=vid, created=rec['created'], parent=rec['parent'], note=f"round {rno} ({source})",
                                         promoted=promote, val_score=val_c['score'], anuga_rmse=fid_c, n_obs=len(obs)))
            s.db['rounds'].append(rec)
            if promote:
                with s.sur.lock:
                    active.load_state_dict(cand.state_dict())
                s.db['active'] = vid
            s.save()
        del cand, opt
        if fs.DEV.type == 'cuda':
            torch.cuda.empty_cache()
        if promote:
            s.status.update(msg='re-checking observations against the new model', progress=0.95)
            s.revalidate_all()
        s.status = dict(state='idle', msg=f"round {rno}: {'promoted ' + vid if promote else 'kept ' + s.db['active']} - {reason}", progress=1.0, round=rno)
        return rec

    def activate(s, vid):
        if not any(v['id'] == vid for v in s.db['versions']):
            raise KeyError(vid)
        with s.calib_lock:
            s.app.clear_runs(); s._load_version(vid)
            with s.lock:
                s.db['active'] = vid; s.save()
        s.revalidate_all()

    # ------------------------------------------------------------------ self-iteration
    def set_auto(s, on):
        with s.lock:
            s.db['auto'] = bool(on); s.save()
        if on:
            s.maybe_auto()

    def maybe_auto(s):
        if not s.db.get('auto'):
            return
        if not any(o['status'] in ('accepted', 'flagged') for o in s.db['observations'].values()):
            return
        s.pending = True
        if s.worker is None or not s.worker.is_alive():
            s.worker = threading.Thread(target=s._auto_loop, daemon=True); s.worker.start()

    def _auto_loop(s):
        """New data -> up to 3 rounds, each with a fresh validation split; stop at the first round that doesn't improve."""
        while s.pending:
            s.pending = False
            for _ in range(3):
                try:
                    rec = s.calibrate(source='auto')
                except Exception as e:
                    print('auto calibration:', e, flush=True); break
                if not rec['promoted'] or s.pending:
                    break

    def state(s):
        return dict(events=s.events(), observations=sorted(s.db['observations'].values(), key=lambda o: o['created'], reverse=True),
                    versions=s.db['versions'], rounds=s.db['rounds'][-30:], active=s.db['active'], auto=s.db['auto'],
                    status=s.status, urban_cn=URBAN_CN)

    # ------------------------------------------------------------------ rendering
    def sar_png(s, oid, what, pred=None):
        o = s.db['observations'][oid]; A = s.sar_arrays(oid); R = s.app.R
        base = s.mask_t & (A['cover'] >= 0.5)
        if what == 'depth':
            return R.png(A['depth'], 'depth')
        if what == 'extent':
            rgb = torch.zeros(s.H, s.W, 3, device=fs.DEV)
            rgb[..., 0], rgb[..., 1], rgb[..., 2] = 232, 89, 12
            perm = base & (A['perm'] >= 0.5)
            rgb[perm] = torch.tensor([90., 90., 90.], device=fs.DEV)
            return R.overlay(rgb, base & ((A['frac'] >= 0.5) | perm), 0.85, dim=~base)
        if pred is None:
            pred = s.predict_steps(o['event_id'], [o['step']])[0]
        sw, mw = (A['frac'] >= 0.5) & (A['perm'] < 0.5), pred >= fs.THR - fs.EPS
        rgb = torch.zeros(s.H, s.W, 3, device=fs.DEV)
        cols = [(base & sw & mw, (31, 111, 209)), (base & sw & ~mw, (214, 51, 108)), (base & ~sw & mw & ~s.urban_t, (240, 180, 0)),
                (base & ~sw & mw & s.urban_t, (170, 140, 220))]
        show = torch.zeros_like(base)
        for m, col in cols:
            rgb[m] = torch.tensor(col, dtype=torch.float32, device=fs.DEV); show |= m
        return R.overlay(rgb, show, 0.9, dim=~base)
