import asyncio
from datetime import date, timedelta

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import benefits, main, store


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(main, "settings", lambda: {"auto_research": False})
    monkeypatch.setattr(benefits, "settings", lambda: {"search_provider": "bing"})


@pytest.mark.parametrize(("lines", "expected"), [
    (["发布日期为2026年10月1日。", "请于2026年11月25日17:00前提交申请。"], "2026-11-25"),
    (["申请时间为2026-11-01至2026-11-30。"], "2026-11-30"),
    (["学生申请截止时间为2026年12月1日。"], "2026-12-01"),
    (["三、申请截止时间", "2026年12月1日"], "2026-12-01"),
    (["申请时间为2026年11月至12月中旬。"], ""),
    (["申请截止时间为2026年2月30日。"], ""),
    (["申请时间另行通知。", "公告发布日期为2026年10月1日。"], ""),
    (["本科生申请截止2026年11月20日。", "研究生申请截止2026年11月27日。"], ""),
    (["本科生申请截止2026年11月20日。", "研究生申请时间另行通知。"], ""),
    (["本科生申请截止2026年11月20日，研究生截止11月27日。"], ""),
    (["本科生申请截止2026年11月20日。", "硕士组截止2026年12月3日。"], ""),
    (["学院汇总后于2026年11月30日前提交材料。", "公示期至2026年12月3日。"], ""),
])
def test_deadline_requires_one_applicant_cutoff(lines, expected):
    assert benefits.application_deadline(lines)[0] == expected


def test_school_resolution_uses_rule_source_and_keeps_organizers_separate():
    store.put("document", dict(id="rules", source_url="https://cs.alpha.edu.cn/rules.pdf"))
    policy = dict(id="a", name="计算机学院细则", official_domains=["host.beta.edu.cn", "org.example"])
    store.put("policy", policy)
    assert benefits.scope("a") == ("", "beta.edu.cn")
    store.put("policy", {**policy, "document_ids": ["rules"]})
    assert benefits.scope("a")[0] == "alpha.edu.cn"
    store.put("benefit_school", dict(id="_workspace", domain="other.edu.cn"))
    assert benefits.scope()[0] == "other.edu.cn"
    assert benefits.scope("a")[0] == "alpha.edu.cn"
    store.put("benefit_school", dict(id="a", domain="corrected.edu.cn"))
    assert benefits.scope("a")[0] == "corrected.edu.cn"
    assert benefits.school_for({"name": "武汉大学计算机学院"}, None) == "whu.edu.cn"
    for invalid in ["edu.cn", "https://", "ftp://alpha.edu.cn", "127.0.0.1", "localhost"]:
        with pytest.raises(ValueError):
            benefits.school_domain(invalid)


def test_only_landing_page_evidence_becomes_an_offer():
    soup = BeautifulSoup("""<title>勤工助学岗位招聘</title><body><nav>每人每月9999元</nav>
        <article><p>面向本校全日制本科生。</p><p>岗位报酬每小时20元。</p>
        <p>请登录<a>校园服务平台</a>提交申请。</p><p>本岗位不得与其他补贴同时享受。</p>
        <p>奖学金发放时间预计在2027年上半年，本次申请的是2026学年的岗位。</p></article></body>""",
        "html.parser")
    card = benefits.read_benefit(soup, "https://alpha.edu.cn/jobs")
    assert card["category"] == "勤工助学"
    assert card["offer"] == "岗位报酬每小时20元。"
    assert card["method"] == "请登录校园服务平台提交申请。"
    assert card["terms"] == ["本岗位不得与其他补贴同时享受。"]
    assert not card["deadline_text"] and not card["deadline"]
    assert "9999" not in str(card)


