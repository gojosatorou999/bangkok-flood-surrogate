"""Bangkok flood surrogate: data prep, model, evaluation and web server (page in index.html, same folder).

Emulates the ANUGA rain-on-grid + tide runs in surrogate_dataset/: given a rain series (mm per 15 min, uniform over
the domain) and a Gulf tide series, it predicts the 150 m water-depth and flow-speed maps at every 15-min step.

Model: U-Net (PyTorch, CUDA + bf16 when available) over the static layers (terrain, Manning n, curve number,
distance to coast, ...), conditioned through FiLM on features of the forcing history (rain sums over 15 min..96 h,
cumulative rain, tide now / lagged / windowed). Each time step is predicted directly (no autoregressive drift).
Split is by scenario: S2, D4, L3, M3 are never seen in training and give the honest test scores.

    python flood_surrogate.py train [--steps 7000]     build cache, train, evaluate  (writes cache/)
    python flood_surrogate.py serve [--port 8000]      web UI at http://localhost:8000
    python flood_surrogate.py                          train if no model yet, then serve

Needs: numpy pandas xarray netCDF4 scipy matplotlib pillow torch  (all from the standard scientific stack).
"""
import argparse, io, json, math, re, sys, threading, time, uuid, webbrowser
from collections import OrderedDict
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.modules.setdefault('flood_surrogate', sys.modules[__name__])

APP_DIR = Path(__file__).resolve().parent         # surrogate_app/ : code, page, cache
ROOT = APP_DIR.parent                             # anuga_model/ : surrogate_dataset/ and inputs/ (full project)
# full project layout if present, else the small copies bundled in data/ (static layers + rain/tide CSVs)
DATA = ROOT / 'surrogate_dataset' if (ROOT / 'surrogate_dataset' / 'static_layers_150m.nc').exists() else APP_DIR / 'data'
INPUTS = ROOT / 'inputs' if (ROOT / 'inputs').is_dir() else APP_DIR / 'data' / 'inputs'
CACHE = APP_DIR / 'cache'
MODEL_PATH = CACHE / 'unet_film.pt'
METRICS_PATH = CACHE / 'metrics.json'
TEST_SCENARIOS = ['S2', 'D4', 'L3', 'M3']   # one held-out event per class
DT_H = 0.25                                  # 15-min steps
CELL_KM2 = 0.15 * 0.15
THR = 0.15                                   # flood threshold used throughout (m)
EPS = 1e-4                                   # GPU float division puts 15 cm / 100 a hair below 0.15
PAD_H, PAD_W = 512, 672                      # 508 x 662 grid padded to a multiple of 16
DEV = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
AMP = dict(device_type='cuda', dtype=torch.bfloat16) if DEV.type == 'cuda' else dict(device_type='cpu', dtype=torch.bfloat16, enabled=False)
CLASS_ORDER = 'SDLMX'


def gpu_banner():
    if DEV.type == 'cuda':
        p = torch.cuda.get_device_properties(0)
        print(f'GPU: {p.name} ({p.total_memory / 2 ** 30:.1f} GB), CUDA {torch.version.cuda}, bf16 autocast', flush=True)
    else:
        print('WARNING: no CUDA GPU visible to PyTorch; running on the CPU (slow). Install a CUDA build of torch.', flush=True)


# ----------------------------------------------------------------------------------------------- data
def sid_key(s):
    return (CLASS_ORDER.find(s[0]) if s[0] in CLASS_ORDER else 9, int(re.sub(r'\D', '', s) or 0))


def scenario_files():
    groups = {}
    for f in DATA.glob('dataset_*_HT*.nc'):
        m = re.match(r'dataset_([A-Z]\d+)_HT(?:_part(\d+)of\d+)?\.nc$', f.name)
        if m:
            groups.setdefault(m.group(1), []).append((int(m.group(2) or 1), f))
    return {k: [f for _, f in sorted(groups[k])] for k in sorted(groups, key=sid_key)}


def build_cache():
    """Decompress every scenario once into int16 .npy files (depth cm, speed cm/s) that training memory-maps."""
    import xarray as xr
    CACHE.mkdir(exist_ok=True)
    ipath = CACHE / 'index.json'
    index = json.loads(ipath.read_text()) if ipath.exists() else {}
    for sid, files in scenario_files().items():
        if sid in index and (CACHE / f'{sid}_speed.npy').exists():
            continue
        t0 = time.time()
        parts = [xr.open_dataset(f, mask_and_scale=False) for f in files]
        T = sum(p.sizes['time'] for p in parts)
        H, W = parts[0].sizes['y'], parts[0].sizes['x']
        dep = np.lib.format.open_memmap(CACHE / f'{sid}_depth.npy', 'w+', np.int16, (T, H, W))
        spd = np.lib.format.open_memmap(CACHE / f'{sid}_speed.npy', 'w+', np.int16, (T, H, W))
        rain, tide, hours, i = [], [], [], 0
        for p in parts:
            n = p.sizes['time']
            for a in range(0, n, 24):
                b = min(a + 24, n)
                dep[i + a:i + b] = np.maximum(p.depth_cm[a:b].values, 0)
                spd[i + a:i + b] = np.maximum(p.speed_cms[a:b].values, 0)
            rain.append(p.rain_mm_per_15min.values.astype(float)); tide.append(p.tide_m.values.astype(float))
            hours.append(p.hours_since_start.values.astype(float)); i += n
        start = str(parts[0].time.values[0])[:16].replace('T', ' ')
        for p in parts:
            p.close()
        dep.flush(); spd.flush(); del dep, spd
        index[sid] = dict(T=T, start=start, rain=np.round(np.concatenate(rain), 4).tolist(),
                          tide=np.round(np.concatenate(tide), 4).tolist(), hours=np.concatenate(hours).tolist(),
                          files=[f.name for f in files])
        ipath.write_text(json.dumps(index))
        print(f'cached {sid}: {T} steps from {len(files)} file(s) in {time.time() - t0:.0f}s', flush=True)
    return index


