// Bangkok Flood Dashboard: front end. Talks to the /api/dash/* endpoints of dashboard.py.
// Map: MapLibre GL (2D + 3D terrain, extruded flood water, buildings, pixel-level zoom, before/after swipe).
// Language: every request is language-neutral; all wording happens here, so changeLang() is one synchronous re-render.
import * as ML from '/static/maplibre/maplibre-gl.mjs';
import { t, getLang, setLang, applyStatic, fmtTime, dowOf, num } from './i18n.js';

const maplibregl = ML.default ?? ML;
const API = String(window.FD_API_BASE || '').replace(/\/$/, '');   // '' = same origin (see config.js)
const A = (p) => API + p;
const $ = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = { get(k) { try { return localStorage.getItem('fd_' + k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem('fd_' + k, v); } catch (e) {} } };
const BLANK = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg==';
const CLS_HEX = { NORMAL: '#64c864', WATERLOGGING: '#e6c83c', FLOODING: '#e67828', SEVERE_FLOODING: '#c82828', UNUSABLE: '#787878' };
const LAYERS = {
  before: [['max', 'L_max'], ['depth', 'L_depth']],
  during: [['cctv', 'L_cctv'], ['fused', 'L_fused'], ['depth', 'L_model']],
};
const THR0 = 0.15; // lowest depth on the legend (m)
const MARKERS_MAX = 14; // most alert markers drawn on the map (the header list has every district)
const DEMO_ID = 'heavy';   // the one demo dataset: a synthetic monsoon-trough storm (server: PRESETS['heavy'])
let DEMO = new URLSearchParams(location.search).get('demo') || '';   // '' = live NOAA data

// ------------------------------------------------------------------------------------------------ state
const S = {
  META: null, FC: null, AL: null, CC: null, CAMS: null, PT: null, health: null, stage: null, loading: false,
  phase: store.get('phase') || 'before', layer: null, playing: false, picking: false,
  view3d: store.get('view') === '3d', basemap: store.get('basemap') || 'streets',
  terX: +(store.get('terx') || 12), waterX: +(store.get('wax') || 40),
  cmp: { on: false, mode: store.get('cmpmode') || 'dry', x: 50 }, sel: null, zoomHi: false, lastCell: null, menuOpen: false,
};
if (location.hash === '#during' || location.hash === '#before') S.phase = location.hash.slice(1);
let MAIN = null, CMP = null, syncing = false, popup = null;
const MK = { dist: [], cams: [] };

// ------------------------------------------------------------------------------------------------ api + small helpers
async function api(path, body, raw) {
  const o = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': raw ? 'text/csv' : 'application/json' }, body: raw ? body : JSON.stringify(body) };
  const r = await fetch(A(path), o);
  let j; try { j = await r.json(); } catch (e) { j = {}; }
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}
const lvColor = (l) => css('--l' + l);
const lvName = (l) => t('lv_' + l);
const clsText = (c) => t('cls_' + c) || c;
const nameOf = (o, k = '') => (getLang() === 'th' ? (o['name' + k + '_th'] || o['name' + k]) : o['name' + k]);
const hm = (s) => (s ? s.slice(11, 16) : '–');
const compass = (d) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(d / 45) % 8];
function toast(msg) { const e = $('toast'); e.textContent = msg; e.classList.remove('hide'); e.style.opacity = 1; clearTimeout(toast.h); toast.h = setTimeout(() => { e.style.opacity = 0; setTimeout(() => e.classList.add('hide'), 400); }, 5000); }
function tickClock() {
  const d = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Bangkok' }));
  const p = (n) => String(n).padStart(2, '0');
  $('clock').textContent = fmtTime(`${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`) + ' ' + (getLang() === 'th' ? 'น.' : 'ICT');
}

// ------------------------------------------------------------------------------------------------ base maps
const rs = (tiles, attribution, maxzoom = 19, extra = []) => ({
  version: 8, sources: { base: { type: 'raster', tiles, tileSize: 256, maxzoom, attribution }, ...Object.fromEntries(extra.map((e, i) => [`x${i}`, { type: 'raster', tiles: [e], tileSize: 256, maxzoom: 19 }])) },
  layers: [{ id: 'base', type: 'raster', source: 'base' }, ...extra.map((_, i) => ({ id: `x${i}`, type: 'raster', source: `x${i}` }))],
});
const BASEMAPS = {
  streets: () => 'https://tiles.openfreemap.org/styles/liberty',
  satellite: () => rs(['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], 'Imagery © Esri, Maxar, Earthstar Geographics', 19,
    ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}']),
  light: () => rs(['a', 'b', 'c', 'd'].map((s) => `https://${s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png`), '© OpenStreetMap contributors © CARTO', 20),
  dark: () => rs(['a', 'b', 'c', 'd'].map((s) => `https://${s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png`), '© OpenStreetMap contributors © CARTO', 20),
  osm: () => rs(['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], '© OpenStreetMap contributors', 19),
};
const emptyFC = { type: 'FeatureCollection', features: [] };

function depthStops() {
  const hex = (S.META.legends.depth.cmap.match(/#[0-9a-fA-F]{6}/g) || []);
  const out = [];
  hex.forEach((c, i) => out.push(THR0 * Math.pow(3 / THR0, i / (hex.length - 1)), c));
  return out;
}
function coordsOf() {
  const [[la0, lo0], [la1, lo1]] = S.META.bounds;
  return [[lo0, la1], [lo1, la1], [lo1, la0], [lo0, la0]];
}
const firstSymbol = (m) => (m.getStyle().layers.find((l) => l.type === 'symbol') || {}).id;

function setLabelLanguage(m) {
  const th = getLang() === 'th';
  const expr = th ? ['coalesce', ['get', 'name:th'], ['get', 'name'], ['get', 'name_en']] : ['coalesce', ['get', 'name_en'], ['get', 'name:en'], ['get', 'name:latin'], ['get', 'name']];
  for (const l of m.getStyle().layers) {
    if (l.type !== 'symbol' || !l.layout || !l.layout['text-field'] || l.id.startsWith('fd-')) continue;
    if (!JSON.stringify(l.layout['text-field']).includes('name')) continue;
    try { m.setLayoutProperty(l.id, 'text-field', expr); } catch (e) {}
  }
}

function install(m, role) {
  if (!S.META) return;
  const before = firstSymbol(m);
  if (!m.getSource('dem')) m.addSource('dem', { type: 'raster-dem', tiles: [`${API || location.origin}/api/dash/terrain/{z}/{x}/{y}.png`], tileSize: 256, encoding: 'terrarium', maxzoom: 13 });
  if (!m.getSource('dem-hs')) m.addSource('dem-hs', { type: 'raster-dem', tiles: [`${API || location.origin}/api/dash/terrain/{z}/{x}/{y}.png`], tileSize: 256, encoding: 'terrarium', maxzoom: 13 });
  if (!m.getLayer('fd-hill')) m.addLayer({ id: 'fd-hill', type: 'hillshade', source: 'dem-hs', layout: { visibility: S.view3d ? 'visible' : 'none' },
    paint: { 'hillshade-exaggeration': 0.35, 'hillshade-shadow-color': '#26303a', 'hillshade-highlight-color': '#fff', 'hillshade-accent-color': '#45515e' } }, before);
  if (!m.getSource('fd-img')) m.addSource('fd-img', { type: 'image', url: BLANK, coordinates: coordsOf() });
  if (!m.getLayer('fd-flood')) m.addLayer({ id: 'fd-flood', type: 'raster', source: 'fd-img',
    paint: { 'raster-opacity': 0.9, 'raster-fade-duration': 0, 'raster-resampling': S.zoomHi ? 'nearest' : 'linear' } }, before);
  if (!m.getSource('fd-3d')) m.addSource('fd-3d', { type: 'geojson', data: emptyFC });
  if (!m.getLayer('fd-3d')) m.addLayer({ id: 'fd-3d', type: 'fill-extrusion', source: 'fd-3d', layout: { visibility: 'none' },
    paint: { 'fill-extrusion-color': ['interpolate', ['linear'], ['get', 'd'], ...depthStops()], 'fill-extrusion-height': ['*', ['get', 'd'], S.waterX],
      'fill-extrusion-base': 0, 'fill-extrusion-opacity': 0.88, 'fill-extrusion-vertical-gradient': true } });
  if (!m.getSource('fd-domain')) m.addSource('fd-domain', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'LineString', coordinates: [...S.META.outline, S.META.outline[0]].map(([la, lo]) => [lo, la]) } } });
  if (!m.getLayer('fd-domain')) m.addLayer({ id: 'fd-domain', type: 'line', source: 'fd-domain', paint: { 'line-color': '#7a8794', 'line-width': 1.2, 'line-dasharray': [3, 3] } });
  if (!m.getSource('fd-cell')) m.addSource('fd-cell', { type: 'geojson', data: emptyFC });
  if (!m.getLayer('fd-cell-fill')) {
    m.addLayer({ id: 'fd-cell-fill', type: 'fill', source: 'fd-cell', paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.18 } });
    m.addLayer({ id: 'fd-cell-line', type: 'line', source: 'fd-cell', paint: { 'line-color': '#111', 'line-width': 2 } });
  }
  if (!m.getSource('fd-pin')) m.addSource('fd-pin', { type: 'geojson', data: emptyFC });
  if (!m.getLayer('fd-pin')) m.addLayer({ id: 'fd-pin', type: 'circle', source: 'fd-pin', paint: { 'circle-radius': 7, 'circle-color': '#e8590c', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } });
  if (m.getLayer('building-3d')) m.setLayoutProperty('building-3d', 'visibility', $('showBld').checked ? 'visible' : 'none');
  m.setTerrain(S.view3d ? { source: 'dem', exaggeration: S.terX } : null);
  setLabelLanguage(m);
  updateOverlays();
}

function makeMap(container, role) {
  const m = new maplibregl.Map({ container, style: BASEMAPS[S.basemap](), center: S.META.center, zoom: 9.7, pitch: S.view3d ? 58 : 0, bearing: S.view3d ? -18 : 0,
    maxZoom: 22, minZoom: 6, maxPitch: 82, attributionControl: { compact: true }, hash: false, cooperativeGestures: false });
  m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-left');
  m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
  m.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true }, trackUserLocation: false }), 'top-left');
  m.on('style.load', () => install(m, role));
  m.on('error', (e) => { if (e && e.error && !/(tile|404|Failed to fetch|aborted)/i.test(String(e.error.message || e.error))) console.warn('map', e.error); });
  return m;
}

