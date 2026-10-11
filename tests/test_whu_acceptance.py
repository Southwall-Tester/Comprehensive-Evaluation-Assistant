"""Independent numerical checks of the supplied real PDF's reviewed test data."""

import json
from copy import deepcopy
from pathlib import Path
import pytest
from app.engine import calculate

PATH = Path(__file__).resolve().parents[1] / "artifacts/whu-reviewed-policy.json"
pytestmark = pytest.mark.skipif(
    not PATH.exists(), reason="Run scripts/review_whu_fixture.py with the authorized sample first"
)


@pytest.fixture
def policy():
    return json.loads(PATH.read_text(encoding="utf8"))


def student():
    return dict(
        inputs={},
        period_start="2026-09-01",
        period_end="2027-08-31",
        tables={
            "courses": [
                dict(score=90, credits=3, kind="必修或培养方案必选", status="正常", selected=True),
                dict(score=90, credits=2, kind="其他选修或辅修", status="正常", selected=True),
            ]
        },
        items=[],
    )


def item(rule, values, **extra):
    return dict(
        id=str(values),
        name="测试成果",
        rule_id=rule,
        values=values,
        state="confirmed",
        date="2026-10-10",
        **extra,
    )


def scores(p, u):
    return {x["id"]: x["value"] for x in calculate(p, u)["steps"]}


def competition(cls="B", level="全国", rank=1, **more):
    return item(
        "discipline_competition",
        dict(class_id=cls, level=level, award="一等", member_rank=rank, special=False, eligible=True, **more),
    )


def test_pdf_golden_total(policy):
    u = student()
    u["items"] = [competition(), item("certification", {"level": "软考中级"})]
    r = scores(policy, u)
    assert r["b1"] == 90
    assert r["b2"] == 0.36
    assert r["f3"] == 15
    assert calculate(policy, u)["total"] == 80.02


@pytest.mark.parametrize("level,expected", [("国际", 7), ("全国", 7), ("省级", 5), ("校级", 2), ("院级", 2)])
def test_D_class_demotion(policy, level, expected):
    u = student()
    u["items"] = [competition("D", level)]
    assert scores(policy, u)["c3"] == expected


def test_not_all_A_competitions_are_icpc(policy):
    u = student()
    u["items"] = [competition("A")]
    assert scores(policy, u)["c3"] == 12
    u["items"][0]["values"]["special"] = True
    assert scores(policy, u)["c3"] == 14.4


def test_member_ranks(policy):
    u = student()
    u["items"] = [competition(rank=6)]
    assert scores(policy, u)["c3"] == 5
    u["items"][0]["values"]["member_rank"] = 11
    assert scores(policy, u)["c3"] == 0


def test_zero_course_is_counted_and_required_elective_not_double_counted(policy):
    u = student()
    u["tables"]["courses"].append(
        dict(score=0, credits=3, kind="必修或培养方案必选", status="正常", selected=True)
    )
    assert scores(policy, u)["b1"] == 45
    assert scores(policy, u)["b2"] == 0.36
    u["tables"]["courses"][1]["kind"] = "必修或培养方案必选"
    assert scores(policy, u)["b2"] == 0


def test_elective_limit_and_repeat_exclusion(policy):
    u = student()
    row = deepcopy(u["tables"]["courses"][1])
    u["tables"]["courses"].extend(deepcopy(row) for _ in range(8))
    with pytest.raises(ValueError, match="8门"):
        calculate(policy, u)
    u["tables"]["courses"][-1]["status"] = "缓考"
    assert scores(policy, u)["b2"] == 2.88


def test_author_fraction_uses_cap_not_multiplication(policy):
    u = student()
    u["items"] = [
        item(
            "paper",
            dict(
                level="CCF A会议", rank=3, ratio=0.4, best=False, nomination=False, short=False, eligible=True
            ),
        )
    ]
    assert scores(policy, u)["c1"] == 10
    u["items"][0]["values"]["rank"] = 4
    assert scores(policy, u)["c1"] == 0


def test_separate_patents_add_and_same_work_takes_highest(policy):
    u = student()
    u["items"] = [
        item("patent", dict(kind="软件著作权授权", rank=1, eligible=True), conflict_key="A"),
        item("patent", dict(kind="软件著作权授权", rank=1, eligible=True), conflict_key="B"),
    ]
    assert scores(policy, u)["c2"] == 10
    u["items"][1]["conflict_key"] = "A"
    assert scores(policy, u)["c2"] == 5


def test_sports_no_main_roster_means_half_and_group_cap(policy):
    u = student()
    r = item(
        "sports_competition",
        dict(
            level="全国",
            award="一等",
            team_size=8,
            rank=1,
            roster=False,
            boost=False,
            special=False,
            eligible=True,
        ),
    )
    u["items"] = [r]
    assert scores(policy, u)["c3"] == 5
    u["items"] = [deepcopy(r) for _ in range(4)]
    assert scores(policy, u)["c3"] == 15


def test_commendations_global_cap_and_same_exam_max(policy):
    u = student()
    u["items"] = [
        item("commendation", dict(level="校级", count=2)),
        item("commendation", dict(level="院级或单项志愿先进个人", count=4)),
        item("certification", dict(level="软考中级")),
        item("certification", dict(level="软考高级")),
        item("certification", dict(level="CSP前3%")),
    ]
    s = scores(policy, u)
    assert s["c4"] == 3
    assert s["c5"] == 14.5


def test_full_categories_total_cap_and_date_exclusion(policy):
    u = student()
    u["items"] = [item("special_" + x, dict(recognized=True)) for x in ["c1", "c2", "c3", "c4"]]
    assert scores(policy, u)["f3"] == 100
    u["items"][0]["date"] = "2025-01-01"
    assert scores(policy, u)["f3"] == 80


def test_startup_without_leader_list_counts_half(policy):
    u = student()
    u["items"] = [
        item("startup", dict(stage="A轮", team_size=6, principal=True, roster=False, progress=True))
    ]
    assert scores(policy, u)["c5"] == 5