def test_discovery_crawls_without_search_and_retains_unread_sources(monkeypatch):
    domain = "campus.edu.cn"
    home = "https://campus.edu.cn/"
    leaf = home + "aid/notice"
    directory = home + "aid/"
    failed = home + "unread"
    read_urls, queries = [], []
    pages = {
        home: '<a href="/aid/">学生资助</a>',
        "https://www.campus.edu.cn/": '<a href="https://another.edu.cn/b">助学金申请</a>',
        directory: '<a href="notice">交通补贴申请</a><a href="notice#part">交通补贴</a>'
                   '<a href="/unread">学生助理招聘</a><a href="/list">奖学金评选结果公示</a>',
        leaf: '<title>在校学生交通补贴申请</title><article><p>服务对象为全日制在校本科生。</p>'
              '<p>每人每月补贴100元。</p><p>请填写交通补贴申请表。</p></article>',
    }

    async def search(query, cfg):
        queries.append(query)
        if "勤工" in query:
            raise RuntimeError("搜索超时")
        return [{"url": "https://campus.edu.cn.other.org/fake", "title": "交通补贴申请"},
                {"url": leaf, "title": "交通补贴申请", "snippet": "每人99999元"}]

    async def fetch(url, *, limit, domains):
        assert domains == [domain]
        read_urls.append(url)
        if url not in pages:
            raise ValueError("暂时无法读取")
        return ("<html><body>" + pages[url] + "</body></html>").encode(), url, "text/html", {}

    monkeypatch.setattr(benefits, "search", search)
    monkeypatch.setattr(benefits, "fetch", fetch)
    asyncio.run(benefits.discover_benefits(domain, lambda _: None))
    feed = store.get("benefit_feed", domain)
    assert all(q.startswith("site:campus.edu.cn ") for q in queries)
    assert set(read_urls) == {home, "https://www.campus.edu.cn/", directory, leaf, failed}
    assert read_urls.count(leaf) == 1
    assert feed["fresh"] == feed["pages_read"] == 1
    assert feed["entries"][0]["offer"] == "每人每月补贴100元。"
    assert feed["pending"][0]["url"] == failed
    assert len(feed["failures"]) == 2
    del pages[leaf]
    asyncio.run(benefits.discover_benefits(domain, lambda _: None))
    retry = store.get("benefit_feed", domain)
    assert retry["fresh"] == 0 and retry["entries"] == feed["entries"]
    assert retry["checked_at"] != retry["entries"][0]["checked_at"]

    async def no_hits(*args):
        return []

    monkeypatch.setattr(benefits, "search", no_hits)
    pages[directory] = "<p>本期暂无新公告。</p>"
    read_urls.clear()
    pages[leaf] = "<title>补贴已停止办理</title><article>停止办理。</article>"
    asyncio.run(benefits.discover_benefits(domain, lambda _: None))
    assert leaf in read_urls
    assert not store.get("benefit_feed", domain)["entries"]


def test_mirror_deduplication_preserves_conditions_and_institutional_deadlines(monkeypatch):
    domain = "other.edu.cn"
    root = "https://other.edu.cn/"
    body = """<html><title>新生助学金申请通知</title><article><p>一、资助对象、人数和金额</p>
        <p>资助全日制新生中的家庭经济困难学生，每人补贴1000元。</p><p>二、申请条件</p>
        <p>1.申请人未享受其他社会助学金。</p><p>2.同一家庭只允许一人申领。</p><p>三、申请流程</p>
        <p>登录校园平台提交个人申请。</p><p>2.学院初审学生申请材料，于2027年2月5日前报送学生中心。</p>
        <a href="form.pdf">申请材料</a></article></html>"""
    urls = ["first", "mirror", "separate", "index"]

    async def fetch(url, **kwargs):
        if url.rstrip("/") in {root.rstrip("/"), "https://www." + domain}:
            html = "".join(f'<a href="{root}{path}">新生助学金申请通知</a>' for path in urls)
        elif url.endswith("index"):
            html = body.replace("新生助学金申请通知", "奖助学金-学生资助管理中心")
        elif url.endswith("separate"):
            html = body.replace("form.pdf", "separate-form.pdf")
        else:
            html = body
        return ("<body>" + html + "</body>").encode(), url, "text/html", {}

    async def search(*args):
        return []

    monkeypatch.setattr(benefits, "fetch", fetch)
    monkeypatch.setattr(benefits, "search", search)
    asyncio.run(benefits.discover_benefits(domain, lambda _: None))
    feed = store.get("benefit_feed", domain)
    assert feed["fresh"] == 2 and set(i["url"] for i in feed["entries"]) == {root + "first", root + "separate"}
    card = feed["entries"][0]
    assert card["audience"] == card["offer"]
    assert card["conditions"] == card["terms"] == ["1.申请人未享受其他社会助学金。", "2.同一家庭只允许一人申领。"]
    assert not card["deadline"] and not card["deadline_text"] and len(card["school_dates"]) == 1