// ------------------------------------------------------------------------------------------------ overlays
function specFor(role) {
  const time = +$('time').value;
  const thr = $('thr').value, sig = $('sig').value;
  const hi = S.zoomHi ? 'hi' : 'lo';
  const mk = (kind, tt) => ({ kind, t: tt, thr, sig, res: hi });
  let main = S.layer, mainT = time;
  if (S.cmp.on) {
    if (S.cmp.mode === 'cctv') { main = 'fused'; }
    if (S.cmp.mode === 'time') { main = 'depth'; }
  }
  if (role === 'main') return mk(main, mainT);
  if (S.cmp.mode === 'dry') return null;
  if (S.cmp.mode === 'cctv') return mk('depth', mainT);
  return mk('depth', S.FC ? liveIdx() : 0);
}
function urlOf(sp) {
  if (!sp) return BLANK;
  if (sp.kind !== 'cctv' && !S.FC) return BLANK;
  return A(`/api/dash/overlay?kind=${sp.kind}&t=${sp.t}&thr=${sp.thr}&sigma=${sp.sig}&res=${sp.res}&fc=${S.FC ? S.FC.id : ''}&v=${S.CC ? S.CC.version : 0}`);
}
const ovTok = new WeakMap();
function paintOverlay(m, url) {
  if (!m || !m.getSource('fd-img')) return Promise.resolve();
  const tok = (ovTok.get(m) || 0) + 1; ovTok.set(m, tok);
  return new Promise((res) => {
    if (url === BLANK) { m.getSource('fd-img').updateImage({ url, coordinates: coordsOf() }); return res(); }
    const im = new Image();
    im.onload = () => { if (ovTok.get(m) === tok && m.getSource('fd-img')) m.getSource('fd-img').updateImage({ url, coordinates: coordsOf() }); res(); };
    im.onerror = () => res();
    im.src = url;
  });
}
function updateOverlays() {
  if (!MAIN || !S.META) return Promise.resolve();
  const p = [paintOverlay(MAIN, urlOf(specFor('main')))];
  if (S.cmp.on && CMP) p.push(paintOverlay(CMP, urlOf(specFor('cmp'))));
  const res = S.zoomHi ? 'nearest' : 'linear';
  for (const m of [MAIN, CMP]) if (m && m.getLayer('fd-flood')) m.setPaintProperty('fd-flood', 'raster-resampling', res);
  update3d();
  return Promise.all(p);
}
let t3d = null;
function update3d() {
  clearTimeout(t3d);
  t3d = setTimeout(() => {
    for (const [m, role] of [[MAIN, 'main'], [CMP, 'cmp']]) {
      if (!m || !m.getSource('fd-3d')) continue;
      const sp = role === 'main' || S.cmp.on ? specFor(role) : null;
      const show = S.view3d && sp && S.FC && sp.kind !== 'cctv';
      m.setLayoutProperty('fd-3d', 'visibility', show ? 'visible' : 'none');
      if (show) {
        const b = m.getBounds(), padx = (b.getEast() - b.getWest()) * 0.2, pady = (b.getNorth() - b.getSouth()) * 0.2;
        const bb = [b.getWest() - padx, b.getSouth() - pady, b.getEast() + padx, b.getNorth() + pady].map((v) => v.toFixed(4)).join(',');
        m.getSource('fd-3d').setData(A(`/api/dash/flood3d?kind=${sp.kind === 'max' ? 'max' : 'depth'}&t=${sp.t}&thr=${sp.thr}&fc=${S.FC.id}&bbox=${bb}`));
      }
      if (m.getLayer('fd-flood')) m.setPaintProperty('fd-flood', 'raster-opacity', show ? 0.35 : 0.9);
    }
  }, 160);
}

// ------------------------------------------------------------------------------------------------ view controls
function setView(v) {
  S.view3d = v === '3d'; store.set('view', v);
  document.body.classList.toggle('v3d', S.view3d);
  document.querySelectorAll('#viewseg button').forEach((b) => b.classList.toggle('on', b.dataset.v === v));
  for (const m of [MAIN, CMP]) {
    if (!m || !m.isStyleLoaded()) continue;
    m.setTerrain(S.view3d ? { source: 'dem', exaggeration: S.terX } : null);
    if (m.getLayer('fd-hill')) m.setLayoutProperty('fd-hill', 'visibility', S.view3d ? 'visible' : 'none');
  }
  if (MAIN) MAIN.easeTo({ pitch: S.view3d ? 58 : 0, bearing: S.view3d ? -18 : 0, duration: 900 });
  updateOverlays();
}
function setBasemap(b) {
  S.basemap = b; store.set('basemap', b);
  for (const m of [MAIN, CMP]) if (m) m.setStyle(BASEMAPS[b](), { diff: false });
}
function resetView() {
  const [[la0, lo0], [la1, lo1]] = S.META.bounds;
  MAIN.fitBounds([[lo0, la0], [lo1, la1]], { padding: 30, pitch: S.view3d ? 58 : 0, bearing: S.view3d ? -18 : 0, duration: 900 });
}
function updateZoomBadge() {
  if (!MAIN || !S.META) return;
  const z = MAIN.getZoom(), lat = MAIN.getCenter().lat;
  const mpp = 78271.517 * Math.cos((lat * Math.PI) / 180) / Math.pow(2, z);
  const cellPx = S.META.cell_m / mpp;
  const b = $('zoombadge');
  b.textContent = `${t('zoom')} ${z.toFixed(1)} · ${t('px_scale', { m: mpp < 10 ? mpp.toFixed(1) : Math.round(mpp) })}` + (cellPx >= 2 ? ` · ${t('px_cells', { n: Math.round(cellPx) })}` : '');
  b.classList.toggle('px', cellPx >= 3);
  $('map').classList.toggle('zlow', z < 11.5);
  const hi = z >= 12.5;
  if (hi !== S.zoomHi) { S.zoomHi = hi; updateOverlays(); }
}

// ------------------------------------------------------------------------------------------------ compare (before / after)
function setCompare(on) {
  S.cmp.on = on;
  $('cmpbtn').classList.toggle('on', on);
  $('cmpbtn').textContent = on ? t('compare_off') : t('compare');
  for (const id of ['map2', 'divider', 'chipB', 'chipA']) $(id).classList.toggle('hide', !on);
  $('cmpmode').classList.toggle('hide', !on);
  if (on) {
    if (!CMP) {
      CMP = makeMap('map2', 'cmp');
      const link = (a, b) => a.on('move', () => { if (syncing) return; syncing = true; b.jumpTo({ center: a.getCenter(), zoom: a.getZoom(), bearing: a.getBearing(), pitch: a.getPitch() }); syncing = false; });
      link(MAIN, CMP); link(CMP, MAIN);
      CMP.once('load', () => CMP.jumpTo({ center: MAIN.getCenter(), zoom: MAIN.getZoom(), bearing: MAIN.getBearing(), pitch: MAIN.getPitch() }));
    } else CMP.jumpTo({ center: MAIN.getCenter(), zoom: MAIN.getZoom(), bearing: MAIN.getBearing(), pitch: MAIN.getPitch() });
    placeDivider(S.cmp.x);
    setCmpLabels();
  }
  MAIN && MAIN.resize(); CMP && CMP.resize();
  updateOverlays(); renderLegend();
}
function setCmpLabels() {
  const L = { dry: ['before_lbl', 'after_lbl'], cctv: ['L_model', 'L_fused'], time: ['now', 'L_depth'] }[S.cmp.mode];
  $('chipB').textContent = t(L[0]); $('chipA').textContent = t(L[1]);
}
function placeDivider(x) {
  S.cmp.x = Math.max(2, Math.min(98, x));
  $('divider').style.left = S.cmp.x + '%';
  $('map2').style.clipPath = `inset(0 ${100 - S.cmp.x}% 0 0)`;
  $('divider').setAttribute('aria-valuenow', Math.round(S.cmp.x));
}
(() => {
  const d = $('divider'); let drag = false;
  const move = (e) => { if (!drag) return; const r = $('mapwrap').getBoundingClientRect(); placeDivider(((e.clientX - r.left) / r.width) * 100); };
  d.addEventListener('pointerdown', (e) => { drag = true; d.setPointerCapture(e.pointerId); });
  d.addEventListener('pointermove', move);
  d.addEventListener('pointerup', () => { drag = false; });
  d.addEventListener('keydown', (e) => { if (e.key === 'ArrowLeft') placeDivider(S.cmp.x - 3); if (e.key === 'ArrowRight') placeDivider(S.cmp.x + 3); });
})();

