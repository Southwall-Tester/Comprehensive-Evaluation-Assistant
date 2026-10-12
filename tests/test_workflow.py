from copy import deepcopy
from datetime import date
from io import BytesIO
import zipfile

import pytest
from fastapi.testclient import TestClient
from app import store
from app.main import app
from app.workflow import timing, enrich_analysis, scenario, apply_review, review_numbers
from tests.test_engine import example, student, event


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    with TestClient(app) as client:
        policy = example()
        policy.update(id="policy", state="active", version=1)
        profile = student([dict(event(), id="old")])
        profile.update(id="person", policy_id="policy", name="测试记录")
        store.put("policy", policy)
        store.put("profile", profile)
        yield client, policy, profile


def d(label, day, **kw):
    return dict(label=label, date=day, verified=True, **kw)


def test_registration_uses_school_deadline_not_final_and_never_invents_opening():
    n = dict(analysis=dict(dates=[d("全国报名截止", "2026-11-10", scope="national"),
        d("校内报名截止", "2026-10-10", scope="school"), d("决赛", "2026-12-10")]))
    t = timing(n, date(2026, 10, 12))
    assert t["status"] == "closed"
    assert t["deadline"]["scope"] == "school"
    n["analysis"]["dates"] = [d("决赛", "2026-12-10")]
    assert timing(n, date(2026, 10, 12))["status"] == "unknown"
    n["analysis"]["dates"] = [d("报名截止", "2026-10-17")]
    assert timing(n, date(2026, 10, 12))["status"] == "deadline_only"
    n["analysis"]["dates"].append(d("报名开始", "2026-10-01"))
    assert timing(n, date(2026, 10, 12))["status"] == "closing"


def test_track_conflicts_and_unverified_dates_remain_unknown():
    n = dict(analysis=dict(dates=[d("报名截止", "2026-11-01", track="A"),
        d("报名截止", "2026-10-01", track="B"), dict(label="报名截止", date="2026-11-09")]))
    t = timing(n, date(2026, 10, 12))
    assert t["status"] == "unknown" and len(t["dates"]) == 2


def test_immediate_registration_needs_no_publication_date_or_invented_start_day():
    n = dict(analysis=dict(dates=[
        d("报名开始（即日起）", None, quote="报名时间 即日起至2026年10月31日。", document_id="notice"),
        d("报名截止（本科组）", "2026-10-31", document_id="notice"),
        d("报名截止（研究生组、留学生组延期）", "2026-11-15", document_id="notice"),
    ]))
    original = deepcopy(n)
    current = timing(n, date(2026, 10, 12))
    assert current["status"] == "open"
    assert [w["status"] for w in current["registration_windows"]] == ["open", "open"]
    assert all(w["start"] is None and w["start_evidence"]["date"] is None for w in current["registration_windows"])
    assert not any(d["kind"] == "registration_start" for d in current["dates"])
    assert current["deadline"] is None  # choosing a group is required for a plan's deadline
    november = timing(n, date(2026, 11, 1))
    assert november["status"] == "partial_open"
    assert [w["status"] for w in november["registration_windows"]] == ["closed", "open"]
    assert timing(n, date(2026, 11, 16))["status"] == "closed"
    assert n == original


def test_immediate_clause_on_deadline_also_establishes_started():
    n = dict(analysis=dict(dates=[d("报名截止", "2027-02-20", quote="报名时间：即日起至2027年2月20日。")]))
    assert timing(n, date(2027, 2, 1))["status"] == "open"


@pytest.mark.parametrize("source", [
    dict(label="报名开始", date=None, quote="即日起报名", verified=False),
    dict(label="活动开始", date=None, quote="即日起举办展览", verified=True),
    dict(label="报名开始", date=None, quote="即日起报名", verified=True, track="另一个组"),
    dict(label="报名开始", date=None, quote="即日起报名", verified=True, document_id="other-notice"),
])
def test_unrelated_or_unverified_immediate_text_cannot_open_registration(source):
    n = dict(analysis=dict(dates=[source, d("报名截止", "2026-10-31")]))
    assert timing(n, date(2026, 10, 12))["status"] == "deadline_only"