def load_index():
    return json.loads((CACHE / 'index.json').read_text())


def load_static():
    import xarray as xr
    from scipy.ndimage import gaussian_filter
    st = xr.open_dataset(DATA / 'static_layers_150m.nc')
    mask = st.domain_mask.values == 1
    raw = {k: st[k].values.astype('float32') for k in ['dem_m', 'dem_90m_burned_m', 'manning_n', 'curve_number', 'dist_to_coast_km']}
    for v in raw.values():
        v[~np.isfinite(v)] = np.nanmedian(v[mask])
    dem = raw['dem_m']
    den = lambda s: np.maximum(gaussian_filter(mask.astype('float32'), s), 1e-3)
    smooth = lambda a, s: gaussian_filter(np.where(mask, a, 0), s) / den(s)
    slog = lambda a: np.sign(a) * np.log1p(np.abs(a))
    H, W = mask.shape
    yy, xx = np.meshgrid(np.linspace(-1, 1, H), np.linspace(-1, 1, W), indexing='ij')
    ch = [slog(dem), slog(raw['dem_90m_burned_m']), (raw['manning_n'] - 0.06) / 0.03, (raw['curve_number'] - 80) / 15,
          np.log1p(raw['dist_to_coast_km']) - 2, np.clip(dem - smooth(dem, 3), -5, 5),
          np.clip(dem - smooth(dem, 15), -10, 10) / 2, np.ones_like(dem)]
    X = np.stack([np.where(mask, c, 0) for c in ch] + [xx, yy]).astype('float32')
    return dict(mask=mask, X=X, raw=raw, x=st.x.values, y=st.y.values)


def forcing_features(rain, tide):
    """(T,) rain mm/15min + (T,) tide m -> (T, 25) features of the forcing history up to each step."""
    from numpy.lib.stride_tricks import sliding_window_view as win
    r = np.asarray(rain, float); td = np.asarray(tide, float); T = len(r); t = np.arange(T)
    c = np.concatenate([[0.], np.cumsum(r)])
    f = [np.log1p(c[t + 1] - c[np.maximum(t + 1 - w, 0)]) for w in (1, 2, 4, 8, 12, 24, 48, 96, 192, 384)]
    f.append(np.log1p(c[1:]))
    f.append(np.log1p(np.maximum.accumulate(r)))
    f.append(np.log1p(win(np.r_[np.zeros(23), r], 24).max(1)))
    f.append(np.log1p(t * DT_H) / 5)
    wet = np.where(r >= 0.5, t, -10 ** 6)
    f.append(np.minimum((t - np.maximum.accumulate(wet)) * DT_H, 72) / 24)
    lag = lambda a, k: np.r_[np.full(k, a[0]), a][:len(a)]
    f += [td, lag(td, 4), lag(td, 12), lag(td, 24)]
    for w in (24, 48, 96):
        v = win(np.r_[np.full(w - 1, td[0]), td], w)
        f += [v.max(1), v.mean(1)]
    return np.stack(f, 1).astype('float32')


def synth_tide(T, peak_idx, amp=1.0, shift_h=0.0, mean=0.0):
    """Same synthetic K1/O1/M2/S2 tide as the ANUGA runs: high water of +1.3 m at the rain peak (HT variant)."""
    th = np.arange(T) * DT_H - (peak_idx * DT_H + shift_h)
    comps = [(0.50, 23.934), (0.40, 25.819), (0.25, 12.421), (0.15, 12.0)]
    return mean + amp * sum(a * np.cos(2 * np.pi * th / P) for a, P in comps)


def design_storm(total_mm, duration_h, peak_frac, shape, lead_h, tail_h):
    n = max(1, int(round(duration_h / DT_H))); i = np.arange(n); pk = peak_frac * (n - 1)
    if shape == 'uniform':
        w = np.ones(n)
    elif shape == 'triangular':
        w = np.where(i <= pk, (i + 1) / (pk + 1), (n - i) / (n - pk))
    else:  # 'peaked': Chicago-like, sharp burst around the peak
        w = np.exp(-np.abs(i - pk) / max(0.08 * n, 0.5))
    r = total_mm * w / w.sum()
    return np.r_[np.zeros(int(round(lead_h / DT_H))), r, np.zeros(int(round(tail_h / DT_H)) + 1)]


def read_inputs(sid, tide_variant):
    """inputs/<sid>_precip.csv + tide csv, resampled exactly like build_dataset.py (one extra step at the end)."""
    import pandas as pd
    rain = pd.read_csv(INPUTS / f'{sid}_precip.csv'); tide = pd.read_csv(INPUTS / f'{sid}_{tide_variant}_tide.csv')
    t = np.arange(len(rain) + 1) * DT_H
    return (np.interp(t, rain.elapsed_h, rain.precip_mm_per_15min), np.interp(t, tide.elapsed_h, tide.stage_m_MSL),
            str(rain.datetime_local.iloc[0]))


# ---------------------------------------------------------------------------------------------- model
class Block(nn.Module):
    def __init__(s, cin, cout, gdim, dil=1):
        super().__init__()
        s.c1 = nn.Conv2d(cin, cout, 3, padding=dil, dilation=dil); s.n1 = nn.GroupNorm(8, cout)
        s.c2 = nn.Conv2d(cout, cout, 3, padding=dil, dilation=dil); s.n2 = nn.GroupNorm(8, cout)
        s.film = nn.Linear(gdim, 2 * cout)
        s.skip = nn.Conv2d(cin, cout, 1) if cin != cout else nn.Identity()

    def forward(s, x, g):
        h = F.silu(s.n1(s.c1(x)))
        h = s.n2(s.c2(h))
        sc, sh = s.film(g).chunk(2, 1)
        return F.silu(h * (1 + sc[..., None, None]) + sh[..., None, None] + s.skip(x))