// ------------------------------------------------------------------------------------------------ pixel inspector + clicks
let cellReq = 0, lastMove = 0;
function onMove(e) {
  const now = performance.now();
  if (now - lastMove < 110 || !S.META) return;
  lastMove = now;
  if (MAIN.getZoom() < 9.5) return;
  const my = ++cellReq, tt = +$('time').value;
  const q = `/api/dash/cell?lat=${e.lngLat.lat}&lon=${e.lngLat.lng}` + (S.FC ? `&fc=${S.FC.id}` : '') + (S.FC && S.layer !== 'max' && S.layer !== 'cctv' ? `&t=${tt}` : '');
  api(q).then((c) => { if (my === cellReq) { S.lastCell = c; renderCell(); } }).catch(() => {});
}
function renderCell() {
  const c = S.lastCell; if (!c) return;
  const src = MAIN.getSource('fd-cell');
  if (src) src.setData(c.valid ? { type: 'Feature', geometry: { type: 'Polygon', coordinates: [c.ring] }, properties: {} } : emptyFC);
  const el = $('pxbody'), fl = $('pxfloat');
  el.removeAttribute('data-i18n');
  fl.classList.remove('hide');
  const showPeak = S.layer === 'max' && c.peak != null;
  fl.textContent = !c.valid ? t('px_outside') : `r${c.row}·c${c.col} · ${t('px_ground')} ${num(c.dem)} ${t('m')}`
    + (c.depth != null ? ` · ${showPeak ? t('px_peak') : t('px_depth')} ${num(showPeak ? c.peak : c.depth)} ${t('m')}` : '');
  if (!c.valid) { el.innerHTML = esc(t('px_outside')); return; }
  const kv = (k, v) => `<span>${esc(t(k))} <b class="v">${v}</b></span>`;
  el.className = '';
  el.innerHTML = `<div class="g">${kv('px_cell', `r${c.row}·c${c.col} (${Math.round(c.size_m)} ${t('m')})`)}${kv('px_ground', num(c.dem) + ' ' + t('m'))}`
    + (c.depth != null ? kv('px_depth', num(c.depth) + ' ' + t('m')) + kv('px_peak', num(c.peak) + ' ' + t('m') + ' · ' + fmtTime(c.peak_time)) : '')
    + `${kv('px_normal', num(c.normal_water) + ' ' + t('m'))}${kv('px_cn', num(c.cn, 0))}${kv('px_manning', num(c.manning, 3))}`
    + `<span class="mute">${c.lat.toFixed(5)}, ${c.lon.toFixed(5)}</span></div>`;
}
function onClick(e) {
  if (S.picking) {
    $('flat').value = e.lngLat.lat.toFixed(5); $('flon').value = e.lngLat.lng.toFixed(5);
    S.picking = false; $('fpick').textContent = t('pick_map'); MAIN.getCanvas().style.cursor = '';
    return;
  }
  pointAt(e.lngLat);
}
async function pointAt(ll) {
  if (!S.FC) return;
  const pin = MAIN.getSource('fd-pin');
  if (pin) pin.setData({ type: 'Feature', geometry: { type: 'Point', coordinates: [ll.lng, ll.lat] }, properties: {} });
  try {
    const p = await api(`/api/dash/point?lat=${ll.lat}&lon=${ll.lng}&fc=${S.FC.id}`);
    S.PT = { ...p, ll }; renderPoint(); drawCharts();
  } catch (e) { $('pmeta').textContent = e.message; }
}
function renderPoint() {
  const p = S.PT;
  if (!p) { $('ptitle').textContent = t('pt_title'); $('pmeta').textContent = t('pt_hint'); return; }
  $('ptitle').textContent = p.valid ? t('pt_at', { lat: p.lat.toFixed(4), lon: p.lon.toFixed(4), near: getLang() === 'th' ? p.near_th : p.near }) : t('pt_title');
  $('pmeta').innerHTML = p.valid ? esc(t('pt_meta', { dem: p.dem, nw: p.normal_water, pk: num(Math.max(...p.depth.slice(S.FC.now_idx))) })) : esc(t('pt_out'));
}

// ------------------------------------------------------------------------------------------------ phase, layers, time
function setPhase(p) {
  S.phase = p; store.set('phase', p); history.replaceState(null, '', location.pathname + location.search + '#' + p);
  document.querySelectorAll('#phase button').forEach((b) => b.classList.toggle('on', b.dataset.p === p));
  document.querySelectorAll('[data-phase]').forEach((c) => { if (c.id !== 'camcard') c.classList.toggle('hide', c.dataset.phase !== p); });
  $('camcard').classList.toggle('hide', !(p === 'during' && S.sel));
  closePopup(); renderLayerButtons();
  $('showCams').checked = p === 'during' || $('showCams').checked;
  if (S.FC) setT(liveIdx(), true);
  setLayer(LAYERS[p][0][0]);
  S.AL = null; renderAlertButton(); renderAlertMenu(); drawDistricts();
  drawCams(); loadAlerts();
}
function renderLayerButtons() {
  $('layers').innerHTML = LAYERS[S.phase].map(([k, key]) => `<button data-l="${k}" class="${S.layer === k ? 'on' : ''}">${esc(t(key))}</button>`).join('');
  $('layers').querySelectorAll('button').forEach((b) => (b.onclick = () => setLayer(b.dataset.l)));
}
function setLayer(l) {
  S.layer = l; renderLayerButtons();
  $('thrbox').classList.toggle('hide', l === 'cctv');
  $('sigbox').classList.toggle('hide', !(l === 'cctv' || l === 'fused'));
  refresh();
}
function ovNote() { return { max: t('note_max'), depth: t('note_depth'), cctv: t('note_cctv'), fused: t('note_fused') }[S.layer] || ''; }
function renderLegend() {
  if (!S.META) return;
  const lg = S.layer === 'cctv' ? S.META.legends.cctv : S.META.legends.depth;
  const lo = S.layer === 'cctv' ? '0' : $('thr').value;
  let h = `<span>${lo}</span><span class="bar" style="background:${lg.cmap}"></span><span>${S.layer === 'cctv' ? lg.hi : '3'} ${t('m')}</span><span>${esc(S.layer === 'cctv' ? t('lg_cctv') : t('lg_depth'))}</span>`;
  h += `<span style="margin-left:8px">${esc(t('lg_alerts'))}</span>` + [1, 2, 3].map((i) => `<span class="dotc" style="background:${lvColor(i)}"></span>${esc(lvName(i))}`).join('');
  if ($('showCams').checked) h += `<span style="margin-left:8px">${esc(t('lg_cameras'))}</span>` + ['SEVERE_FLOODING', 'FLOODING', 'WATERLOGGING', 'NORMAL'].map((c) => `<span class="dotc" style="background:${CLS_HEX[c]};border-radius:2px"></span>${esc(clsText(c))}`).join('');
  $('legend').innerHTML = h;
  $('mapnote').textContent = ovNote() + (S.cmp.on ? '  ' + t('cmp_hint') + '.' : '');
}
const T = () => (S.FC ? S.FC.T : 1);
/** Step of the timeline that is "now" by the clock. A published forecast may be a few hours old; never before its issue time. */
function liveIdx() {
  const FC = S.FC; if (!FC) return 0;
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(FC.times[0]);
  if (!m) return FC.now_idx;
  const start = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] - 7, +m[5]);        // the times are ICT = UTC+7
  const k = Math.round((Date.now() - start) / 900000);
  return Math.max(FC.now_idx, Math.min(FC.T - 1, k));
}
function refresh() {
  renderLegend(); timeLabel(); drawCharts();
  return updateOverlays().then(() => { if (S.playing) setTimeout(step, 80); });
}
function setT(tt, quiet) {
  $('time').value = Math.max(0, Math.min(T() - 1, tt));
  if (!quiet) { if (S.layer === 'max') setLayer('depth'); else refresh(); if (S.phase === 'during') loadAlerts(); } else timeLabel();
}
function timeLabel() {
  const FC = S.FC;
  if (!FC) { $('tlabel').textContent = ''; return; }
  const tt = +$('time').value, d = (tt - liveIdx()) * 0.25;
  $('tlabel').textContent = S.layer === 'max' ? t('max_over') : `${fmtTime(FC.times[tt])} (${d === 0 ? t('now') : (d > 0 ? '+' : '') + d.toFixed(d % 1 ? 2 : 0) + ' ' + t('hours_abbr')})`;
}
function step() {
  if (!S.playing) return;
  const tt = +$('time').value;
  if (tt >= T() - 1) { stopPlay(); return; }
  $('time').value = tt + 1; refresh();
}
function stopPlay() { S.playing = false; $('play').innerHTML = '&#9654;'; if (S.phase === 'during') loadAlerts(); }

