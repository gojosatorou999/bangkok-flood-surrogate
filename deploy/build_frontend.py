"""Build the static front end for Vercel (or any static host) into ./frontend.

    python3 deploy/build_frontend.py            # on Vercel: Build Command; Output Directory = frontend

Result:  /            the flood dashboard         (dashboard.html)
         /workbench   the model workbench         (index.html)
         /static/...  MapLibre, scripts, styles
The pages call the API on the same origin (/api/..., which vercel.json rewrites to the AWS backend). To call the backend
directly instead, set the environment variable FD_API_BASE=https://your-api-host when building; it is written to
static/dash/config.js and the backend then needs FLOOD_CORS_ORIGINS=https://your-site.
"""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'frontend'


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    dash = (ROOT / 'dashboard.html').read_text(encoding='utf-8')
    wb = (ROOT / 'index.html').read_text(encoding='utf-8')
    # on the static site the dashboard is the home page and the workbench lives at /workbench
    assert 'href="/" id="wblink"' in dash, 'dashboard.html: workbench link not found'
    assert 'href="/dashboard"' in wb, 'index.html: dashboard link not found'
    (OUT / 'index.html').write_text(dash.replace('href="/" id="wblink"', 'href="/workbench" id="wblink"'), encoding='utf-8')
    (OUT / 'workbench.html').write_text(wb.replace('href="/dashboard"', 'href="/"'), encoding='utf-8')
    shutil.copytree(ROOT / 'static', OUT / 'static', ignore=shutil.ignore_patterns('leaflet'))
    base = os.environ.get('FD_API_BASE', '').strip().rstrip('/')
    if base:
        (OUT / 'static' / 'dash' / 'config.js').write_text(f"window.FD_API_BASE = {base!r};\n".replace("'", '"'), encoding='utf-8')
    n = sum(1 for p in OUT.rglob('*') if p.is_file())
    print(f'frontend built: {n} files in {OUT}' + (f', API base {base}' if base else ', API on the same origin'))


if __name__ == '__main__':
    main()