class UNetFiLM(nn.Module):
    def __init__(s, cin, gdim, ch=(32, 64, 128, 192, 256), cout=2, hid=128):
        super().__init__()
        s.gmlp = nn.Sequential(nn.Linear(gdim, hid), nn.SiLU(), nn.Linear(hid, hid), nn.SiLU())
        s.stem = nn.Conv2d(cin, ch[0], 3, padding=1)
        s.enc = nn.ModuleList(); prev = ch[0]
        for c in ch:
            s.enc.append(Block(prev, c, hid)); prev = c
        s.mid = nn.ModuleList([Block(prev, prev, hid, 2), Block(prev, prev, hid, 4)])
        s.dec = nn.ModuleList()
        for c in reversed(ch[:-1]):
            s.dec.append(Block(prev + c, c, hid)); prev = c
        s.head = nn.Conv2d(ch[0], cout, 1)

    def forward(s, x, g):
        g = s.gmlp(g); h = s.stem(x); skips = []
        for i, b in enumerate(s.enc):
            h = b(F.avg_pool2d(h, 2) if i else h, g); skips.append(h)
        for b in s.mid:
            h = b(h, g)
        skips.pop()
        for b in s.dec:
            h = b(torch.cat([F.interpolate(h, scale_factor=2, mode='nearest'), skips.pop()], 1), g)
        return s.head(h)


def pad(a):
    return F.pad(a, (0, PAD_W - a.shape[-1], 0, PAD_H - a.shape[-2]))


to_target = lambda cm: torch.log1p(cm / 10.)          # cm -> log1p(10 * metres)
from_target = lambda y: torch.expm1(y.clamp(min=0)) / 10.  # -> metres (or m/s)


class Surrogate:
    def __init__(s, path=None, static=None):
        ck = torch.load(path or MODEL_PATH, map_location=DEV, weights_only=False)
        s.meta = {k: v for k, v in ck.items() if k != 'state'}
        s.mu, s.sd = np.array(ck['mu'], 'float32'), np.array(ck['sd'], 'float32')
        s.model = UNetFiLM(ck['cin'], ck['gdim']).to(DEV).eval()
        s.model.load_state_dict(ck['state'])
        s.S = static or load_static()
        s.H, s.W = s.S['mask'].shape
        s.X = pad(torch.from_numpy(s.S['X']))[None].to(DEV)
        s.mask_t = torch.from_numpy(s.S['mask']).to(DEV)
        s.lock = threading.Lock()

    @torch.no_grad()
    def predict(s, rain, tide, batch=8):
        """-> depth (m) and speed (m/s) stacks, (T,H,W) float16, kept on the GPU."""
        G = torch.from_numpy((forcing_features(rain, tide) - s.mu) / s.sd).to(DEV)
        T = len(G); dep = torch.empty((T, s.H, s.W), dtype=torch.float16, device=DEV); spd = torch.empty_like(dep)
        with s.lock:
            for a in range(0, T, batch):
                g = G[a:a + batch]
                with torch.autocast(**AMP):
                    out = s.model(s.X.expand(len(g), -1, -1, -1), g)
                o = from_target(out.float()[:, :, :s.H, :s.W]) * s.mask_t
                dep[a:a + len(g)] = o[:, 0]; spd[a:a + len(g)] = o[:, 1]
        return dep, spd


# --------------------------------------------------------------------------------------------- training
def train(steps=7000, batch=4, lr=2e-3, holdout=TEST_SCENARIOS, seed=0):
    index = build_cache(); S = load_static()
    sids = list(index); test_ids = [s for s in holdout if s in index]; train_ids = [s for s in sids if s not in test_ids]
    gpu_banner()
    print(f'train {train_ids} | test {test_ids}', flush=True)
    feats = {s: forcing_features(index[s]['rain'], index[s]['tide']) for s in sids}
    allf = np.concatenate([feats[s] for s in train_ids]); mu, sd = allf.mean(0), allf.std(0) + 1e-6
    feats = {s: (f - mu) / sd for s, f in feats.items()}
    dep = {s: np.load(CACHE / f'{s}_depth.npy', mmap_mode='r') for s in sids}
    spd = {s: np.load(CACHE / f'{s}_speed.npy', mmap_mode='r') for s in sids}
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    model = UNetFiLM(S['X'].shape[0], allf.shape[1]).to(DEV)
    X = pad(torch.from_numpy(S['X']))[None].to(DEV)
    mask = pad(torch.from_numpy(S['mask'].astype('float32')))[None].to(DEV)
    pairs = [(s, t) for s in train_ids for t in range(index[s]['T'])]
    p = np.array([index[s]['T'] ** -0.5 for s, _ in pairs]); p /= p.sum()   # long events not to drown short ones
    tpairs = [(s, t) for s in test_ids for t in range(index[s]['T'])]
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.05)

    def get(sel):
        up = lambda a: torch.from_numpy(a).pin_memory().to(DEV, non_blocking=True) if DEV.type == 'cuda' else torch.from_numpy(a)
        d = up(np.stack([dep[s][t] for s, t in sel])).float()   # int16 over PCIe, cast on the GPU
        v = up(np.stack([spd[s][t] for s, t in sel])).float()
        g = up(np.stack([feats[s][t] for s, t in sel]))
        return pad(d), pad(v), g

    def loss_fn(out, d, v):
        w = mask * (1 + 4 * (d >= 15))   # d in cm
        e = (out[:, 0] - to_target(d)) ** 2 + 0.5 * (out[:, 1] - to_target(v)) ** 2
        return (w * e).sum() / w.sum()

    t0 = time.time(); run = 0.
    for step in range(1, steps + 1):
        model.train()
        d, v, g = get([pairs[i] for i in rng.choice(len(pairs), batch, p=p)])
        with torch.autocast(**AMP):
            out = model(X.expand(batch, -1, -1, -1), g)
        loss = loss_fn(out.float(), d, v)
        opt.zero_grad(set_to_none=True); loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); sched.step()
        run = 0.98 * run + 0.02 * loss.item() if step > 1 else loss.item()
        if step % 250 == 0 or step == steps:
            msg = f'step {step}/{steps}  loss {run:.4f}  lr {sched.get_last_lr()[0]:.2e}  {(time.time() - t0) / step:.3f}s/it'
            if tpairs and (step % 1000 == 0 or step == steps):   # monitoring only; no model selection on test
                model.eval(); tl = []
                with torch.no_grad():
                    for k in range(0, 64, 8):
                        sel = [tpairs[i] for i in np.random.default_rng(k).choice(len(tpairs), 8)]
                        d, v, g = get(sel)
                        with torch.autocast(**AMP):
                            tl.append(loss_fn(model(X.expand(8, -1, -1, -1), g).float(), d, v).item())
                msg += f'  heldout-loss {np.mean(tl):.4f}'
            print(msg, flush=True)
    torch.save(dict(state=model.state_dict(), mu=mu.tolist(), sd=sd.tolist(), cin=S['X'].shape[0], gdim=allf.shape[1],
                    train_ids=train_ids, test_ids=test_ids, steps=steps, batch=batch, lr=lr,
                    trained=time.strftime('%Y-%m-%d %H:%M'), train_minutes=round((time.time() - t0) / 60, 1),
                    device=str(torch.cuda.get_device_name(0) if DEV.type == 'cuda' else 'cpu')), MODEL_PATH)
    print(f'saved {MODEL_PATH} after {(time.time() - t0) / 60:.1f} min', flush=True)
    evaluate(Surrogate(static=S), index)


