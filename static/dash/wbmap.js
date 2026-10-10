// Shared MapLibre helper for the model workbench (index.html): the same basemaps, domain outline, cell highlight and
// flood-overlay mechanics as the dashboard, exposed as window.WB. The workbench script is a classic script, so it waits
// for `window.WB_READY` (a promise) before touching maps.
import * as ML from '/static/maplibre/maplibre-gl.mjs';

const maplibregl = ML.default ?? ML;
const BLANK = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg==';
const rs = (tiles, attribution, maxzoom = 19, extra = []) => ({
  version: 8, sources: { base: { type: 'raster', tiles, tileSize: 256, maxzoom, attribution }, ...Object.fromEntries(extra.map((e, i) => [`x${i}`, { type: 'raster', tiles: [e], tileSize: 256, maxzoom: 19 }])) },
  layers: [{ id: 'base', type: 'raster', source: 'base' }, ...extra.map((_, i) => ({ id: `x${i}`, type: 'raster', source: `x${i}` }))],
});
export const BASEMAPS = {
  streets: () => 'https://tiles.openfreemap.org/styles/liberty',
  satellite: () => rs(['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], 'Imagery © Esri, Maxar, Earthstar Geographics', 19,
    ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}']),
  light: () => rs(['a', 'b', 'c', 'd'].map((s) => `https://${s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png`), '© OpenStreetMap contributors © CARTO', 20),
  dark: () => rs(['a', 'b', 'c', 'd'].map((s) => `https://${s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png`), '© OpenStreetMap contributors © CARTO', 20),
  osm: () => rs(['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], '© OpenStreetMap contributors', 19),
};
const emptyFC = { type: 'FeatureCollection', features: [] };
const store = { get(k) { try { return localStorage.getItem('fd_' + k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem('fd_' + k, v); } catch (e) {} } };

let META = null;
const maps = new Set();
const coords = () => { const [[la0, lo0], [la1, lo1]] = META.bounds; return [[lo0, la1], [lo1, la1], [lo1, la0], [lo0, la0]]; };
const lang = () => { try { return localStorage.getItem('fd_lang') === 'th' ? 'th' : 'en'; } catch (e) { return 'en'; } };

function labels(m) {
  const th = lang() === 'th';
  const expr = th ? ['coalesce', ['get', 'name:th'], ['get', 'name'], ['get', 'name_en']] : ['coalesce', ['get', 'name_en'], ['get', 'name:en'], ['get', 'name:latin'], ['get', 'name']];
  for (const l of m.getStyle().layers) {
    if (l.type !== 'symbol' || !l.layout || !l.layout['text-field'] || l.id.startsWith('wb-')) continue;
    if (!JSON.stringify(l.layout['text-field']).includes('name')) continue;
    try { m.setLayoutProperty(l.id, 'text-field', expr); } catch (e) {}
  }
}

function install(m) {
  const before = (m.getStyle().layers.find((l) => l.type === 'symbol') || {}).id;
  if (!m.getSource('wb-img')) m.addSource('wb-img', { type: 'image', url: BLANK, coordinates: coords() });
  if (!m.getLayer('wb-flood')) m.addLayer({ id: 'wb-flood', type: 'raster', source: 'wb-img', paint: { 'raster-opacity': 0.92, 'raster-fade-duration': 0, 'raster-resampling': m.__hi ? 'nearest' : 'linear' } }, before);
  if (!m.getSource('wb-domain')) m.addSource('wb-domain', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'LineString', coordinates: [...META.outline, META.outline[0]].map(([la, lo]) => [lo, la]) } } });
  if (!m.getLayer('wb-domain')) m.addLayer({ id: 'wb-domain', type: 'line', source: 'wb-domain', paint: { 'line-color': '#7a8794', 'line-width': 1.2, 'line-dasharray': [3, 3] } });
  if (!m.getSource('wb-cell')) m.addSource('wb-cell', { type: 'geojson', data: emptyFC });
  if (!m.getLayer('wb-cell-fill')) {
    m.addLayer({ id: 'wb-cell-fill', type: 'fill', source: 'wb-cell', paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.2 } });
    m.addLayer({ id: 'wb-cell-line', type: 'line', source: 'wb-cell', paint: { 'line-color': '#111', 'line-width': 2 } });
  }
  labels(m);
  if (m.__lastUrl) paint(m, m.__lastUrl);
}