@pytest.mark.parametrize("quote", [
    "即日起至2026年10月31日接受报名。", "报名现已开放，截止2026年10月31日。",
    "报名正在进行中。", "报名通道已经开启。", "报名系统正式启用。", "现接受报名。",
    "从现在起接受报名。", "自今日起受理报名。", "自公告发布之日起报名。", "即日开始报名。",
    "报名工作已正式启动。", "现已开放报名。", "报名火热进行中。",
])
def test_existing_analyses_accept_equivalent_opening_language(quote):
    n = dict(analysis=dict(dates=[d("报名开始", None, quote=quote), d("报名截止", "2026-10-31")]))
    assert timing(n, date(2026, 10, 12))["status"] == "open"


@pytest.mark.parametrize("quote,expected", [
    ("报名尚未开放。", "not_open"), ("暂未开始报名。", "not_open"),
    ("报名已结束。", "closed"), ("报名通道已关闭。", "closed"),
    ("暂停接受报名。", "suspended"), ("报名工作暂缓。", "suspended"),
    ("将于下月开始报名。", "deadline_only"), ("报名启动时间另行通知。", "deadline_only"),
    ("欢迎报名参加。", "deadline_only"), ("报名尚未启动，即日起接受咨询。", "not_open"),
])
def test_registration_state_understands_negative_future_and_ended_language(quote, expected):
    n = dict(analysis=dict(dates=[d("报名开始", None, quote=quote), d("报名截止", "2026-10-31")]))
    assert timing(n, date(2026, 10, 12))["status"] == expected


def test_structured_semantic_state_does_not_depend_on_fallback_phrase_vocabulary():
    n = dict(analysis=dict(dates=[d("报名截止", "2026-10-31")], registration_statuses=[
        dict(label="报名状态", quote="参赛登记正在受理，请同学们递交资料。", registration_status="open", verified=True)]))
    assert timing(n, date(2026, 10, 12))["status"] == "open"
    n["analysis"]["dates"] = []
    t = timing(n, date(2026, 10, 12))
    assert t["status"] == "open" and t["registration_windows"][0]["deadline"] is None
    n["analysis"]["registration_statuses"][0]["verified"] = False
    assert timing(n, date(2026, 10, 12))["status"] == "unknown"


def test_recognition_needs_policy_evidence_and_participation_needs_quote():
    docs = {"notice": dict(units=[dict(text="比赛全程线上进行")]),
            "rules": dict(units=[dict(text="本赛事属于认可名单")])}
    cite = dict(document_id="notice", unit=1, quote="比赛全程线上进行")
    policy = dict(item_rules=[dict(id="event")], document_ids=["rules"])
    data = dict(participation=dict(attendance=dict(value="remote", citations=[cite]),
                format=dict(value="project", citations=[dict(cite, quote="捏造的项目赛制")])),
                scoring_matches=[dict(rule_id="event", recognition="named", citations=[cite])])
    result = enrich_analysis(data, policy, docs)
    assert result["participation"]["attendance"]["value"] == "remote"
    assert result["participation"]["format"]["value"] == "unknown"
    assert result["scoring_matches"][0]["recognition"] == "pending"
    data["scoring_matches"][0].update(recognition="inferred", citations=[dict(document_id="rules", unit=1, quote="本赛事属于认可名单")])
    assert enrich_analysis(data, policy, docs)["scoring_matches"][0]["recognition"] == "inferred"