def to_dev(a, dtype=torch.float32):
    return torch.from_numpy(np.array(a)).to(DEV, dtype)   # copy: memmaps are read-only


@torch.no_grad()
def score(dep, spd, D, V, mask):
    """Metrics of predicted depth/speed (T,H,W float16 GPU tensors, metres) against ANUGA (int16 cm memmaps), on the GPU."""
    acc = {k: torch.zeros((), dtype=torch.float64, device=DEV) for k in ('se', 'ae', 'bias', 'se_wet', 'n_wet', 'se0', 'sev', 'hit', 'miss', 'fa')}
    T = len(dep); n = 0; ap, at, ap5, at5 = [], [], [], []
    mp = torch.zeros(int(mask.sum()), device=DEV); mt = torch.zeros_like(mp)
    for a in range(0, T, 32):
        p = dep[a:a + 32][:, mask].float(); d = to_dev(D[a:a + 32])[:, mask] / 100
        pv = spd[a:a + 32][:, mask].float(); dv = to_dev(V[a:a + 32])[:, mask] / 100
        e = p - d; wet = d >= THR - EPS; pw = p >= THR - EPS
        acc['se'] += (e ** 2).sum(); acc['ae'] += e.abs().sum(); acc['bias'] += e.sum(); n += e.numel()
        acc['se_wet'] += (e[wet] ** 2).sum(); acc['n_wet'] += wet.sum(); acc['se0'] += (d ** 2).sum(); acc['sev'] += ((pv - dv) ** 2).sum()
        acc['hit'] += (pw & wet).sum(); acc['miss'] += (~pw & wet).sum(); acc['fa'] += (pw & ~wet).sum()
        ap.append(pw.sum(1)); at.append(wet.sum(1)); ap5.append((p >= 0.5 - EPS).sum(1)); at5.append((d >= 0.5 - EPS).sum(1))
        mp = torch.maximum(mp, p.amax(0)); mt = torch.maximum(mt, d.amax(0))
    A = {k: v.item() for k, v in acc.items()}
    ser = {k: (torch.cat(v).double() * CELL_KM2).cpu().numpy() for k, v in (('area_pred', ap), ('area_true', at), ('area05_pred', ap5), ('area05_true', at5))}
    h, m, f = A['hit'], A['miss'], A['fa']
    mw, tw = mp >= THR - EPS, mt >= THR - EPS
    mh = (mw & tw).sum().item(); mm = (~mw & tw).sum().item(); mf = (mw & ~tw).sum().item()
    pa, ta = ser['area_pred'].max(), ser['area_true'].max()
    met = dict(rmse=math.sqrt(A['se'] / n), mae=A['ae'] / n, bias=A['bias'] / n,
               rmse_wet=math.sqrt(A['se_wet'] / max(A['n_wet'], 1)), rmse_zero_baseline=math.sqrt(A['se0'] / n),
               rmse_speed=math.sqrt(A['sev'] / n), csi=h / max(h + m + f, 1), pod=h / max(h + m, 1), far=f / max(h + f, 1),
               peak_area_true=ta, peak_area_pred=pa, peak_area_err_pct=100 * (pa - ta) / max(ta, 1e-6),
               maxdepth_rmse=((mp - mt) ** 2).mean().sqrt().item(), maxdepth_csi=mh / max(mh + mm + mf, 1))
    met = {k: round(float(v), 4) for k, v in met.items()}
    return met, {k: np.round(v, 2).tolist() for k, v in ser.items()}


def evaluate(sur, index=None):
    index = index or load_index(); res = {}
    for sid in index:
        t0 = time.time()
        pd_, ps = sur.predict(index[sid]['rain'], index[sid]['tide'])
        D = np.load(CACHE / f'{sid}_depth.npy', mmap_mode='r'); V = np.load(CACHE / f'{sid}_speed.npy', mmap_mode='r')
        met, _ = score(pd_, ps, D, V, sur.mask_t)
        del pd_, ps
        res[sid] = dict(split='test' if sid in sur.meta['test_ids'] else 'train', **met)
        print(f"{sid:3s} {res[sid]['split']:5s}  RMSE {met['rmse']:.3f} m  RMSE(wet) {met['rmse_wet']:.3f}  CSI {met['csi']:.3f}  "
              f"peak area {met['peak_area_pred']:.0f}/{met['peak_area_true']:.0f} km2  ({time.time() - t0:.0f}s)", flush=True)
    summ = {}
    for split in ('train', 'test'):
        rows = [r for r in res.values() if r['split'] == split]
        if rows:
            summ[split] = {k: round(float(np.mean([r[k] for r in rows])), 4) for k in rows[0] if k != 'split'}
    out = dict(per_scenario=res, mean=summ, threshold_m=THR, model={k: v for k, v in sur.meta.items() if k not in ('mu', 'sd')})
    METRICS_PATH.write_text(json.dumps(out, indent=1))
    print('mean:', json.dumps(summ), flush=True)
    return out


