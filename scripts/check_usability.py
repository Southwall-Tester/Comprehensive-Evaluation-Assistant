"""Exercise daily workflows in an isolated copy; never call a model or mutate local data."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
SAMPLE = "acceptance-fictional"
OTHER = "usability-other-fictional"
EMPTY = "usability-empty-fictional"
PROPOSAL = "usability-proposal-fictional"
COURSE = '[data-table="courses"][data-row="0"][data-column="score"]'


def put(connection, kind, obj):
    connection.execute(
        "INSERT OR REPLACE INTO objects VALUES (?,?,?)",
        (kind, obj["id"], json.dumps(obj, ensure_ascii=False)),
    )


def get_profile(folder, profile_id):
    with sqlite3.connect(folder / "workspace.sqlite") as connection:
        row = connection.execute(
            "SELECT body FROM objects WHERE kind='profile' AND id=?", (profile_id,)
        ).fetchone()
    assert row is not None, "The isolated fixture profile must exist"
    return json.loads(row[0])


def prepare_workspace(folder):
    source = ROOT / ".local" / "workspace.sqlite"
    assert source.exists(), "This check requires the reviewed local acceptance workspace"
    # SQLite backup also captures a possible WAL without writing to the source DB.
    with (
        sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original,
        sqlite3.connect(folder / "workspace.sqlite") as copy,
    ):
        original.backup(copy)
        row = copy.execute(
            "SELECT body FROM objects WHERE kind='profile' AND id=?", (SAMPLE,)
        ).fetchone()
        assert row is not None, "Run the fictional acceptance setup before this check"
        sample = json.loads(row[0])
        sample["name"] = "验证样例（虚构数据）"
        sample["tables"]["courses"][0]["score"] = 90
        sample["tables"]["courses"][1]["score"] = 90
        other = deepcopy(sample)
        other.update(id=OTHER, name="切换验证（虚构数据）")
        other["tables"]["courses"][0]["score"] = 85
        empty = dict(
            id=EMPTY, name="我的测评", policy_id=sample["policy_id"],
            inputs={}, tables={}, items=[], period_start="", period_end="",
        )
        policy_row = copy.execute(
            "SELECT body FROM objects WHERE kind='policy' AND id=?", (sample["policy_id"],)
        ).fetchone()
        policy = json.loads(policy_row[0])
        document_ids = policy.get("document_ids", [])[:1]
        for document_id in document_ids:
            doc_row = copy.execute(
                "SELECT body FROM objects WHERE kind='document' AND id=?", (document_id,)
            ).fetchone()
            if doc_row:
                document = json.loads(doc_row[0])
                document["source_url"] = ""
                put(copy, "document", document)
        # Keep only named fictional profiles in the temporary copy and screenshots.
        copy.execute("DELETE FROM objects WHERE kind IN ('profile','calculation','proposal','job')")
        for profile in (other, empty, sample):
            put(copy, "profile", profile)
        proposal = dict(
            id=PROPOSAL, profile_id=EMPTY, document_ids=document_ids,
            proposal=dict(
                inputs={"deduct_1": None, "all_required_done": None},
                tables={"courses": [
                    dict(_label="保留课程", score=None, credits="", kind=None, status="", selected=None),
                    dict(_label="排除课程", score=95, credits=2, kind="其他选修或辅修",
                         status="正常", selected=True),
                ]},
                items=[dict(
                    name="提取的虚构成果", rule_id="discipline_competition", date="",
                    conflict_key="", evidence="验收专用虚构材料，未完成人工核对",
                    values=dict(class_id="B", level="全国", award="一等", member_rank=None,
                                special=None, eligible=None),
                )],
                questions=["成绩、学分、队员排名与资格尚未提供，请保留为空。"],
            ),
        )
        put(copy, "proposal", proposal)
    # Read credentials only to copy settings. Never log or return the configuration.
    settings_path = ROOT / ".local" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf8")) if settings_path.exists() else {}
    settings["auto_research"] = False
    (folder / "settings.json").write_text(json.dumps(settings, ensure_ascii=False), encoding="utf8")
    return sample["policy_id"], proposal


def wait_ready(process, base):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        assert process.poll() is None, "The isolated server exited before becoming healthy"
        try:
            with urlopen(base + "/health", timeout=1) as response:
                if json.load(response).get("ok"):
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError("The isolated server did not become healthy within 45 seconds")


def nav(page, name):
    direct = page.locator(f'nav [data-act="nav"][data-page="{name}"]')
    if direct.count():
        direct.click()
    else:
        page.locator('nav [data-act="nav"][data-page="more"]').click()
        page.locator(f'#main [data-act="nav"][data-page="{name}"]').click()
    expect(page.locator("h1")).to_be_visible()


def select_profile(page, profile_id):
    page.locator("#profile-select").select_option(profile_id)
    page.wait_for_function("id => U()?.id === id", arg=profile_id)


def score(page, value):
    expect(page.locator(".score-number")).to_have_text(f"{value:.2f}", timeout=15000)


def check_proposal(page, folder, proposal):
    """Selectors intentionally target the user-facing review controls, not raw JSON."""
    select_profile(page, EMPTY)
    page.locator('#main [data-act="extract-records"]').first.click()
    expect(page.locator("#record-upload")).to_be_visible()
    expect(page.locator("#record-upload")).to_have_attribute("type", "file")
    expect(page.locator("#profile-select")).to_have_value(EMPTY)
    page.locator('#dialog [data-act="close"]').click()
    page.locator('#main [data-act="add-item"]').click()
    page.locator("#item-name").fill("正在编辑而未保存的虚构成果")
    page.evaluate("draft => queueProposalReview(draft)", proposal)
    expect(page.locator("#item-name")).to_have_value("正在编辑而未保存的虚构成果")
    expect(page.locator("#record-review")).to_have_count(0)
    page.locator('#dialog [data-act="close"]').click()
    expect(page.locator("#record-review")).to_be_visible()
    page.locator('[data-review-item="0"] [data-review-meta="name"]').fill("暂停核对时保留的名称")
    page.locator('#dialog [data-act="close"]').click()
    expect(page.locator("#record-review-inbox")).to_be_visible()
    page.locator("#record-review-inbox").click()
    expect(page.locator('[data-review-item="0"] [data-review-meta="name"]')).to_have_value("暂停核对时保留的名称")
    expect(page.locator("#dialog")).to_be_visible()
    expect(page.locator("#proposal-json")).to_have_count(0)
    expect(page.locator("#dialog")).to_contain_text("成绩")
    expect(page.locator("#dialog")).to_contain_text("学分")
    expect(page.locator("#dialog")).to_contain_text("队员排名")
    page.locator('[data-review-row="1"] [data-review-keep]').uncheck()
    item_card = page.locator('[data-review-item="0"]')
    item_card.locator('[data-review-meta="name"]').fill("人工改名的虚构成果")
    expect(item_card.locator('[data-review-value="member_rank"]')).to_have_value("")
    expect(item_card.locator('[data-review-value="eligible"]')).to_have_value("")
    item_card.locator('[data-review-rule]').select_option("certification")
    expect(item_card.locator('[data-review-value="level"]')).to_have_value("")
    item_card.locator('[data-review-rule]').select_option("discipline_competition")
    expect(item_card.locator('[data-review-value="level"]')).to_have_value("全国")
    if proposal["document_ids"]:
        source = page.locator('#record-review > .citations a').first
        expect(source).to_have_attribute("target", "_blank")
        with page.expect_popup() as opened:
            source.click()
        opened.value.close()
        expect(page.locator("#dialog")).to_be_visible()
        expect(item_card.locator('[data-review-meta="name"]')).to_have_value("人工改名的虚构成果")
    page.locator('#dialog [data-act="apply-proposal"]').click()
    expect(page.locator("#dialog")).not_to_be_visible()
    profile = get_profile(folder, EMPTY)
    assert len(profile["tables"]["courses"]) == 1, "Excluded proposal rows must not enter the record"
    row = profile["tables"]["courses"][0]
    assert row.get("_label") == "保留课程"
    for key in ("score", "credits", "kind", "status", "selected"):
        assert row.get(key) in (None, ""), f"Missing course {key} must remain unknown"
    assert profile["inputs"].get("deduct_1") in (None, "")
    assert profile["inputs"].get("all_required_done") in (None, "")
    assert len(profile["items"]) == 1
    item = profile["items"][0]
    assert item["name"] == "人工改名的虚构成果"
    assert item["state"] == "pending", "Adding an extracted record is not confirmation"
    for key in ("member_rank", "special", "eligible"):
        assert item["values"].get(key) in (None, ""), f"Missing item {key} must not acquire a default"
    expect(page.locator('#main [data-act="edit-item"][data-index="0"]')).to_be_visible()
    page.locator('#main [data-act="edit-item"][data-index="0"]').click()
    page.locator("#item-name").fill("再次改名的虚构成果")
    page.locator('[data-act="save-item"]').click()
    expect(page.locator("#dialog")).not_to_be_visible()
    edited = get_profile(folder, EMPTY)["items"][0]
    assert edited["name"] == "再次改名的虚构成果"
    assert edited["state"] == "pending"
    for key in ("member_rank", "special", "eligible"):
        assert edited["values"].get(key) in (None, ""), f"Editing only a name must preserve unknown {key}"
    unknown = deepcopy(proposal)
    unknown["id"] += "-unknown"
    unknown["proposal"]["items"][0]["rule_id"] = "unknown-test-rule"
    page.evaluate("draft => openProposal(draft)", unknown)
    error = page.evaluate("() => { try {readProposalReview();return '';} catch(e) {return e.message;} }")
    assert "选择类别" in error, "An unknown rule must require a user choice before adding an item"
    page.locator('[data-review-item="0"] [data-review-keep]').uncheck()
    assert page.evaluate("readProposalReview().items.length") == 0
    page.locator('#dialog [data-act="close"]').click()


def run_browser(base, folder, policy_id, proposal, checks):
    blocked = []
    errors = []
    calculations = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            # No browser request may invoke a model, fetch research, or leave this server.
            def guard(route):
                request = route.request
                parsed = urlsplit(request.url)
                path = parsed.path
                allowed_write = (
                    re.fullmatch(r"/api/profiles/[^/]+(?:/calculate)?", path)
                    or re.fullmatch(r"/api/proposals/[^/]+/apply", path)
                )
                if request.url.startswith(base + "/") and (
                    request.method in {"GET", "HEAD"} or allowed_write
                ):
                    if path.endswith("/calculate"):
                        calculations.append(path.split("/")[-2])
                    route.continue_()
                else:
                    blocked.append(path)
                    route.abort("blockedbyclient")

            context.route("**/*", guard)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(
                "localStorage.setItem('cea-policy', " + json.dumps(policy_id) + ");"
                "localStorage.setItem('cea-profile', " + json.dumps(EMPTY) + ");"
                "localStorage.setItem('cea-page', 'home');"
            )
            page.goto(base, wait_until="networkidle")
            expect(page.locator("#profile-select")).to_have_value(EMPTY)
            nav(page, "score")
            expect(page.locator(".score-number")).to_have_text("—")
            assert EMPTY not in calculations, "Empty records must not calculate a fictional starting score"
            checks.append("An empty record shows no invented score")

            select_profile(page, SAMPLE)
            score(page, 80.02)
            checks.append("The existing fictional sample calculates 80.02 without an extra click")
            course = page.locator(COURSE)
            course.fill("80")
            score(page, 72.52)
            expect(course).to_be_focused()
            assert get_profile(folder, SAMPLE)["tables"]["courses"][0]["score"] == 80
            checks.append("Changing a grade saves and calculates 72.52 while preserving input focus")

            # Switch before the debounce has expired. The pending edit belongs to SAMPLE.
            course.fill("88")
            select_profile(page, OTHER)
            score(page, 76.27)
            expect(page.locator(COURSE)).to_have_value("85")
            assert get_profile(folder, SAMPLE)["tables"]["courses"][0]["score"] == 88
            assert get_profile(folder, OTHER)["tables"]["courses"][0]["score"] == 85
            # Two immediate changes exercise overlapping async selection handlers.
            page.evaluate("([a,b]) => { const s=document.querySelector('#profile-select');"
                          "s.value=a;s.dispatchEvent(new Event('change',{bubbles:true}));"
                          "s.value=b;s.dispatchEvent(new Event('change',{bubbles:true})); }", [SAMPLE, OTHER])
            page.wait_for_function("id => U()?.id === id", arg=OTHER)
            score(page, 76.27)
            select_profile(page, SAMPLE)
            expect(page.locator(COURSE)).to_have_value("88")
            score(page, 78.52)
            checks.append("Fast profile switches preserve edits and keep results attached to their profile")
            page.locator(COURSE).fill("90")
            score(page, 80.02)
            page.screenshot(path=str(ART / "usability-score.png"), full_page=True)
            nav(page, "home")
            page.screenshot(path=str(ART / "usability-home.png"), full_page=True)

            nav(page, "score")
            check_proposal(page, folder, proposal)
            checks.append("Review uses readable fields, supports exclusion and editing, and preserves unknowns")
            checks.append("Imported achievements remain pending after review")
            checks.append("Editing only an achievement name preserves its unknown numeric and boolean facts")
            checks.append("The material button opens file selection directly on the current empty record")
            checks.append("Finished extraction waits for an open editor to close and retains paused review edits")
            select_profile(page, SAMPLE)
            score(page, 80.02)
            page.set_viewport_size({"width": 390, "height": 844})
            for section in ("home", "more", "rules", "files", "score", "opportunities", "plans", "settings"):
                nav(page, section)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                    f"The {section} page must fit a 390px viewport"
                )
                if section == "score":
                    for column in ("credits", "status", "selected"):
                        control = page.locator(
                            f'[data-table="courses"][data-row="0"][data-column="{column}"]'
                        )
                        expect(control).to_be_visible()
                        assert control.evaluate("el => { const container=el.closest('.course-table');"
                                                "const box=el.getBoundingClientRect();"
                                                "const bounds=container.getBoundingClientRect();"
                                                "return container.scrollWidth<=container.clientWidth"
                                                "&&box.left>=bounds.left&&box.right<=bounds.right"
                                                "&&box.left>=0&&box.right<=innerWidth;}"), (
                            f"Mobile course {column} must be readable without horizontal scrolling"
                        )
                    expect(page.locator("#toast")).not_to_be_visible(timeout=7000)
                    page.screenshot(path=str(ART / "usability-mobile.png"), full_page=True)
            checks.append("All eight main and secondary pages fit a 390px viewport without document-level overflow")
            checks.append("Mobile course cards expose credits, course status, and inclusion without horizontal scrolling")
            assert not blocked, "A workflow attempted a prohibited external or model request"
            assert not errors, "Browser JavaScript errors occurred: " + "; ".join(errors)
            return {"javascript_errors": errors, "prohibited_requests": blocked,
                    "viewports": ["1440x1000", "390x844"], "scores": [80.02, 72.52, 76.27, 78.52]}
        finally:
            browser.close()


def main():
    ART.mkdir(exist_ok=True)
    checks = []
    record = dict(status="failed", isolated_data=True, model_calls=0, checks=checks)
    try:
        with tempfile.TemporaryDirectory(prefix="cea-usability-") as temporary:
            folder = Path(temporary)
            policy_id, proposal = prepare_workspace(folder)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            env = os.environ.copy()
            env.update(CEA_DATA=str(folder), PYTHONIOENCODING="utf-8")
            with (folder / "server.log").open("w+b") as log:
                process = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                     "--port", str(port), "--log-level", "warning"],
                    cwd=ROOT, env=env, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                try:
                    wait_ready(process, base)
                    record.update(run_browser(base, folder, policy_id, proposal, checks))
                    record["status"] = "passed"
                finally:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
    finally:
        (ART / "usability-check.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8"
        )
    print("USABILITY_PASS: isolated copy, autosave, automatic scores, profile switching, review form, mobile")


if __name__ == "__main__":
    main()
