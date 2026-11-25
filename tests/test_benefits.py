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


def test_personal_deadline_without_year_uses_same_month_official_date():
    text = ["以上所有电子及纸质材料的提交截止时间为11月25下午17:00。"]
    assert benefits.application_deadline(text, "2026-11-23") == ("2026-11-25", text)
    assert not benefits.application_deadline(text, "2026-12-01")[0]
    assert not benefits.application_deadline(text)[0]
    both = ["申请截止日期为11月25日，本科生另行通知。"]
    assert not benefits.application_deadline(both, "2026-11-23")[0]


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


@pytest.mark.parametrize(("statement", "expected"), [
    ("每支参赛团队将获赠200万Tokens用于模型调用。", "AI 与算力"),
    ("为报名学生提供免费设备借用。", "学习资源"),
    ("本周为学生提供免费简历诊断。", "就业服务"),
    ("在校学生预约后可领取演出门票。", "文体活动"),
    ("全程自费，本次不提供模型调用额度。", ""),
    ("请登录后领取身份验证令牌（token）并妥善保存。", ""),
    ("课程介绍了模型如何将文字转换为token。", ""),
    ("去年现场发放了200万Tokens。", ""),
    ("培训会上还向同学们发放了 Token 服务使用额度。", ""),
    ("报名后每位学生可领取1,000,000 Tokens。", "AI 与算力"),
])
def test_generic_activity_requires_an_explicit_student_entitlement(statement, expected):
    html = f"<title>校园创作周报名</title><article><p>本次活动面向全校师生。</p><p>{statement}</p>" \
           "<p>请登录校园活动平台报名参加。</p></article>"
    card = benefits.read_benefit(BeautifulSoup(html, "html.parser"), "https://campus.edu.cn/notice")
    assert (card["category"] if card else "") == expected
    if card:
        assert card["offer"] == statement


def test_recent_unlabelled_notice_and_affiliated_domain_survive_refresh(monkeypatch):
    root = "https://www.whuss.com/category/20"
    article = "https://www.whuss.com/article/1"
    today = date.today().isoformat()
    pages = {root: f'<dt><span class="updated">[{today}]</span><a href="{article}">校园创作周日程安排</a></dt>'
             f'<dt><span class="updated">[{today}]</span><a href="https://other.cn/article/2">校园服务活动</a></dt>',
             article: '<title>校园创作周日程安排</title><article><p>本次活动面向全校师生。</p>'
             '<p>每位参与者可领取模型调用额度。</p></article>'}
    reads = []

    async def fetch(url, *, limit, domains):
        assert domains == ["whu.edu.cn", "www.whuss.com"]
        reads.append(url)
        html = pages.get(url, "")
        return f"<body>{html}</body>".encode(), url, "text/html", {}

    async def search(*args):
        return []

    monkeypatch.setattr(benefits, "fetch", fetch)
    monkeypatch.setattr(benefits, "search", search)
    monkeypatch.setattr(benefits, "SCHOOLS", {"武汉大学": ("whu.edu.cn", (root,))})
    monkeypatch.setattr(benefits, "SERVICE_GUIDES", {})
    for i in range(2):
        asyncio.run(benefits.discover_benefits("whu.edu.cn", lambda _: None))
        feed = store.get("benefit_feed", "whu.edu.cn")
        assert feed["added"] == (1 if i == 0 else 0)
        assert [(c["url"], c["published_on"], c["category"]) for c in feed["entries"]] == [
            (article, today, "AI 与算力")]
        pages[root] = "<p>今天已更新栏目。</p>"
    assert reads.count(article) == 2 and "https://other.cn/article/2" not in reads
    assert root in {d["url"] for d in feed["directories"]}


@pytest.mark.parametrize(("head", "body", "expected"), [
    ('<meta name="PubDate" content="2026-11-23 17:09">', "", "2026-11-23"),
    ("", "<p><span>发布日期：</span><span>2026年11月23日</span></p>", "2026-11-23"),
    ('<meta property="article:modified_time" content="2026-11-25">', "", ""),
    ('<meta name="PubDate" content="2026年2月31日">', "", ""),
])
def test_official_publication_date_is_independent_of_deadlines(head, body, expected):
    soup = BeautifulSoup(f"<html><head>{head}</head><body>{body}"
                         "<article>学生申请截止日期为2026年12月15日。</article></body></html>", "html.parser")
    assert benefits.publication_date(soup) == expected


@pytest.mark.parametrize(("offer", "accepted"), [
    ("学生可同步申请外方奖学金10,000至25,000美元。", True),
    ("项目不提供奖学金，学生自行承担全部费用。", False),
    ("项目提供两门课程，学费为每人6000元。", False),
    ("校内申请与外方申请均需在平台提交。", False),
])
def test_exchange_notice_requires_funding_evidence(offer, accepted):
    html = f"""<meta name="ArticleTitle" content="关于选派本科生赴海外攻读硕士学位的通知">
        <title>国际合作处</title><article><p>费用由学生自理，学费另缴。</p>
        <p>{offer}</p><p>外方申请截止日期：202 6 年12月15日。</p></article>"""
    result = benefits.read_benefit(BeautifulSoup(html, "html.parser"), "https://campus.edu.cn/project")
    assert bool(result) == accepted
    if accepted:
        assert result["offer"] == offer and result["deadline"] == "2026-12-15"


def test_trial_validity_and_institutional_reporting():
    trial = BeautifulSoup("""<title>数据库开通试用</title><article><p>各位师生可登录校园平台访问数据库。</p>
        <p>试用有效期</p><p>2026年11月—2027年11月</p></article>""", "html.parser")
    card = benefits.read_benefit(trial, "https://campus.edu.cn/trial")
    assert card["terms"] == ["试用有效期 2026年11月—2027年11月"]
    aid = BeautifulSoup("""<title>寒衣补助申请</title><article><p>为在校家庭困难本科生免费发放冬衣。</p>
        <p>三、各学院在11月20日之前将尺码统计表发送至学生中心。</p></article>""", "html.parser")
    card = benefits.read_benefit(aid, "https://campus.edu.cn/winter")
    assert "11月20日" in card["school_dates"][0] and not card["deadline"]


def test_refreshes_cover_later_candidates_without_losing_leading_notices():
    urls = [f"https://example.edu/item/{i}" for i in range(81)]
    first, cursor = benefits.candidate_batch(urls, None)
    second, cursor = benefits.candidate_batch(urls, cursor)
    third, _ = benefits.candidate_batch(urls, cursor)
    assert len(first) == len(set(second)) == len(third) == 48
    assert first[:24] == second[:24] == third[:24] == urls[:24]
    assert set(first + second + third) == set(urls)
    assert benefits.candidate_batch(urls, "removed") == benefits.candidate_batch(urls, None)


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
        directory: '<a title="某大学" href="notice">交通补贴申请</a><a href="notice#part">交通补贴</a>'
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
    assert feed["fresh"] == feed["pages_read"] == feed["added"] == 1
    assert feed["entries"][0]["offer"] == "每人每月补贴100元。"
    assert feed["pending"][0]["url"] == failed
    assert len(feed["failures"]) == 2
    asyncio.run(benefits.discover_benefits(domain, lambda _: None))
    rechecked = store.get("benefit_feed", domain)
    assert rechecked["fresh"] == 1 and rechecked["added"] == 0
    del pages[leaf]
    asyncio.run(benefits.discover_benefits(domain, lambda _: None))
    retry = store.get("benefit_feed", domain)
    assert retry["fresh"] == 0 and retry["entries"] == rechecked["entries"]
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