def test_scenario_respects_cap_duplicate_and_does_not_change_record(workspace):
    client, policy, profile = workspace
    candidate = dict(event(level="省级"), values=dict(level="省级", ratio=1))
    before = deepcopy(store.get("profile", "person"))
    result = client.post('/api/profiles/person/scenario', json=candidate).json()
    assert result["baseline"] == 92 and result["total"] == 95 and result["gain"] == 3
    candidate["same_item_id"] = "old"
    result = client.post('/api/profiles/person/scenario', json=candidate).json()
    assert result["gain"] == 0
    assert store.get("profile", "person") == before
    candidate["values"]["ratio"] = None
    assert client.post('/api/profiles/person/scenario', json=candidate).status_code == 400


def test_prepare_is_idempotent_and_progress_survives_reload(workspace):
    client, policy, profile = workspace
    store.put("notice", dict(id="notice", policy_id="policy", title="测试赛", analysis=dict(
        dates=[d("决赛", "2026-12-01")], actions=["提交作品", "提交作品"], materials=["项目报告"])))
    p = client.post('/api/notices/notice/prepare', json=dict(profile_id="person")).json()
    assert not p["date"] and len(p["checklist"]) == 3
    assert client.post('/api/notices/notice/prepare', json=dict(profile_id="person")).json()["id"] == p["id"]
    p["checklist"][1]["done"] = True
    updated = client.put('/api/plans/'+p["id"], json=dict(checklist=p["checklist"], date="2026-11-01"))
    assert updated.status_code == 200
    assert store.get("plan", p["id"])["checklist"][1]["done"]
    other = store.put("profile", dict(id="other", policy_id="other"))
    assert client.post('/api/notices/notice/prepare', json=dict(profile_id=other["id"])).status_code == 400
    client.put('/api/plans/'+p["id"], json=dict(completed=True))
    assert "BEGIN:VEVENT" not in client.get('/api/plans/calendar?profile_id=person').text


def test_pack_contains_linked_proofs_only_and_sanitizes_spreadsheet_cells(workspace, tmp_path):
    client, policy, profile = workspace
    for doc_id in ("proof", "private"):
        path = tmp_path / (doc_id + '.txt')
        path.write_text(doc_id, encoding='utf-8')
        store.put("document", dict(id=doc_id, name=doc_id+'.txt', path=str(path), units=[]))
    profile["items"][0].update(document_ids=["proof"], name="=HYPERLINK(123)")
    profile["items"].append(dict(event(state="planned"), id="pending"))
    store.put("profile", profile)
    response = client.get('/api/profiles/person/application-pack')
    assert response.status_code == 200
    with zipfile.ZipFile(BytesIO(response.content)) as z:
        assert any(n.endswith('proof.txt') for n in z.namelist())
        assert not any('private' in n for n in z.namelist())
        assert "'=HYPERLINK" in z.read('成果汇总.csv').decode('utf-8-sig')
        assert "计划尚未取得" in z.read('待补材料.txt').decode('utf-8')


def test_review_numeric_edits_preserve_lookup_keys_and_version_gate(workspace):
    client, policy, profile = workspace
    changes = dict(version=1, formulas={"bonus": dict(numbers={"4": 10})},
        lookups=[dict(path=["levels", "省级"], value=8)])
    result = client.post('/api/policies/policy/review', json=changes).json()
    assert result["state"] == "draft" and result["version"] == 2
    assert result["formulas"][0]["expression"] == "min(10,awards('bonus'))"
    assert result["lookups"]["levels"]["省级"] == 8
    assert store.all_of("policy_history")[0]["policy"]["state"] == "active"
    assert client.post('/api/policies/policy/review', json=changes).status_code == 400
    assert review_numbers("lookup('2026赛事',level)*.5")[0]["value"] == .5
    assert review_numbers("bad(") == []


def test_calendar_scoped_by_profile_and_policy(workspace):
    client, _, _ = workspace
    for i in range(3):
        store.put("plan", dict(id=str(i), title=str(i), date="2026-11-01", policy_id="policy",
                               profile_id="person" if i == 0 else "other"))
    text = client.get('/api/plans/calendar?policy_id=policy&profile_id=person').text
    assert text.count("BEGIN:VEVENT") == 1