# -------------------------------------------------------------------------------------------- rendering
class Renderer:
    """Colours maps on the GPU (256-entry colour lookup tables); only the PNG encoding runs on the CPU."""

    def __init__(s, S):
        from matplotlib import colormaps
        from matplotlib.colors import LightSource, LinearSegmentedColormap
        s.cm = colormaps; s.mask = torch.from_numpy(S['mask']).to(DEV)
        z = S['raw']['dem_90m_burned_m']
        hs = LightSource(azdeg=315, altdeg=40).hillshade(np.clip(z, -5, 40), vert_exag=25, dx=150, dy=150)
        g = 165 + 70 * hs
        s.bg = to_dev(np.dstack([g, g, g, np.where(S['mask'], 255, 0)]))
        s.depth_cmap = LinearSegmentedColormap.from_list('depth', ['#bfe6ff', '#58b4f0', '#1f78d1', '#1b3fa0', '#2a1366'])
        s.lut = {k: to_dev(c(np.linspace(0, 1, 256))[:, :3] * 255) for k, c in
                 (('depth', s.depth_cmap), ('speed', colormaps['inferno']), ('error', colormaps['RdBu_r']),
                  ('terrain', colormaps['terrain']), ('viridis', colormaps['viridis']), ('cividis_r', colormaps['cividis_r']))}
        s.static = {'dem': (to_dev(S['raw']['dem_m']), 'terrain', -3, 12, 'Terrain (m, EGM2008)'),
                    'cn': (to_dev(S['raw']['curve_number']), 'viridis', 60, 98, 'SCS curve number'),
                    'manning': (to_dev(S['raw']['manning_n']), 'viridis', 0.03, 0.12, "Manning's n"),
                    'coast': (to_dev(S['raw']['dist_to_coast_km']), 'cividis_r', 0, 60, 'Distance to coast (km)')}

    def legend(s, kind):
        if kind == 'depth':
            return dict(cmap=s._css(s.depth_cmap), lo=THR, hi=3.0, unit='m', log=True)
        if kind == 'speed':
            return dict(cmap=s._css(s.cm['inferno']), lo=0, hi=1.2, unit='m/s')
        if kind == 'error':
            return dict(cmap=s._css(s.cm['RdBu_r']), lo=-1, hi=1, unit='m (model - ANUGA)')
        a, cmap, lo, hi, label = s.static[kind]
        return dict(cmap=s._css(s.cm[cmap]), lo=lo, hi=hi, unit=label)

    @staticmethod
    def _css(cmap):
        return 'linear-gradient(90deg,' + ','.join('#%02x%02x%02x' % tuple(int(255 * c) for c in cmap(i / 10)[:3]) for i in range(11)) + ')'

    @torch.no_grad()
    def png(s, arr, kind, thr=THR, depth=None):
        """arr / depth: (H,W) float tensors on the GPU."""
        img = s.bg.clone()
        if kind == 'depth':
            show = (arr >= thr - EPS) & s.mask
            v = torch.log(arr.clamp(min=1e-3) / THR) / math.log(3.0 / THR); lut = s.lut['depth']; alpha = 0.9
        elif kind == 'speed':
            show = (depth >= thr - EPS) & (arr >= 0.02) & s.mask; v = arr / 1.2; lut = s.lut['speed']; alpha = 0.9
        elif kind == 'error':
            show = (arr.abs() >= 0.05) & s.mask & (depth >= thr - EPS); v = arr / 2 + 0.5; lut = s.lut['error']; alpha = 0.9
        else:
            a, cmap, lo, hi, _ = s.static[kind]
            show = s.mask; v = (a - lo) / (hi - lo); lut = s.lut[cmap]; alpha = 0.85
        rgb = lut[(v.clamp(0, 1) * 255).round().long()]
        img[..., :3] = torch.where(show[..., None], (1 - alpha) * img[..., :3] + alpha * rgb, img[..., :3])
        return s._encode(img)

    @torch.no_grad()
    def overlay(s, rgb=None, show=None, alpha=0.9, dim=None):
        """Hillshade with an (H,W,3) colour layer where `show`; cells in `dim` are washed out (e.g. no SAR coverage)."""
        img = s.bg.clone()
        if dim is not None:
            img[..., :3] = torch.where((dim & s.mask)[..., None], img[..., :3] * 0.5 + 127, img[..., :3])
        if rgb is not None:
            img[..., :3] = torch.where(show[..., None], (1 - alpha) * img[..., :3] + alpha * rgb, img[..., :3])
        return s._encode(img)

    @staticmethod
    def _encode(img):
        from PIL import Image
        buf = io.BytesIO(); Image.fromarray(img.round().clamp(0, 255).byte().cpu().numpy(), 'RGBA').save(buf, 'PNG', compress_level=1)
        return buf.getvalue()


