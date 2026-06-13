"""Captures README — design VELOURS (lancé dans l'image probe via Docker).

Usage : python readme_screenshots.py <base_url> <email> <password> <out_dir>
"""

import sys

from playwright.sync_api import sync_playwright

base, email, password, out = sys.argv[1:5]
VIEWPORT = {"width": 1440, "height": 900}


def shot(page, name, settle_ms=1600):
    page.wait_for_timeout(settle_ms)  # animations d'entrée + données WS
    page.screenshot(path=f"{out}/{name}.png")
    print("captured", name, flush=True)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport=VIEWPORT, ignore_https_errors=True, locale="en-GB")
    page = ctx.new_page()

    # Login via l'UI réelle
    page.goto(f"{base}/login", wait_until="networkidle")
    page.fill('input[type="email"], input[autocomplete="username"], form input:not([type="password"])', email)
    page.fill('input[type="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{base}/", timeout=15000)

    # Dashboard — sombre (défaut) puis clair
    page.goto(f"{base}/", wait_until="networkidle")
    shot(page, "dashboard")
    page.click('button[aria-label="Toggle theme"]')
    shot(page, "dashboard-light")
    page.click('button[aria-label="Toggle theme"]')

    # Monitors
    page.goto(f"{base}/monitors", wait_until="networkidle")
    shot(page, "monitors-view")

    # Monitor detail (ID passé en argument optionnel, sinon premier lien visible)
    monitor_id = sys.argv[5] if len(sys.argv) > 5 else None
    if monitor_id:
        page.goto(f"{base}/monitors/{monitor_id}", wait_until="networkidle")
    else:
        page.locator('a[href*="/monitors/"]:visible').first.click()
        page.wait_for_load_state("networkidle")
    shot(page, "monitor-detail")

    # Probes (carte Leaflet — tuiles plus lentes)
    page.goto(f"{base}/probes", wait_until="networkidle")
    shot(page, "probes-map", settle_ms=3000)

    # Status page publique (onglet propre, sans auth)
    pub = ctx.new_page()
    pub.goto(f"{base}/status/telegmi", wait_until="networkidle")
    shot(pub, "public-status")

    browser.close()