// ------------------------------------------------------------------------------------------------ forecast + loading state
function renderLoading() {
  const sg = S.stage || { code: 'idle' }, sec = Math.round((Date.now() - (S.loadT0 || Date.now())) / 1000);
  const m = sg.code === 'fetch' ? t('stage_fetch', { d: sg.done || 0, n: sg.total || '…' }) : sg.code === 'model' ? t('stage_model', { s: sec })
    : sg.code === 'idle' || !sg.code ? t('stage_idle') : t('stage_wait', { s: sec });
  $('loadmsg').textContent = m; $('fcstat').textContent = m;
}
async function loadForecast(quiet) {
  if (S.loadingFC) return; S.loadingFC = true;
  S.loadT0 = Date.now(); renderSourceSwitch();
  if (!quiet) { $('maploading').classList.remove('hide'); renderLoading(); }
  const iv = setInterval(async () => {
    try { S.stage = (await api('/api/dash/status')).stage; } catch (e) {}
    if (!quiet) renderLoading();
  }, 1500);
  try {
    const q = DEMO ? `?demo=${encodeURIComponent(DEMO)}` : '';
    const prev = S.FC && S.FC.id;
    S.FC = await api('/api/dash/forecast' + q);
    $('time').max = S.FC.T - 1;
    if (!quiet || !prev) setT(liveIdx(), true);
    renderBanner(); renderForecast(); renderProv(); await refresh(); loadAlerts();
    if (S.PT) pointAt(S.PT.ll);
    if (quiet && prev && prev !== S.FC.id) toast(t('new_forecast', { cycle: S.FC.source.cycle || '' }));
  } catch (e) { $('fcstat').innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  finally { clearInterval(iv); S.loadingFC = false; $('maploading').classList.add('hide'); renderSourceSwitch(); }
}
function renderBanner() {
  const src = S.FC && S.FC.source, b = $('banner');
  let k = 'banner_gfs', v = {};
  if (src && src.kind === 'gfs') { v = { cycle: src.cycle, fetched: src.fetched }; if (src.error) { k = 'banner_stale'; } }
  else if (src && src.kind === 'demo') { k = src.reason === 'noaa_unreachable' ? 'banner_offline' : 'banner_demo'; v = { demo: t('demo_' + src.preset) }; }
  else v = { cycle: '…', fetched: '…' };
  b.textContent = t(k, v);
  b.classList.toggle('warn', k !== 'banner_gfs');
}
// Live (NOAA GFS) / Demo (one synthetic storm) switch in the weather card. Both forecasts stay in memory on the server.
function renderSourceSwitch() {
  const src = S.FC && S.FC.source, live = !DEMO;
  $('wxlive').textContent = src && src.kind === 'gfs' ? t('wx_src_gfs', { cycle: src.cycle }) : t('wx_src_wait');
  document.querySelectorAll('#wxmode button').forEach((b) => { b.classList.toggle('on', (b.dataset.m === 'live') === live); b.disabled = !!S.loadingFC; });
}
function setSource(m) {
  if (S.loadingFC || (m === 'demo') === !!DEMO) return;
  DEMO = m === 'demo' ? DEMO_ID : '';
  const u = new URL(location.href); if (DEMO) u.searchParams.set('demo', DEMO); else u.searchParams.delete('demo');
  history.replaceState(null, '', u);
  S.AL = null; S.PT = null; S.FC = null; closePopup(); renderPoint(); renderAlertButton(); renderAlertMenu(); drawDistricts(); renderFeed();
  renderForecast(); drawCharts(); loadForecast();
}
function warnText(w) { return t('warn_' + w.code, { a: w.a, b: w.b }); }
function renderForecast() {
  const FC = S.FC, src = FC && FC.source;
  renderSourceSwitch();
  if (!FC) { $('wx5').innerHTML = ''; return; }
  const c = FC.current, r = FC.rain_summary;
  const row = (k, v, big) => `<div class="wxr${big ? ' big' : ''}"><span class="k">${esc(t(k))}</span><span class="v">${v}</span></div>`;
  $('wx5').innerHTML =
    row('wx_now', `<b>${num(c.temp, 0)}°</b> ${esc(t('cond_' + c.cond))}`, true)
    + row('wx_rain24', `<b>${num(r.next24h, 0)}</b> ${esc(t('mm'))}`)
    + row('wx_rain72', `<b>${num(r.next72h, 0)}</b> ${esc(t('mm'))}`)
    + row('wx_wind', esc(t('wx_wind_v', { dir: t('dir_' + compass(c.wdir)), v: num(c.wind, 0), g: num(c.gust, 0) })))
    + row('wx_heavy', r.peak_mm_h >= 0.1 ? esc(t('wx_heavy_v', { r: num(r.peak_mm_h, 1), when: fmtTime(r.peak_time) })) : esc(t('wx_none')));
  $('fcwarn').innerHTML = FC.warnings.map((w) => `<div class="warnbox">${esc(warnText(w))}</div>`).join('');
  $('fcstat').textContent = t('wx_foot', { secs: FC.predict_seconds, issued: fmtTime(FC.times[FC.now_idx]) });
}

// ------------------------------------------------------------------------------------------------ charts (canvas)
function chart(cv, o) {
  const dpr = devicePixelRatio || 1, w = cv.clientWidth, H = +cv.dataset.h || 150;
  if (!w) return;
  cv.width = w * dpr; cv.height = H * dpr; cv.style.height = H + 'px';
  const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.font = '11px "Noto Sans Thai",system-ui';
  const ink = css('--mute'), line = css('--line');
  const hasR = o.series.some((s) => s.axis === 'r'), L = 40, R = hasR ? 40 : 10, Tp = 8, B = 22, pw = w - L - R, ph = H - Tp - B;
  g.clearRect(0, 0, w, H);
  if (!o.n) { g.fillStyle = ink; g.fillText(o.empty || t('loading'), L, H / 2); return; }
  const X = (i) => L + (i / (o.n - 1)) * pw;
  const rng = (ss, z) => {
    let lo = z ? 0 : Infinity, hi = -Infinity;
    ss.forEach((s) => s.y.forEach((v) => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
    (o.hlines || []).forEach((h) => { if (h.axis !== 'r') hi = Math.max(hi, h.v * 1.05); });
    if (hi <= lo) hi = lo + 1;
    const p = (hi - lo) * 0.06; return [z ? lo : lo - p, hi + p];
  };
  if (o.now != null) { g.fillStyle = css('--past'); g.fillRect(L, Tp, X(o.now) - L, ph); }
  const ax = (ss, side) => {
    if (!ss.length) return null;
    const [lo, hi] = rng(ss, side === 'l' ? o.zeroL !== false : !!o.zeroR);
    const Y = (v) => Tp + ph - ((v - lo) / (hi - lo)) * ph;
    g.fillStyle = ink; g.textAlign = side === 'l' ? 'right' : 'left';
    for (let i = 0; i <= 4; i++) {
      const v = lo + ((hi - lo) * i) / 4, y = Y(v);
      if (side === 'l') { g.strokeStyle = line; g.beginPath(); g.moveTo(L, y); g.lineTo(L + pw, y); g.stroke(); }
      g.fillText(Math.abs(hi - lo) < 5 ? v.toFixed(Math.abs(hi - lo) < 0.5 ? 2 : 1) : v.toFixed(0), side === 'l' ? L - 5 : L + pw + 5, y + 4);
    }
    return Y;
  };
  const YL = ax(o.series.filter((s) => s.axis !== 'r'), 'l'), YR = ax(o.series.filter((s) => s.axis === 'r'), 'r');
  g.textAlign = 'center'; g.fillStyle = ink;
  S.FC.times.forEach((tm, i) => {
    const hh = tm.slice(11, 13), mm = tm.slice(14);
    if (mm === '00' && (hh === '00' || hh === '12')) {
      const x = X(i); g.strokeStyle = line; g.beginPath(); g.moveTo(x, Tp + ph); g.lineTo(x, Tp + ph + 4); g.stroke();
      g.fillText(hh === '00' ? dowOf(tm.slice(0, 10)) + ' ' + tm.slice(8, 10) : '12:00', x, H - 6);
    }
  });
  for (const h of o.hlines || []) {
    const Y = h.axis === 'r' ? YR : YL; if (!Y) continue;
    g.strokeStyle = h.color; g.setLineDash([4, 3]); g.lineWidth = 1; g.beginPath(); g.moveTo(L, Y(h.v)); g.lineTo(L + pw, Y(h.v)); g.stroke(); g.setLineDash([]);
  }
  for (const s of o.series) {
    const Y = s.axis === 'r' ? YR : YL; g.strokeStyle = g.fillStyle = css(s.color);
    if (s.kind === 'bar') { const bw = Math.max(1, (pw / o.n) * 0.9); s.y.forEach((v, i) => { if (v > 0) { const y = Y(v); g.fillRect(X(i) - bw / 2, y, bw, Y(0) - y); } }); }
    else { g.lineWidth = s.w || 1.8; g.beginPath(); let st = false; s.y.forEach((v, i) => { if (v == null) { st = false; return; } st ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)); st = true; }); g.stroke(); }
  }
  const vline = (i, c, lbl) => { const x = X(i); g.strokeStyle = c; g.lineWidth = 1; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(x, Tp); g.lineTo(x, Tp + ph); g.stroke(); g.setLineDash([]); if (lbl) { g.fillStyle = c; g.textAlign = 'left'; g.fillText(lbl, x + 3, Tp + 10); } };
  if (o.now != null) vline(o.now, ink, t('now').toLowerCase());
  if (o.cursor != null && o.cursor !== o.now) vline(o.cursor, css('--acc2'));
  cv.onclick = (e) => { const r = cv.getBoundingClientRect(); setT(Math.round(((e.clientX - r.left - L) / pw) * (o.n - 1))); };
}
function drawCharts() {
  const FC = S.FC, n = FC ? FC.T : 0, cur = S.layer === 'max' || S.layer === 'cctv' ? null : +$('time').value, base = { n, now: FC && FC.now_idx, cursor: cur };
  chart($('cMain'), { ...base, series: FC ? [{ y: FC.rain, kind: 'bar', color: '--rain' }, { y: FC.area_km2, axis: 'r', color: '--area', w: 2 }] : [], zeroR: true });
  const th = S.META && S.META.thresholds, P = S.PT;
  chart($('cPoint'), { ...base, n: P && P.valid ? n : 0, empty: t('click_map'), series: P && P.valid ? [{ y: P.depth, color: '--area', w: 2 }] : [],
    hlines: th ? [{ v: th.watch, color: lvColor(1) }, { v: th.warning, color: lvColor(2) }, { v: th.severe, color: lvColor(3) }] : [] });
}

// ------------------------------------------------------------------------------------------------ alerts: header button, dropdown, map markers
async function loadAlerts() {
  if (!S.META) return;
  const tt = S.phase === 'during' && S.FC ? `&t=${$('time').value}` : '', my = ++loadAlerts.n;
  try {
    const a = await api(`/api/dash/alerts?phase=${S.phase}${tt}${S.FC ? '&fc=' + S.FC.id : ''}`);
    if (my !== loadAlerts.n || a.phase !== S.phase) return;
    S.AL = a; renderAlertButton(); renderAlertMenu(); drawDistricts(); renderFeed();
  } catch (e) { $('amlist').innerHTML = `<div class="err small">${esc(e.message)}</div>`; }
}
loadAlerts.n = 0;
const flooded = () => (S.AL ? S.AL.alerts.filter((a) => a.level > 0) : []);
function renderAlertButton() {
  const btn = $('alertbtn'), AL = S.AL;
  const waiting = !AL || (S.phase === 'before' && !AL.forecast_id);
  const list = waiting ? [] : flooded(), n = list.length, worst = list.reduce((m, a) => Math.max(m, a.level), 0);
  btn.className = 'alertbtn ' + (waiting ? 'wait' : n ? `on lv${worst}` : 'calm');
  const prev = btn.dataset.n; btn.dataset.n = waiting ? '' : String(n);
  $('altxt').textContent = waiting ? t('al_wait') : n ? `${n} ${t(n === 1 ? 'al_one' : 'al_many')} · ${lvName(worst)}` : t('al_none');
  const ct = $('alcount'); ct.textContent = waiting || !n ? '' : String(n); ct.classList.toggle('hide', waiting || !n);
  if (prev !== undefined && prev !== btn.dataset.n && n) { ct.classList.remove('bump'); void ct.offsetWidth; ct.classList.add('bump'); }
  btn.setAttribute('aria-label', $('altxt').textContent);
}
function alertRight(a) {
  if (!a.level) return `<span class="mute">${esc(t('al_clear_row'))}</span>`;
  if (S.phase === 'before') return `${a.depth != null ? `<b>${num(a.depth)} ${esc(t('m'))}</b>` : ''}${a.onset_time ? ` <span class="mute">${esc(t('al_from', { when: fmtTime(a.onset_time) }))}</span>` : ''}`;
  const dd = Math.max(a.depth || 0, ...(a.cctv.map((e) => e.depth || 0)));
  return `<b>${num(dd)} ${esc(t('m'))}</b> <span class="mute">${esc(a.source === 'cctv' ? t('al_source_cctv') : a.source === 'model+cctv' ? t('al_source_mc') : t('al_source_model'))}</span>`;
}
function renderAlertMenu() {
  const AL = S.AL; if (!AL) { $('amlist').innerHTML = `<div class="mute small" style="padding:10px">${esc(t('waiting_fc'))}</div>`; $('amsum').textContent = ''; $('amsub').textContent = ''; return; }
  const c = AL.counts, nm = S.META.level_names_en;
  $('amsum').innerHTML = [3, 2, 1].map((i) => `<span class="chip"><span class="badge lv${i}">${esc(lvName(i))}</span> ${c[nm[i]]}</span>`).join('') + `<span class="chip mute">${esc(t('clear_n', { n: c[nm[0]] }))}</span>`;
  $('amsub').textContent = S.phase === 'before' ? t('al_sub_before') : t('al_sub_during');
  const q = ($('amq').value || '').trim().toLowerCase();
  const rows = AL.alerts.filter((a) => !q || a.name.toLowerCase().includes(q) || (a.name_th || '').includes(q));
  $('amlist').innerHTML = rows.map((a) => `<button class="amrow l${a.level}${a.level ? '' : ' clear'}" role="menuitem" data-id="${a.id}" title="${esc(nameOf(a))}">
    <span class="amdot" style="background:${lvColor(a.level)}"></span><span class="amname">${esc(nameOf(a))}</span><span class="amlvl">${a.level ? esc(lvName(a.level)) : ''}</span><span class="amval">${alertRight(a)}</span></button>`).join('');
  $('amlist').querySelectorAll('.amrow').forEach((el, i) => { el.style.animationDelay = Math.min(i, 14) * 18 + 'ms'; el.onclick = () => { const a = AL.alerts.find((x) => x.id === +el.dataset.id); toggleMenu(false); focusDistrict(a); }; });
}
function toggleMenu(open) {
  S.menuOpen = open === undefined ? !S.menuOpen : open;
  const m = $('alertmenu'), b = $('alertbtn');
  b.setAttribute('aria-expanded', String(S.menuOpen));
  if (S.menuOpen) { m.hidden = false; requestAnimationFrame(() => m.classList.add('open')); setTimeout(() => $('amq').focus({ preventScroll: true }), 120); }
  else { m.classList.remove('open'); setTimeout(() => { if (!S.menuOpen) m.hidden = true; }, 180); }
}
function focusDistrict(a) {
  if (!a) return;
  const ll = a.hot_lat != null ? [a.hot_lon, a.hot_lat] : [a.lon, a.lat];
  MAIN.flyTo({ center: ll, zoom: Math.max(MAIN.getZoom(), a.level ? 13 : 12), duration: 1100 });
  setTimeout(() => distPopup(a, ll), 1150);
}
function closePopup() { if (popup) { popup.remove(); popup = null; } }
function openPopup(ll, html, opts = {}) {
  closePopup();
  popup = new maplibregl.Popup({ offset: 14, maxWidth: '340px', closeButton: true, ...opts }).setLngLat(ll).setHTML(html).addTo(MAIN);
  return popup;
}
function alertLine(a) {
  if (S.phase === 'before') {
    if (!a.level) return t('pop_line_clear');
    return t('pop_line_before', { lvl: lvName(a.level), d: num(a.depth), onset: fmtTime(a.onset_time), peak: fmtTime(a.peak_time) });
  }
  return a.depth != null ? t('pop_line_during', { lvl: lvName(a.model_level), d: num(a.depth), n6: num(a.next6h) }) : '';
}
function camLine(e) {
  return t('pop_cam_line', { id: e.cam_id, km: num(e.km, 1), cls: clsText(e.cls).toLowerCase(), d: num(e.depth), veh: e.submerged ? t('veh') : '', ph: e.placeholder ? t('ph') : '' });
}
function distPopup(a, ll) {
  const cams = a.cctv.slice(0, 3).map((e) => `<div class="m">${esc(camLine(e))}</div>`).join('');
  openPopup(ll || (a.hot_lat != null ? [a.hot_lon, a.hot_lat] : [a.lon, a.lat]),
    `<div class="pop"><h4>${esc(nameOf(a))} <span class="badge lv${a.level}">${esc(lvName(a.level))}</span></h4><div>${esc(alertLine(a))}</div>${cams}
     <div class="m" style="margin-top:4px">${esc(t('pop_vuln', { v: num(a.vuln), l: t('vuln_' + a.vuln_label), dem: num(a.dem, 1), cn: num(a.cn, 0), coast: num(a.coast_km, 0) }))}</div></div>`);
}
function drawDistricts() {
  for (const k of MK.dist) k.remove();
  MK.dist = [];
  if (!MAIN || !S.AL || !$('showDist').checked) return;
  // only flooded districts, only where the water is (the deepest cell of the district), at most MARKERS_MAX.
  // Camera-sourced alerts are not drawn as pills: the camera's own photo marker is already on that spot.
  const seen = new Set();
  for (const a of flooded().filter((x) => x.source !== 'cctv').slice(0, MARKERS_MAX).reverse()) {
    const ll = a.hot_lat != null ? [a.hot_lon, a.hot_lat] : [a.lon, a.lat];
    const key = ll[0].toFixed(3) + ',' + ll[1].toFixed(3);
    if (seen.has(key)) continue;
    seen.add(key);
    const el = document.createElement('button');
    el.className = `dmk lv${a.level}`; el.title = `${nameOf(a)}: ${lvName(a.level)}`;
    const d = S.phase === 'during' ? Math.max(a.depth || 0, ...a.cctv.map((e) => e.depth || 0)) : (a.depth || 0);   // the same number the list shows
    el.innerHTML = `<span class="ring"></span><span class="dv">${num(d, 2)}</span>`;
    el.addEventListener('click', (e) => { e.stopPropagation(); distPopup(a, ll); });
    MK.dist.push(new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(ll).addTo(MAIN));
  }
}
function feedText(f) {
  const lvl = lvName(f.level), name = getLang() === 'th' ? f.district_th : f.district;
  if (f.kind === 'onset') return t('feed_onset', { name, onset: hm(f.time), lvl, d: num(f.depth), peak: fmtTime(f.peak_time) });
  if (f.kind === 'cctv') return t('feed_cctv', { id: f.cam_id, name, cls: clsText(f.cls).toLowerCase(), d: num(f.depth), veh: f.submerged ? t('veh') : '' });
  return t('feed_rising', { name, lvl, d: num(f.next6h) });
}
function renderFeed() {
  const F = S.AL ? S.AL.feed : [];
  $('feed').innerHTML = F.length ? F.map((f) => `<div><span class="tm"><span class="dotc" style="margin:0 5px 0 0;background:${lvColor(f.level)}"></span>${esc(fmtTime(f.time))}</span><span>${esc(feedText(f))}</span></div>`).join('')
    : `<div class="mute" style="display:block">${esc(S.phase === 'before' ? t('nothing') : t('no_events'))}</div>`;
}

// ------------------------------------------------------------------------------------------------ CCTV: readings, cameras, photos
async function loadCctv() { S.CC = await api('/api/dash/cctv' + (S.FC ? '?fc=' + S.FC.id : '')); renderCctv(); drawCams(); if (S.sel) renderCamCard(); }
async function loadCameras() { S.CAMS = await api('/api/dash/cameras'); drawCams(); }
async function pollCctv() {
  try {
    const v = await api('/api/dash/cctv/version');
    if (S.CC && v.version !== S.CC.version) {
      await loadCctv(); await loadCameras();
      toast(t('cctv_updated_n', { n: S.CC.n_used }));
      loadAlerts(); refresh();
    }
    $('cctvlive').textContent = t('live'); $('cctvlive').title = '';
  } catch (e) { $('cctvlive').textContent = t('offline_tag'); $('cctvlive').title = e.message; }
}
const reasonText = (r) => t('rs_' + r.code, r);
const noteText = (n) => t('nt_' + n.code, n);
function renderCctv() {
  const CC = S.CC; if (!CC) return;
  const c = CC.counts;
  $('ctiles').innerHTML = `<div class="tile"><div class="k">${esc(t('t_cams'))}</div><div class="v">${CC.n_cameras}</div></div><div class="tile"><div class="k">${esc(t('t_severe'))}</div><div class="v" style="color:var(--l3)">${c.SEVERE_FLOODING}</div></div>
    <div class="tile"><div class="k">${esc(t('t_fw'))}</div><div class="v">${c.FLOODING} / ${c.WATERLOGGING}</div></div><div class="tile"><div class="k">${esc(t('t_newest'))}</div><div class="v sm">${esc(fmtTime(CC.latest))}</div></div>`;
  const rows = CC.readings.map((r) => `<tr class="${r.used ? 'cam' : 'ex'}" data-cam="${esc(r.cam_id)}"><td><span class="dotc" style="margin:0 4px 0 0;background:${CLS_HEX[r.cls] || '#888'}"></span><b>${esc(r.cam_id)}</b></td>
    <td>${esc(clsText(r.cls))}</td><td>${num(r.depth)} ${esc(t('m'))}</td><td>${esc(fmtTime(r.time_ict))}</td><td>${r.used ? (r.model_now != null ? num(r.model_now) + ' ' + esc(t('m')) : '–') : `<span title="${esc(r.reasons.map(reasonText).join('; '))}">${esc(t('not_mapped'))}</span>`}</td></tr>`).join('');
  $('ctable').innerHTML = `<table><tr><th>${esc(t('th_cam'))}</th><th>${esc(t('th_class'))}</th><th>${esc(t('th_depth'))}</th><th>${esc(t('th_time'))}</th><th>${esc(t('th_model'))}</th></tr>${rows}</table>
    <div class="pinfo">${esc(t('cctv_foot', { v: [...new Set(CC.readings.map((r) => r.model_version))].join(', '), f: CC.files.join(' + ') || '–', l: CC.loaded }))}</div>`;
  $('ctable').querySelectorAll('tr.cam').forEach((tr) => (tr.onclick = () => selectCam(tr.dataset.cam, true)));
  const gaps = [];
  CC.readings.filter((r) => !r.used).forEach((r) => gaps.push(t('gap_notmapped', { id: r.cam_id, why: r.reasons.map(reasonText).join('; ') })));
  const ph = CC.readings.filter((r) => r.used && r.placeholder_location);
  if (ph.length) gaps.push(t('gap_placeholder', { ids: ph.map((r) => r.cam_id).join(', '), m: ph[0].loc_method }));
  if (CC.readings.some((r) => !r.capture_known)) gaps.push(t('gap_capture'));
  gaps.push(...CC.notes.map(noteText));
  $('cgaps').innerHTML = gaps.length ? `<details class="gapsd"><summary>${esc(t('c_notes', { n: gaps.length }))}</summary>${gaps.map((g) => `<div class="warnbox">${esc(g)}</div>`).join('')}</details>` : '';
}
const imgUrl = (cam, full) => A(`/api/dash/cctv/image?cam=${encodeURIComponent(cam)}${full ? '&full=1' : ''}&v=${S.CC ? S.CC.version : 0}`);
function latestReadings() {
  const m = {};
  for (const r of S.CC ? S.CC.readings : []) if (r.used && (!m[r.cam_id] || r.ts_utc > m[r.cam_id].ts_utc)) m[r.cam_id] = r;
  return m;
}
function drawCams() {
  for (const k of MK.cams) k.remove();
  MK.cams = [];
  if (!MAIN || !S.META) return;
  const lat = latestReadings(), reg = S.CAMS ? S.CAMS.features : [];
  const regById = Object.fromEntries(reg.map((f) => [f.properties.cam_id, f.properties]));
  if ($('showCams').checked) {
    for (const r of Object.values(lat)) {
      const el = document.createElement('div'), p = regById[r.cam_id] || {};
      el.className = 'camMk' + (p.has_image ? '' : ' dot') + (r.placeholder_location ? ' ph' : '');
      el.style.borderColor = CLS_HEX[r.cls] || '#111';
      if (p.has_image) el.style.backgroundImage = `url(${imgUrl(r.cam_id)})`; else el.style.background = CLS_HEX[r.cls];
      el.title = `${r.cam_id}: ${clsText(r.cls)}, ~${num(r.depth)} ${t('m')}`;
      el.addEventListener('click', (e) => { e.stopPropagation(); selectCam(r.cam_id, false); });
      MK.cams.push(new maplibregl.Marker({ element: el }).setLngLat([r.lon, r.lat]).addTo(MAIN));
    }
  }
  renderLegend();
}
function camPopup(r, p) {
  const has = p && p.has_image, hex = CLS_HEX[r.cls] || '#888';
  const html = `<div class="pop cam">${has ? `<img class="pimg" src="${imgUrl(r.cam_id)}" alt="${esc(r.cam_id)}" title="${esc(t('cam_click_full'))}">` : ''}
    <h4>${esc(r.cam_id)} <span class="badge" style="background:${hex};color:#222">${esc(clsText(r.cls))}</span></h4>
    <div><b>~${Math.round((r.depth || 0) * 100)} cm</b> (${num(r.depth)} ${esc(t('m'))}) · ${esc(t('cam_conf'))} ${num(r.conf)}</div>
    <div class="m">${esc(t('cam_proxy'))} · ${esc(fmtTime(r.time_ict))}</div>
    ${r.placeholder_location ? `<div class="m warnl">${esc(t('cam_placeholder'))}</div>` : ''}</div>`;
  const pp = openPopup([r.lon, r.lat], html, { maxWidth: '280px', offset: 28 });
  const el = pp.getElement();
  const im = el.querySelector('.pimg'); if (im) im.onclick = () => openLightbox(r.cam_id, r);
}
function selectCam(id, fly) {
  S.sel = id;
  const r = latestReadings()[id], f = S.CAMS && S.CAMS.features.find((x) => x.properties.cam_id === id);
  const ll = r && r.lat != null ? [r.lon, r.lat] : f ? f.geometry.coordinates : null;
  if (S.phase === 'during') renderCamCard();
  if (fly && ll) MAIN.flyTo({ center: ll, zoom: Math.max(MAIN.getZoom(), 13.5), duration: 1000 });
  if (r) camPopup(r, f && f.properties);
}
function renderCamCard() {
  const id = S.sel, card = $('camcard');
  if (!id || S.phase !== 'during') { card.classList.add('hide'); return; }
  const f = S.CAMS && S.CAMS.features.find((x) => x.properties.cam_id === id), p = f ? f.properties : { cam_id: id, name: id };
  const hist = (S.CC ? S.CC.readings : []).filter((r) => r.cam_id === id).sort((a, b) => a.ts_utc.localeCompare(b.ts_utc));
  const r = latestReadings()[id] || hist[hist.length - 1];
  card.classList.remove('hide');
  const close = () => { S.sel = null; card.classList.add('hide'); closePopup(); };
  let h = `<div class="camhead"><h3>${esc(p.cam_id)}</h3><button class="btn2 sm" id="camx" aria-label="close">&times;</button></div>`;
  if (!r) { h += `<p class="mute small">${esc(t('cam_reg'))}${p.is_mock ? ' · ' + esc(t('cam_mock')) : ''}</p>`; card.innerHTML = h; $('camx').onclick = close; return; }
  const bands = ['#64c864', '#e6c83c', '#e67828', '#c82828', '#7b0000'];
  const act = r.cls === 'NORMAL' ? 0 : r.cls === 'WATERLOGGING' ? 1 : r.cls === 'FLOODING' ? 2 : r.cls === 'SEVERE_FLOODING' ? ((r.depth || 0) >= 0.5 ? 4 : 3) : -1;
  const wp = r.wpct, wc = wp > 0.3 ? '#c82828' : wp > 0.1 ? '#e67828' : '#64c864';
  const probs = r.probs ? ['normal', 'waterlogging', 'flooding', 'severe', 'unusable'].filter((k) => r.probs[k] != null) : [];
  const pcol = { normal: 'NORMAL', waterlogging: 'WATERLOGGING', flooding: 'FLOODING', severe: 'SEVERE_FLOODING', unusable: 'UNUSABLE' };
  h += `<div class="camrow"><div>${p.has_image ? `<img id="camimg" src="${imgUrl(id)}" alt="${esc(id)}">` : `<div class="mute small">${esc(t('cam_noimg'))}</div>`}</div><div>
    <span class="badge" style="background:${CLS_HEX[r.cls]};color:#222">${esc(clsText(r.cls))}</span>
    <div class="mute small">${esc(fmtTime(r.time_ict))} ${getLang() === 'th' ? 'น.' : 'ICT'}</div>
    <div class="gauge">${bands.map((c, i) => `<i style="${i === act ? `background:${c};border-color:${c}` : ''}"></i>`).join('')}</div>
    <div class="gl"><span>0</span><span>5</span><span>15</span><span>30</span><span>50+ cm</span></div>
    <div class="small"><b style="color:${CLS_HEX[r.cls]}">~${Math.round((r.depth || 0) * 100)} cm</b> <span class="mute">${esc(t('cam_mid'))}</span></div>
    ${r.submerged ? `<div class="small" style="color:var(--l3)">${esc(t('cam_sub'))}</div>` : ''}
    ${wp != null ? `<div class="row small"><span class="mute">${esc(t('cam_wpx'))}</span><b style="color:${wc}">${(wp * 100).toFixed(0)}%</b><div class="bar2"><i style="width:${Math.min(wp * 100, 100)}%;background:${wc}"></i></div></div>` : ''}
    </div></div>
    <table class="camt"><tr><td>${esc(t('cam_conf'))}</td><td><b>${num(r.conf)}</b></td><td>${esc(t('cam_model'))}</td><td><b>${r.model_now != null ? num(r.model_now) + ' ' + esc(t('m')) : '–'}</b></td></tr>
    <tr><td>${esc(t('cam_district'))}</td><td colspan="3">${esc((getLang() === 'th' ? r.district_th : r.district) || '–')} (${num(r.district_km, 1)} ${esc(t('km'))})</td></tr></table>
    ${r.placeholder_location ? `<div class="warnbox">${esc(t('cam_placeholder'))}</div>` : ''}
    ${probs.length ? `<details><summary>${esc(t('cam_probs'))}</summary>${probs.map((k) => `<div class="prow"><span>${esc(t('p_' + k))}</span><div class="bar2"><i style="width:${(r.probs[k] || 0) * 100}%;background:${CLS_HEX[pcol[k]]}"></i></div><span>${Math.round((r.probs[k] || 0) * 100)}%</span></div>`).join('')}</details>` : ''}
    <div class="row" style="margin-top:6px"><button class="btn2 sm" id="camfly">${esc(t('cam_fly'))}</button></div>`;
  card.innerHTML = h;
  $('camx').onclick = close;
  $('camfly').onclick = () => selectCam(id, true);
  const im = $('camimg'); if (im) im.onclick = () => openLightbox(id, r);
}
function openLightbox(id, r) {
  $('lbimg').src = imgUrl(id, true);
  $('lbcap').textContent = `${id} · ${t('cam_proxy')} · ${fmtTime(r.time_ict)}`;
  $('lightbox').classList.remove('hide');
}
$('lbx').onclick = () => $('lightbox').classList.add('hide');
$('lightbox').addEventListener('click', (e) => { if (e.target === $('lightbox')) $('lightbox').classList.add('hide'); });
addEventListener('keydown', (e) => { if (e.key === 'Escape') { $('lightbox').classList.add('hide'); if (S.menuOpen) toggleMenu(false); } });

async function afterCctvChange() { await loadCctv(); await loadCameras(); loadAlerts(); refresh(); toast(t('cctv_updated')); }
$('csvup').onclick = async () => {
  const f = $('csvf').files[0];
  if (!f) { $('cstat').innerHTML = `<span class="err">${esc(t('choose_csv'))}</span>`; return; }
  try {
    $('cstat').textContent = t('importing');
    const r = await api('/api/dash/cctv/upload', await f.text(), true);
    $('cstat').innerHTML = esc(t('imported', { n: r.added })) + r.errors.map((e) => `<div class="warnbox">${esc(e)}</div>`).join('');
    await afterCctvChange();
  } catch (e) { $('cstat').innerHTML = `<span class="err">${esc(e.message)}</span>`; }
};
$('fpick').onclick = () => { S.picking = !S.picking; $('fpick').textContent = S.picking ? t('pick_click') : t('pick_map'); MAIN.getCanvas().style.cursor = S.picking ? 'crosshair' : ''; };
$('fadd').onclick = async () => {
  try {
    await api('/api/dash/cctv/add', { cam_id: $('fcam').value, cls: $('fcls').value, lat: $('flat').value, lon: $('flon').value, depth_m: $('fdep').value, confidence: $('fconf').value, notes: $('fnote').value });
    $('cstat').textContent = t('reading_added'); await afterCctvChange();
  } catch (e) { $('cstat').innerHTML = `<span class="err">${esc(e.message)}</span>`; }
};

// ------------------------------------------------------------------------------------------------ side cards
function renderAccuracy() {
  if (!S.META) return;
  const m = S.META.accuracy && S.META.accuracy.per_scenario;
  if (!m) { $('acc').innerHTML = ''; return; }
  const test = Object.values(m).filter((x) => x.split === 'test'), avg = (k) => test.reduce((a, x) => a + (x[k] || 0), 0) / Math.max(test.length, 1);
  $('acc').innerHTML = `<div class="tile"><div class="k">${esc(t('acc_rmse'))}</div><div class="v">${(avg('rmse') * 100).toFixed(1)} cm</div></div><div class="tile"><div class="k">${esc(t('acc_csi'))}</div><div class="v">${avg('csi').toFixed(2)}</div></div>
    <div class="tile"><div class="k">${esc(t('acc_area'))}</div><div class="v">${(test.reduce((a, x) => a + Math.abs(x.peak_area_err_pct || 0), 0) / Math.max(test.length, 1)).toFixed(1)} %</div></div>
    <div class="tile"><div class="k">${esc(t('model'))}</div><div class="v sm">${esc(S.META.model_version)}</div></div>`;
}
function renderProv() {
  const M = S.META; if (!M) return;
  const src = S.FC && S.FC.source, kv = (k, v) => `<div><span class="mute">${esc(t(k))}</span><b>${v}</b></div>`;
  const area = (M.patches.min_cells * (M.cell_m / 1000) ** 2).toFixed(1);
  $('prov').innerHTML = kv('prov_weather', src ? esc(src.kind === 'gfs' ? t('prov_weather_gfs', { cycle: src.cycle }) : t('prov_weather_demo')) : '…')
    + kv('prov_tide', esc(t('prov_tide_v'))) + kv('prov_model', `${esc(M.model_version)} · ${esc(M.device)}`)
    + kv('prov_grid', `${M.grid[1]} × ${M.grid[0]} · ${Math.round(M.cell_m)} ${esc(t('m'))}`)
    + kv('prov_filter', esc(t('prov_filter_v', { a: area }))) + kv('prov_cctv', esc(t('prov_cctv_v')));
}
function renderHealth(ok, h) {
  const el = $('health'); el.classList.toggle('ok', ok); el.classList.toggle('bad', !ok);
  $('healthtxt').textContent = ok ? `${t('online')}${h ? ' · ' + h.device : ''}` : t('offline');
  el.title = h ? `${t('model')} ${h.model_version} · ${t('device')} ${h.device}` : '';
}
async function pollHealth() {
  try {
    S.health = await api('/api/dash/health'); S.stage = S.health.stage; renderHealth(true, S.health);
    const h = S.health;     // a newer NOAA cycle (or hour) was computed in the background: pick it up without a reload
    if (!DEMO && S.FC && h.forecast_id && h.forecast_id !== S.FC.id && !S.loadingFC && h.forecast_source && h.forecast_source.kind === S.FC.source.kind) loadForecast(true);
  } catch (e) { renderHealth(false); }
}

// ------------------------------------------------------------------------------------------------ language: one synchronous re-render
function fillSelects() {
  const o = $('fcls').options; ['', 'WATERLOGGING', 'FLOODING', 'SEVERE_FLOODING', 'NORMAL'].forEach((v, i) => { o[i].textContent = v ? clsText(v) : t('f_from_depth'); });
}
function renderAll() {
  applyStatic();
  tickClock(); renderBanner(); fillSelects();
  renderLayerButtons(); setCmpLabels();
  $('cmpbtn').textContent = S.cmp.on ? t('compare_off') : t('compare');
  $('fpick').textContent = S.picking ? t('pick_click') : t('pick_map');
  renderHealth(!!S.health, S.health);
  renderForecast(); renderAlertButton(); renderAlertMenu(); renderFeed();
  renderCctv(); renderCamCard(); renderAccuracy(); renderProv();
  renderLegend(); timeLabel(); renderPoint(); renderCell(); updateZoomBadge();
  $('thr').dispatchEvent(new Event('input')); $('sig').dispatchEvent(new Event('input'));
  if (S.loadingFC) renderLoading();
  closePopup();
  drawDistricts(); drawCams(); drawCharts();
  // isStyleLoaded() is false while tiles are still loading, which would skip the relabel: only need the style itself
  for (const m of [MAIN, CMP]) if (m) { try { setLabelLanguage(m); } catch (e) { /* style still being swapped: style.load relabels */ } }
}
function changeLang(l) {
  if (l === getLang()) return;
  setLang(l);
  document.querySelectorAll('.lang button').forEach((b) => b.classList.toggle('on', b.dataset.lang === l));
  document.body.classList.add('langswap');
  renderAll();
  setTimeout(() => document.body.classList.remove('langswap'), 220);
}

// ------------------------------------------------------------------------------------------------ wiring
document.querySelectorAll('#phase button').forEach((b) => (b.onclick = () => setPhase(b.dataset.p)));
document.querySelectorAll('.lang button').forEach((b) => (b.onclick = () => changeLang(b.dataset.lang)));
document.querySelectorAll('#viewseg button').forEach((b) => (b.onclick = () => setView(b.dataset.v)));
$('basemap').onchange = () => setBasemap($('basemap').value);
$('showDist').onchange = drawDistricts; $('showCams').onchange = drawCams;
$('showBld').onchange = () => { for (const m of [MAIN, CMP]) if (m && m.getLayer('building-3d')) m.setLayoutProperty('building-3d', 'visibility', $('showBld').checked ? 'visible' : 'none'); };
for (const [k, f] of [['thr', (v) => (+v).toFixed(2) + ' ' + t('m')], ['sig', (v) => (+v).toFixed(2) + ' ' + t('km')], ['terx', (v) => '×' + v], ['wax', (v) => '×' + v]]) {
  const u = () => { $('v_' + k).textContent = f($(k).value); };
  $(k).addEventListener('input', u); u();
}
$('thr').addEventListener('change', () => { refresh(); });
$('sig').addEventListener('change', () => { refresh(); });
$('terx').addEventListener('input', () => { S.terX = +$('terx').value; store.set('terx', S.terX); for (const m of [MAIN, CMP]) if (m && S.view3d && m.getTerrain()) m.setTerrain({ source: 'dem', exaggeration: S.terX }); });
$('wax').addEventListener('input', () => { S.waterX = +$('wax').value; store.set('wax', S.waterX); for (const m of [MAIN, CMP]) if (m && m.getLayer('fd-3d')) m.setPaintProperty('fd-3d', 'fill-extrusion-height', ['*', ['get', 'd'], S.waterX]); });
$('cmpbtn').onclick = () => setCompare(!S.cmp.on);
$('cmpmode').onchange = () => { S.cmp.mode = $('cmpmode').value; store.set('cmpmode', S.cmp.mode); setCmpLabels(); updateOverlays(); };
$('time').addEventListener('input', () => { if (S.layer === 'max') setLayer('depth'); else refresh(); });
$('time').addEventListener('change', () => { if (S.phase === 'during') loadAlerts(); });
$('nowbtn').onclick = () => S.FC && setT(liveIdx());
document.querySelectorAll('#wxmode button').forEach((b) => (b.onclick = () => setSource(b.dataset.m)));
$('play').onclick = () => {
  if (!S.FC) return;
  if (S.playing) { stopPlay(); return; }
  if (S.layer === 'max' || S.layer === 'cctv') setLayer(S.phase === 'during' ? 'fused' : 'depth');
  S.playing = true; $('play').innerHTML = '&#10074;&#10074;';
  if (+$('time').value >= T() - 1) $('time').value = 0;
  step();
};
$('alertbtn').onclick = (e) => { e.stopPropagation(); toggleMenu(); };
$('amq').addEventListener('input', renderAlertMenu);
document.addEventListener('click', (e) => { if (S.menuOpen && !$('alertwrap').contains(e.target)) toggleMenu(false); });
$('bReset').onclick = resetView;
$('bNorth').onclick = () => MAIN.easeTo({ bearing: 0, pitch: S.view3d ? MAIN.getPitch() : 0, duration: 500 });
$('bFull').onclick = () => { const w = $('mapwrap'); if (document.fullscreenElement) document.exitFullscreen(); else w.requestFullscreen && w.requestFullscreen(); };
document.addEventListener('fullscreenchange', () => { MAIN && MAIN.resize(); CMP && CMP.resize(); });
addEventListener('resize', () => { clearTimeout(drawCharts.h); drawCharts.h = setTimeout(drawCharts, 150); });
setInterval(tickClock, 20000);

// ------------------------------------------------------------------------------------------------ init
(async function init() {
  setLang(getLang());
  document.querySelectorAll('.lang button').forEach((b) => b.classList.toggle('on', b.dataset.lang === getLang()));
  document.body.classList.toggle('v3d', S.view3d);
  document.querySelectorAll('#viewseg button').forEach((b) => b.classList.toggle('on', b.dataset.v === (S.view3d ? '3d' : '2d')));
  $('basemap').value = S.basemap; $('terx').value = S.terX; $('wax').value = S.waterX; $('cmpmode').value = S.cmp.mode;
  applyStatic(); tickClock(); renderBanner(); renderAlertButton(); renderForecast();
  for (const k of ['terx', 'wax']) $(k).dispatchEvent(new Event('input'));
  $('maploading').classList.remove('hide'); $('loadmsg').textContent = t('loading');
  try {
    S.META = await api('/api/dash/meta');
    await pollHealth();
    fillSelects(); applyStatic(); renderAccuracy(); renderProv();
    MAIN = makeMap('map', 'main');
    MAIN.on('mousemove', onMove); MAIN.on('click', onClick);
    MAIN.on('zoom', updateZoomBadge); MAIN.on('load', () => { resetView(); updateZoomBadge(); });
    MAIN.on('moveend', () => { if (S.view3d) update3d(); });
    setPhase(S.phase);
    loadCctv().catch((e) => { $('ctable').innerHTML = `<span class="err">${esc(e.message)}</span>`; });
    loadCameras().catch(() => {});
    loadForecast();
    setInterval(pollCctv, 15000); setInterval(pollHealth, 20000);
  } catch (e) { $('loadmsg').textContent = e.message; renderHealth(false); }
})();

window.__fd = { S, get map() { return MAIN; }, get cmp() { return CMP; }, setView, setCompare, changeLang, selectCam, toggleMenu }; // handy for the console / tests