# ------------------------------------------------------------------------------------------------ server
class App:
    MAX_RUNS = 3   # predictions of the last runs stay on the GPU (a 146 h event is ~0.8 GB)

    def __init__(s):
        s.index = load_index()
        s.sur = Surrogate()
        s.S = s.sur.S; s.mask = s.S['mask']; s.mask_t = s.sur.mask_t
        s.R = Renderer(s.S)
        s.metrics = json.loads(METRICS_PATH.read_text()) if METRICS_PATH.exists() else None
        s.runs = OrderedDict(); s.rlock = threading.Lock()
        allr = [np.asarray(s.index[k]['rain']) for k in s.sur.meta['train_ids']]
        s.train_range = dict(total=max(r.sum() for r in allr), peak=max(r.max() for r in allr),
                             hours=max(len(r) for r in allr) * DT_H)
        s.input_ids = sorted({p.name.split('_')[0] for p in INPUTS.glob('*_precip.csv')}, key=sid_key) if INPUTS.exists() else []
        from calibration import ObsManager
        s.obs = ObsManager(s)

    @staticmethod
    def truth_arrays(sid):
        d, v = CACHE / f'{sid}_depth.npy', CACHE / f'{sid}_speed.npy'
        return (np.load(d, mmap_mode='r'), np.load(v, mmap_mode='r')) if d.exists() and v.exists() else None

    def clear_runs(s):
        with s.rlock:
            s.runs.clear()
        if DEV.type == 'cuda':
            torch.cuda.empty_cache()

    def meta(s):
        scen = [dict(id=k, split='test' if k in s.sur.meta['test_ids'] else 'train', start=v['start'], hours=round(v['T'] * DT_H, 2),
                     rain_total=round(float(np.sum(v['rain'])), 1), rain_peak=round(float(np.max(v['rain'])), 1)) for k, v in s.index.items()]
        return dict(scenarios=scen, inputs=s.input_ids, metrics=s.metrics,
                    device=torch.cuda.get_device_name(0) if DEV.type == 'cuda' else 'CPU (no CUDA GPU found)',
                    model={k: v for k, v in s.sur.meta.items() if k not in ('mu', 'sd')},
                    legends={k: s.R.legend(k) for k in ['depth', 'speed', 'error', 'dem', 'cn', 'manning', 'coast']},
                    static_labels={k: v[4] for k, v in s.R.static.items()}, grid=[int(x) for x in s.mask.shape],
                    train_range={k: round(float(v), 1) for k, v in s.train_range.items()}, model_version=s.obs.db['active'],
                    events=[dict(id=e['id'], name=e['name'], source=e['source'], start=e['start'], n_obs=e['n_obs']) for e in s.obs.events()])

    def run(s, spec):
        typ = spec.get('type'); truth = None; start = None; eid = None
        if typ == 'event':
            eid = spec['id']; rain, tide, start = s.obs.forcing(eid)
            if eid in s.index:
                typ, spec = 'scenario', dict(type='scenario', sid=eid)
            else:
                label = f"{s.obs.db['events'][eid]['name'] if eid in s.obs.db['events'] else eid} (event {eid})"
        if typ == 'scenario':
            eid = spec['sid']
            sid = spec['sid']; v = s.index[sid]; rain, tide, start = np.asarray(v['rain']), np.asarray(v['tide']), v['start']
            truth = s.truth_arrays(sid)
            label = f"{sid} (ANUGA scenario, {'held-out test' if sid in s.sur.meta['test_ids'] else 'training'})"
        elif typ == 'inputs':
            sid, tv = spec['sid'], spec.get('tide', 'HT'); rain, tide, start = read_inputs(sid, tv)
            label = f'{sid} from inputs/ with {tv} tide'
            eid = sid if tv == 'HT' else None
            if tv == 'HT' and sid in s.index:
                truth = s.truth_arrays(sid)
        elif typ == 'design':
            rain = design_storm(float(spec['total_mm']), float(spec['duration_h']), float(spec['peak_pct']) / 100, spec['shape'],
                                float(spec.get('lead_h', 1)), float(spec['tail_h']))
            pk = int(np.argmax(rain)); tide = synth_tide(len(rain), pk, float(spec['tide_amp']), float(spec['tide_shift_h']))
            label = f"Design storm {float(spec['total_mm']):.0f} mm / {float(spec['duration_h']):g} h ({spec['shape']})"
        elif typ == 'custom':
            rain = np.array([float(x) for x in re.split(r'[\s,;]+', spec['rain'].strip()) if x], float)
            if len(rain) < 2:
                raise ValueError('need at least 2 rain values (mm per 15 min)')
            tv = [float(x) for x in re.split(r'[\s,;]+', spec.get('tide', '').strip()) if x]
            if tv:
                tide = np.interp(np.arange(len(rain)), np.linspace(0, len(rain) - 1, len(tv)), tv) if len(tv) != len(rain) else np.array(tv)
            else:
                tide = synth_tide(len(rain), int(np.argmax(rain)))
            label = f'Custom series ({len(rain)} steps)'
        elif typ != 'event':
            raise ValueError('unknown run type')
        rain = np.clip(np.asarray(rain, float), 0, None); tide = np.asarray(tide, float)
        if len(rain) > 1200:
            raise ValueError('series too long (max 1200 steps = 300 h)')
        with s.rlock:   # free the GPU memory of the oldest run before predicting a new one
            while len(s.runs) >= s.MAX_RUNS:
                s.runs.popitem(last=False)
        if DEV.type == 'cuda':
            torch.cuda.empty_cache(); torch.cuda.synchronize()
        t0 = time.time(); dep, spd = s.sur.predict(rain, tide)
        if DEV.type == 'cuda':
            torch.cuda.synchronize()
        secs = time.time() - t0
        m = s.mask_t; r = dict(id=uuid.uuid4().hex[:8], label=label, start=start, dep=dep, spd=spd, truth=truth, rain=rain, tide=tide)
        r['maxp'] = dep.amax(0).float()
        out = dict(id=r['id'], label=label, start=start, T=len(rain), hours=(np.arange(len(rain)) * DT_H).tolist(),
                   rain=np.round(rain, 3).tolist(), tide=np.round(tide, 3).tolist(), predict_seconds=round(secs, 2), has_truth=truth is not None,
                   event_id=eid, model_version=s.obs.db['active'],
                   observations=[dict(id=o['id'], type=o['type'], step=o['step'], row=o.get('row'), col=o.get('col'), depth_m=o.get('depth_m'),
                                      status=o['status'], time_local=o['time_local']) for o in (s.obs.for_event(eid) if eid else [])
                                 if o['step'] < len(rain)])
        warn = []
        tr = s.train_range
        if rain.sum() > tr['total'] * 1.05: warn.append(f'Total rain {rain.sum():.0f} mm is above the largest training event ({tr["total"]:.0f} mm): extrapolation.')
        if rain.max() > tr['peak'] * 1.05: warn.append(f'Peak {rain.max():.1f} mm/15 min is above anything seen in training ({tr["peak"]:.1f}).')
        if len(rain) * DT_H > tr['hours'] * 1.05: warn.append(f'Event is longer than any training event ({tr["hours"]:.0f} h).')
        if tide.max() > 1.35 or tide.min() < -0.75: warn.append('Tide is outside the synthetic HT range used in training (-0.67..1.30 m).')
        if typ == 'inputs' and spec.get('tide') == 'LT': warn.append('Training used the high-tide (HT) variant only; LT results are untested.')
        out['warnings'] = warn
        if truth:
            met, ser = score(dep, spd, truth[0], truth[1], m)
            out['metrics'] = met; out.update(ser)
            mt = torch.zeros(m.shape, device=DEV)
            for a in range(0, len(rain), 32):
                mt = torch.maximum(mt, to_dev(truth[0][a:a + 32]).amax(0) / 100)
            r['maxt'] = mt
        else:
            dm = dep[:, m]
            out['area_pred'] = np.round(((dm >= THR - EPS).sum(1) * CELL_KM2).cpu().numpy(), 2).tolist()
            out['area05_pred'] = np.round(((dm >= 0.5 - EPS).sum(1) * CELL_KM2).cpu().numpy(), 2).tolist()
            del dm
        mp = r['maxp'][m]
        out['summary'] = dict(peak_area=round(max(out['area_pred']), 1), peak_area05=round(max(out['area05_pred']), 1),
                              max_depth_p99=round(torch.quantile(mp, 0.99).item(), 2), rain_total=round(float(rain.sum()), 1),
                              rain_peak=round(float(rain.max()), 2), peak_step=int(np.argmax(out['area_pred'])))
        with s.rlock:
            s.runs[r['id']] = r
        return out

    def get_run(s, rid):
        with s.rlock:
            if rid not in s.runs:
                raise KeyError('run expired; press Run again')
            return s.runs[rid]

    def frame(s, rid, layer, t, thr, obs=None):
        if layer == 'base':
            return s.R.overlay()
        if layer in s.R.static:
            return s.R.png(None, layer)
        if layer in ('sarcmp', 'sarext', 'sardepth'):
            r = s.get_run(rid); o = s.obs.db['observations'][obs]
            if layer == 'sarcmp':
                return s.obs.sar_png(obs, 'compare', r['dep'][o['step']].float())
            return s.obs.sar_png(obs, 'extent' if layer == 'sarext' else 'depth')
        r = s.get_run(rid); t = int(np.clip(t, 0, len(r['dep']) - 1)); tr = r['truth']
        p = r['dep'][t].float()
        if layer == 'pred': return s.R.png(p, 'depth', thr)
        if layer == 'speed': return s.R.png(r['spd'][t].float(), 'speed', thr, p)
        if layer == 'maxpred': return s.R.png(r['maxp'], 'depth', thr)
        if tr is None: raise KeyError('no ANUGA result for this run')
        d = to_dev(tr[0][t]) / 100
        if layer == 'truth': return s.R.png(d, 'depth', thr)
        if layer == 'truth_speed': return s.R.png(to_dev(tr[1][t]) / 100, 'speed', thr, d)
        if layer == 'error': return s.R.png(p - d, 'error', thr, torch.maximum(d, p))
        if layer == 'maxtruth': return s.R.png(r['maxt'], 'depth', thr)
        raise KeyError(layer)

    def point(s, rid, row, col):
        r = s.get_run(rid); row = int(np.clip(row, 0, s.mask.shape[0] - 1)); col = int(np.clip(col, 0, s.mask.shape[1] - 1))
        raw = s.S['raw']
        out = dict(row=row, col=col, x=float(s.S['x'][col]), y=float(s.S['y'][row]), valid=bool(s.mask[row, col]),
                   dem=round(float(raw['dem_m'][row, col]), 2), cn=round(float(raw['curve_number'][row, col]), 1),
                   manning=round(float(raw['manning_n'][row, col]), 3), coast_km=round(float(raw['dist_to_coast_km'][row, col]), 1),
                   pred=np.round(r['dep'][:, row, col].float().cpu().numpy(), 3).tolist(),
                   speed=np.round(r['spd'][:, row, col].float().cpu().numpy(), 3).tolist())
        if r['truth'] is not None:
            out['truth'] = np.round(r['truth'][0][:, row, col].astype('float32') / 100, 3).tolist()
        return out

    def ascii_grid(s, rid, which):
        r = s.get_run(rid); a = (r['maxt'] if which == 'maxtruth' else r['maxp']).cpu().numpy()
        a = np.where(s.mask, a, -9999).astype('float32'); xs, ys = s.S['x'], s.S['y']
        if ys[0] < ys[-1]: a = a[::-1]
        hdr = (f'ncols {a.shape[1]}\nnrows {a.shape[0]}\nxllcorner {xs.min() - 75:.1f}\nyllcorner {ys.min() - 75:.1f}\n'
               f'cellsize 150\nNODATA_value -9999\n')
        buf = io.StringIO(); buf.write(hdr); np.savetxt(buf, a, fmt='%.3f')
        return buf.getvalue().encode()

    def series_csv(s, rid):
        r = s.get_run(rid); dm = r['dep'][:, s.mask_t].float()
        a15 = ((dm >= THR - EPS).sum(1) * CELL_KM2).cpu().numpy(); a50 = ((dm >= 0.5 - EPS).sum(1) * CELL_KM2).cpu().numpy()
        p99 = torch.quantile(dm, 0.99, dim=1).cpu().numpy() if dm.numel() < 2 ** 24 else \
            torch.stack([torch.quantile(dm[t], 0.99) for t in range(len(dm))]).cpu().numpy()
        del dm
        lines = ['step,hours,rain_mm_per_15min,tide_m,flooded_km2_ge_0p15m,flooded_km2_ge_0p5m,max_depth_m_p99']
        for t in range(len(r['rain'])):
            lines.append(f'{t},{t * DT_H:.2f},{r["rain"][t]:.3f},{r["tide"][t]:.3f},{a15[t]:.2f},{a50[t]:.2f},{p99[t]:.3f}')
        return ('\n'.join(lines) + '\n').encode()


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype='application/json', extra=None):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == '/':
                    return self.send(200, PAGE_PATH.read_bytes(), 'text/html; charset=utf-8')
                if u.path == '/api/meta':
                    return self.send(200, app.meta())
                if u.path == '/api/frame':
                    return self.send(200, app.frame(q.get('run'), q.get('layer', 'pred'), int(q.get('t', 0)), float(q.get('thr', THR)), q.get('obs')), 'image/png')
                if u.path == '/api/obs/state':
                    return self.send(200, app.obs.state())
                if u.path == '/api/calib/status':
                    return self.send(200, app.obs.status)
                if u.path == '/api/obs/png':
                    return self.send(200, app.obs.sar_png(q['id'], q.get('what', 'extent')), 'image/png')
                if u.path == '/api/obs/file':
                    pth = app.obs.file_path(q['id']); ext = pth.suffix.lower()
                    ct = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}.get(ext, 'application/octet-stream')
                    return self.send(200, pth.read_bytes(), ct)
                if u.path == '/api/point':
                    return self.send(200, app.point(q['run'], int(q['r']), int(q['c'])))
                if u.path == '/api/download':
                    w = q.get('what', 'maxpred')
                    if w == 'series':
                        return self.send(200, app.series_csv(q['run']), 'text/csv', {'Content-Disposition': f'attachment; filename=flood_series_{q["run"]}.csv'})
                    return self.send(200, app.ascii_grid(q['run'], w), 'text/plain',
                                     {'Content-Disposition': f'attachment; filename={w}_depth_m_{q["run"]}_EPSG32647.asc'})
                self.send(404, {'error': 'not found'})
            except Exception as e:
                self.send(400, {'error': str(e)})

        def do_POST(self):
            try:
                path = urlparse(self.path).path; n = int(self.headers.get('Content-Length', 0))
                if path == '/api/upload':
                    from urllib.parse import unquote
                    return self.send(200, app.obs.save_upload(unquote(self.headers.get('X-Filename', 'file')), self.rfile, n))
                body = json.loads(self.rfile.read(n) or b'{}')
                if path == '/api/run':
                    return self.send(200, app.run(body))
                if path == '/api/obs/event':
                    return self.send(200, dict(id=app.obs.create_event(body)))
                if path == '/api/obs/cctv':
                    return self.send(200, app.obs.add_cctv(body))
                if path == '/api/obs/cctv_batch':
                    return self.send(200, app.obs.add_cctv_batch(body))
                if path == '/api/obs/sar':
                    return self.send(200, app.obs.add_sar(body))
                if path == '/api/obs/status':
                    return self.send(200, app.obs.set_status(body['id'], body.get('status')))
                if path == '/api/obs/delete':
                    app.obs.delete(body['id']); return self.send(200, dict(ok=True))
                if path == '/api/calib/run':
                    if app.obs.calib_lock.locked():
                        raise RuntimeError('a calibration round is already running')
                    kw = {k: body[k] for k in ('steps', 'anchor', 'lr', 'force') if k in body}
                    threading.Thread(target=lambda: app.obs.calibrate(**kw), daemon=True).start()
                    return self.send(200, dict(started=True))
                if path == '/api/calib/auto':
                    app.obs.set_auto(body.get('on')); return self.send(200, dict(auto=app.obs.db['auto']))
                if path == '/api/calib/activate':
                    app.obs.activate(body['id']); return self.send(200, dict(active=app.obs.db['active']))
                self.send(404, {'error': 'not found'})
            except Exception as e:
                self.send(400, {'error': f'{type(e).__name__}: {e}'})
    return H


