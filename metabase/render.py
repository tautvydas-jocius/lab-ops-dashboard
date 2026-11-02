"""Screenshot every Metabase dashboard to docs/renders/*.png for the README.

Logs in through the API, hands the session cookie to headless Chromium, waits for
all cards to finish loading. Usage: MB_ADMIN_PASSWORD=... python3 render.py
"""
import json
import os
import re
import urllib.request

from playwright.sync_api import sync_playwright

MB = os.environ.get("MB_URL", "http://127.0.0.1:3300")
OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "renders")
os.makedirs(OUT, exist_ok=True)


def api(method, path, body=None, session=None):
    req = urllib.request.Request(MB + path, json.dumps(body).encode() if body else None,
                                 {"Content-Type": "application/json", **({"X-Metabase-Session": session} if session else {})},
                                 method=method)
    return json.loads(urllib.request.urlopen(req).read())


session = api("POST", "/api/session", {"username": os.environ.get("MB_ADMIN_EMAIL", "admin@example.com"),
                                       "password": os.environ["MB_ADMIN_PASSWORD"]})["id"]
dashboards = sorted((d for d in api("GET", "/api/dashboard", session=session) if d["name"][0].isdigit()),
                    key=lambda d: d["name"])  # skip Metabase's bundled sample dashboard

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1600, "height": 2600}, device_scale_factor=2, bypass_csp=True)
    ctx.add_cookies([{"name": "metabase.SESSION", "value": session, "url": MB}])
    page = ctx.new_page()
    for d in dashboards:
        page.goto(f"{MB}/dashboard/{d['id']}", wait_until="networkidle")
        page.wait_for_selector("[data-testid='dashcard']", timeout=60000)
        page.wait_for_function("!document.querySelector('[data-testid=\"loading-indicator\"], .LoadingSpinner')",
                               timeout=60000)
        page.wait_for_timeout(1500)  # chart transitions
        grid = page.locator("[data-testid='dashboard-grid'], .react-grid-layout").first
        slug = re.sub(r"[^a-z0-9]+", "-", d["name"].lower()).strip("-")
        path = os.path.join(OUT, f"{slug}.png")
        grid.screenshot(path=path)
        print(path)
    browser.close()
