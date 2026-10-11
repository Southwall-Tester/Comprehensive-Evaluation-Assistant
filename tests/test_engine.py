import pytest
from app.engine import calculate, expression, validate_policy


def test_malformed_model_structure_returns_review_errors():
    p = example()
    p["inputs"] = ["bad model response"]
    assert "每项须为对象" in validate_policy(p)[0]
    p = example()
    p["item_rules"][0]["fields"] = ["bad field"]
    assert "字段对象数组" in validate_policy(p)[0]


def test_incomplete_plan_does_not_break_actual_score():
    from app.engine import planned_gains

    p = example()
    u = student(
        [dict(id="plan", rule_id="event", name="未定级别计划", state="planned", date="2026-10-10", values={})]
    )
    assert calculate(p, u)["total"] == 80
    assert planned_gains(p, u)[0]["error"]


def example():
    # A deliberately different fictional policy, not the Wuhan test file.
    cite = [{"document_id": "test", "unit": 1, "quote": "五项指标按各自权重计算"}]
    return dict(
        name="五维通用引擎测试",
        inputs=[
            {"id": x, "type": "number", "min": 0, "max": 100, "default": 80}
            for x in ["ethics", "study", "sport", "art", "work"]
        ],
        tables=[],
        lookups={"levels": {"校级": 2, "省级": 6, "国家级": 12}},
        item_rules=[
            dict(
                id="event",
                category="bonus",
                fields=[
                    dict(id="level", type="select", options=["校级", "省级", "国家级"]),
                    dict(id="ratio", type="number", min=0, max=1, default=1),
                ],
                expression="lookup('levels',level)*ratio",
                citations=cite,
            )
        ],
        formulas=[
            dict(id="bonus", label="独立奖励", expression="min(15,awards('bonus'))", citations=cite),
            dict(
                id="result",
                label="总分",
                expression="ethics*.2+study*.5+sport*.1+art*.1+work*.1+bonus",
                citations=cite,
            ),
        ],
        total="result",
        duplicate_mode="max",
        date_window_required=True,
    )


def student(items=None):
    return dict(inputs={}, tables={}, items=items or [], period_start="2026-09-01", period_end="2027-08-31")


def event(name="one", level="国家级", state="confirmed", date="2026-10-10", conflict_key=""):
    return dict(
        name=name,
        rule_id="event",
        values=dict(level=level),
        state=state,
        date=date,
        conflict_key=conflict_key,
    )


def test_five_dimensions_plus_absolute_bonus():
    p = example()
    assert calculate(p, student())["total"] == 80
    assert calculate(p, student([event()]))["total"] == 92
    p["formulas"][-1]["expression"] = "study*.9+ethics*.1+bonus*.2"
    assert calculate(p, student([event()]))["total"] == 82.4


def test_caps_dedup_dates_pending_and_projection():
    p = example()
    u = student(
        [
            event("gold", conflict_key="same"),
            event("silver", "省级", conflict_key="same"),
            event("new", "校级"),
            event("planned", "国家级", "planned"),
            event("pending", "国家级", "pending"),
            event("old", "国家级", date="2025-10-10"),
        ]
    )
    r = calculate(p, u)
    assert r["total"] == 94
    assert [x["score"] for x in r["ledger"]] == [12, 0, 2, 0, 0, 0]
    assert calculate(p, u, True)["total"] == 95
    assert calculate(p, {**u, "items": list(reversed(u["items"]))})["total"] == 94


def test_automatic_same_certification_group():
    p = example()
    p["item_rules"][0]["group_by"] = "'cert_type'"
    assert calculate(p, student([event(), event("twice", "省级")]))["total"] == 92


def test_negative_adjustment_and_nonlinear_formula():
    p = example()
    p["formulas"][-1]["expression"] = "study*0.5 + min(20,work*.2) + max(0,ethics-60) - bonus"
    assert calculate(p, student([event()]))["total"] == 64


def test_course_weighted_zero_and_top_n():
    p = example()
    p["tables"] = [
        dict(
            id="courses",
            fields=[
                dict(id="score", type="number", min=0, max=100),
                dict(id="credit", type="number", min=0.1),
                dict(id="status", type="select", options=["正常", "重修"]),
            ],
        )
    ]
    p["formulas"][-1]["expression"] = (
        "mean_rows('courses','score','credit',\"status == '正常'\") + sum_rows('courses','score*credit',\"status == '重修'\",1)*0.001"
    )
    u = student()
    u["tables"] = {
        "courses": [
            dict(score=0, credit=2, status="正常"),
            dict(score=90, credit=4, status="正常"),
            dict(score=100, credit=3, status="重修"),
        ]
    }
    assert calculate(p, u)["total"] == 60.3


def test_constraints_and_missing_values():
    p = example()
    p["constraints"] = [dict(expression="study>=85", severity="warning", message="奖项门槛")]
    assert calculate(p, student())["notices"][0]["message"] == "奖项门槛"
    p["constraints"][0]["severity"] = "block"
    with pytest.raises(ValueError, match="奖项门槛"):
        calculate(p, student())
    p = example()
    p["inputs"][0].pop("default")
    with pytest.raises(ValueError, match="请填写"):
        calculate(p, student())


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo bad')",
        "study.__class__",
        "(lambda: 1)()",
        "[x for x in []]",
        "1/0",
        'float("nan")',
    ],
)
def test_expressions_are_not_executable(expr):
    with pytest.raises(ValueError):
        expression(expr, {"study": 1})


def test_source_validation_and_undefined_branch():
    p = example()
    d = {"test": dict(units=[dict(text="五项指标按各自权重计算", tables=[])])}
    assert validate_policy(p, d) == []
    p["formulas"][-1]["expression"] = "study if True else undefined"
    assert any("undefined" in e for e in validate_policy(p, d))
    p["formulas"][0]["citations"][0]["quote"] = "根本不存在的引用"
    assert any("引文" in e for e in validate_policy(p, d))


def test_out_of_range_and_unknown_enum():
    p = example()
    u = student()
    u["inputs"]["study"] = 101
    with pytest.raises(ValueError):
        calculate(p, u)
    with pytest.raises(ValueError):
        calculate(p, student([event(level="编造级别")]))


def test_duplicate_mode_varies_by_policy():
    p = example()
    items = [event(conflict_key="same"), event("second", "校级", conflict_key="same")]
    assert calculate(p, student(items))["total"] == 92
    p["duplicate_mode"] = "sum"
    assert calculate(p, student(items))["total"] == 94
    p["duplicate_mode"] = "block"
    with pytest.raises(ValueError, match="重复"):
        calculate(p, student(items))