def serve(port=8000, open_browser=True):
    if not MODEL_PATH.exists():
        sys.exit('No trained model yet. Run:  python flood_surrogate.py train')
    gpu_banner()
    print('loading model and data ...', flush=True)
    app = App()
    srv = ThreadingHTTPServer(('127.0.0.1', port), make_handler(app))
    url = f'http://localhost:{port}'
    print(f'Flood surrogate UI on {url}  (Ctrl+C to stop)', flush=True)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


PAGE_PATH = APP_DIR / 'index.html'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', nargs='?', choices=['train', 'serve', 'eval', 'cache'], default=None)
    ap.add_argument('--steps', type=int, default=7000)
    ap.add_argument('--batch', type=int, default=4)
    ap.add_argument('--lr', type=float, default=2e-3)
    ap.add_argument('--holdout', default=','.join(TEST_SCENARIOS), help="comma list of test scenarios, or 'none' to train on all")
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    hold = [] if a.holdout.lower() == 'none' else [s.strip() for s in a.holdout.split(',') if s.strip()]
    if a.cmd == 'cache':
        build_cache()
    elif a.cmd == 'train' or (a.cmd is None and not MODEL_PATH.exists()):
        train(a.steps, a.batch, a.lr, hold)
        if a.cmd is None:
            serve(a.port, not a.no_browser)
    elif a.cmd == 'eval':
        evaluate(Surrogate())
    else:
        serve(a.port, not a.no_browser)


if __name__ == '__main__':
    main()
