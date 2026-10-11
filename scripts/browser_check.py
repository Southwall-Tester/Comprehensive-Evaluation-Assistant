"""Real local UI smoke test (Edge), without mocked model or backend responses."""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
ART.mkdir(exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8768", wait_until="networkidle")
    expect(page.locator("#policy-select")).to_have_value("44274322bad3478c8fa6685c1bb794c0")
    page.screenshot(path=str(ART / "desktop-workspace.png"), full_page=True)
    for tab in ["rules", "score", "opportunities", "plans", "settings"]:
        page.locator(f'nav [data-page="{tab}"]').click()
        expect(page.locator("h1")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), tab
    page.locator('nav [data-page="score"]').click()
    page.locator('[data-act="calculate"]').click()
    expect(page.locator(".score-number")).to_have_text("80.02", timeout=15000)
    page.screenshot(path=str(ART / "desktop-score.png"), full_page=True)
    course = page.locator('[data-table="courses"][data-row="0"][data-column="score"]')
    course.fill("80")
    page.locator('[data-act="calculate"]').click()
    expect(page.locator(".score-number")).to_have_text("72.52")
    course = page.locator('[data-table="courses"][data-row="0"][data-column="score"]')
    course.fill("90")
    page.locator('[data-act="calculate"]').click()
    expect(page.locator(".score-number")).to_have_text("80.02")
    page.locator('[data-act="ledger"]').click()
    expect(page.locator("#dialog")).to_be_visible()
    page.locator('#dialog [data-act="source"]').first.click()
    expect(page.locator("#source-unit")).to_be_visible()
    page.screenshot(path=str(ART / "desktop-source.png"), full_page=True)
    page.locator('#dialog [data-act="close"]').click()
    page.locator('nav [data-page="opportunities"]').click()
    page.locator('[data-act="notice"][data-id="b587fb2dc1d44883895017aef91536be"]').click()
    expect(page.locator("#notice-question")).to_be_visible()
    assert page.locator('#dialog [data-act="source"]').count() >= 11
    page.screenshot(path=str(ART / "desktop-notice.png"), full_page=True)
    page.locator('#dialog [data-act="close"]').click()
    page.locator('nav [data-page="plans"]').click()
    page.locator('[data-act="add-plan"]').click()
    page.locator("#plan-title").fill("浏览器验收临时任务")
    page.locator("#plan-date").fill("2026-10-11")
    page.locator('[data-act="save-plan"]').click()
    expect(page.locator(".timeline-item").filter(has_text="浏览器验收临时任务")).to_be_visible()
    page.locator(".timeline-item").filter(has_text="浏览器验收临时任务").locator(
        '[data-act="remove-plan"]'
    ).click()
    expect(page.locator(".timeline-item").filter(has_text="浏览器验收临时任务")).to_have_count(0)
    page.set_viewport_size({"width": 390, "height": 844})
    for tab in ["home", "rules", "score", "opportunities", "plans", "settings"]:
        page.locator(f'nav [data-page="{tab}"]').click()
        expect(page.locator("h1")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"mobile {tab}"
        if tab == "score":
            page.screenshot(path=str(ART / "mobile-score.png"), full_page=True)
    assert not errors, errors
    (ART / "browser-check.json").write_text(
        json.dumps(
            {
                "pages": 6,
                "viewports": ["1440x1000", "390x844"],
                "score": 80.02,
                "javascript_errors": errors,
                "status": "passed",
            },
            indent=2,
        ),
        encoding="utf8",
    )
    browser.close()
    print("BROWSER_PASS: six sections, desktop/mobile, score80.02, source viewer, 11 notice files, plan CRUD")