def test_school_change_and_duplicate_jobs(monkeypatch):
    async def wait_for_cancel(domain, log):
        await asyncio.Event().wait()

    monkeypatch.setattr(benefits, "discover_benefits", wait_for_cancel)
    with TestClient(main.app) as client:
        store.put("policy", dict(id="p", name="测试方案"))
        assert client.post("/api/benefits/search", json={"policy_id": "p"}).status_code == 400
        job = client.put("/api/benefits/school", json={"policy_id": "p", "domain": "www.one.edu.cn"}).json()
        assert client.post("/api/benefits/search", json={"policy_id": "p"}).json()["id"] == job["id"]
        assert client.get("/api/benefits?policy_id=p").json()["running"] == job["id"]
        assert client.get("/api/benefits").json()["domain"] == ""
        assert client.put("/api/benefits/school", json={"policy_id": "p", "domain": "edu.cn"}).status_code == 400
        assert client.get("/api/benefits?policy_id=p").json()["domain"] == "one.edu.cn"


def test_scheduler_respects_interval_and_searches_without_competitions(monkeypatch):
    started = []
    monkeypatch.setattr(main, "start_benefits", started.append)
    store.put("benefit_school", {"id": "_workspace", "domain": "one.edu.cn"})
    policies = [dict(id="p1", state="active", school_domain="one.edu.cn", opportunities=[]),
                dict(id="p2", state="active", school_domain="two.edu.cn", opportunities=[])]
    store.put("benefit_feed", dict(id="two.edu.cn", checked_at=store.now()))
    main.schedule_benefits(policies, {"auto_research": False, "refresh_hours": 24})
    assert not started
    main.schedule_benefits(policies, {"auto_research": True, "refresh_hours": 24})
    assert started == ["one.edu.cn"]
    store.put("benefit_feed", dict(id="two.edu.cn", checked_at="2001-02-03T00:00:00+00:00"))
    main.schedule_benefits(policies, {"auto_research": True, "refresh_hours": 24})
    assert started[1:] == ["one.edu.cn", "two.edu.cn"]


def test_personal_todo_preserves_user_edits_and_checks_school():
    future = (date.today() + timedelta(days=5)).isoformat()
    stamp = store.now()
    item = dict(id="b", url="https://one.edu.cn/aid", title="助学金", checked_at=stamp,
                audience="本校学生", method="请提交材料", deadline=future, deadline_text=["申请截止 " + future],
                school_dates=["学院另行汇总后报送"])
    store.put("benefit_feed", dict(id="one.edu.cn", checked_at=stamp, entries=[item]))
    for i, domain in (("a", "one.edu.cn"), ("b", "two.edu.cn")):
        store.put("policy", dict(id=i, school_domain=domain))
        store.put("profile", dict(id=i, policy_id=i))
    with TestClient(main.app) as client:
        endpoint = "/api/benefits/b/plan"
        assert client.post(endpoint, json={"profile_id": "b"}).status_code == 400
        plan = client.post(endpoint, json={"profile_id": "a"}).json()
        assert plan["date"] == future and plan["url"] == item["url"]
        assert "院系报送安排\n学院另行汇总后报送" in plan["notes"]
        client.put("/api/plans/" + plan["id"], json=dict(notes="已提交材料", completed=True))
        retry = client.post(endpoint, json={"profile_id": "a"}).json()
        assert retry["id"] == plan["id"] and retry["notes"] == "已提交材料" and retry["completed"]
        assert len(store.all_of("plan")) == 1
        assert "BEGIN:VEVENT" not in client.get("/api/plans/calendar?profile_id=a").text
        store.put("profile", dict(id="other", policy_id="a"))
        store.put("benefit_feed", dict(id="one.edu.cn", checked_at=store.now(), entries=[item]))
        assert not client.post(endpoint, json={"profile_id": "other"}).json()["date"]