/** Create a map in `container` (an element). Returns the MapLibre map; call .wbReady to know when the style is loaded. */
export function create(container, opts = {}) {
  const m = new maplibregl.Map({ container, style: BASEMAPS[store.get('basemap') || 'streets'](), center: META.center, zoom: 9.7, maxZoom: 22, minZoom: 6,
    attributionControl: { compact: true }, ...opts });
  m.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: false }), 'top-left');
  m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
  m.on('style.load', () => install(m));
  m.on('error', (e) => { if (e && e.error && !/(tile|404|Failed to fetch|aborted)/i.test(String(e.error.message || e.error))) console.warn('map', e.error); });
  maps.add(m);
  return m;
}

const tokens = new WeakMap();
/** Show a Web-Mercator PNG over the model domain; resolves when it is on the map (or failed). `null` clears. */
export function paint(m, url) {
  m.__lastUrl = url;
  if (!m.getSource('wb-img')) return Promise.resolve();
  const tok = (tokens.get(m) || 0) + 1; tokens.set(m, tok);
  return new Promise((res) => {
    if (!url) { m.getSource('wb-img').updateImage({ url: BLANK, coordinates: coords() }); return res(true); }
    const im = new Image();
    im.onload = () => { if (tokens.get(m) === tok && m.getSource('wb-img')) m.getSource('wb-img').updateImage({ url, coordinates: coords() }); res(true); };
    im.onerror = () => res(false);
    im.src = url;
  });
}
export function setHi(m, hi) {
  m.__hi = hi;
  if (m.getLayer('wb-flood')) m.setPaintProperty('wb-flood', 'raster-resampling', hi ? 'nearest' : 'linear');
}
export function highlight(m, ring) {
  const s = m.getSource('wb-cell'); if (!s) return;
  s.setData(ring ? { type: 'Feature', geometry: { type: 'Polygon', coordinates: [ring] }, properties: {} } : emptyFC);
}
export function setBasemap(name) {
  store.set('basemap', name);
  for (const m of maps) m.setStyle(BASEMAPS[name](), { diff: false });
}
export const basemap = () => store.get('basemap') || 'streets';
// isStyleLoaded() is false while tiles load; the style object is all that is needed (a swap in progress relabels on style.load)
export function relabel() { for (const m of maps) { try { labels(m); } catch (e) {} } }
export function marker(lnglat, el) { return new maplibregl.Marker({ element: el, anchor: 'center' }).setLngLat(lnglat); }
export function fit(m, pad = 20) {
  const [[la0, lo0], [la1, lo1]] = META.bounds;
  m.fitBounds([[lo0, la0], [lo1, la1]], { padding: pad, duration: 700 });
}
/** Keep two maps' cameras locked together. */
export function link(a, b) {
  let busy = false;
  const sync = (x, y) => x.on('move', () => { if (busy) return; busy = true; y.jumpTo({ center: x.getCenter(), zoom: x.getZoom(), bearing: x.getBearing(), pitch: x.getPitch() }); busy = false; });
  sync(a, b); sync(b, a);
}
/** metres per screen pixel at the map centre */
export function mpp(m) { return 78271.517 * Math.cos((m.getCenter().lat * Math.PI) / 180) / Math.pow(2, m.getZoom()); }

fetch(String(window.FD_API_BASE || '').replace(/\/$/, '') + '/api/dash/meta').then((r) => r.json()).then((meta) => {
  META = meta;
  window.WB = { create, paint, setHi, highlight, setBasemap, basemap, relabel, marker, fit, link, mpp, BASEMAPS, meta, maplibregl };
  window.__wbResolve && window.__wbResolve(window.WB);
}).catch((e) => { console.error('wbmap', e); window.__wbReject && window.__wbReject(e); });
