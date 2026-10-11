"""Independent total-formula acceptance cases, not full school rule templates."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import store
from app.engine import calculate, validate_policy

cases = [
    dict(
        domain="gduf.edu.cn",
        name="广东金融学院：五项加权汇总",
        ids=["moral", "study", "sport", "art", "labor"],
        maxima=[100] * 5,
        values=[80] * 5,
        expression="moral*.2+study*.6+sport*.1+art*.05+labor*.05",
        quote="各部分所占百分比分别为20%、60%、10%、5%、5%",
        expected=80,
    ),
    dict(
        domain="hnit.edu.cn",
        name="湖南工学院语言与文化学院：课程与五项实践加权，再加附加分",
        ids=[
            "courses",
            "moral_practice",
            "study_practice",
            "sport_practice",
            "art_practice",
            "labor_practice",
            "bonus",
        ],
        maxima=[100] * 7,
        values=[80] * 6 + [3],
        expression="courses*.6+moral_practice*.15+study_practice*.1+sport_practice*.05+art_practice*.05+labor_practice*.05+bonus",
        quote="综合素质测评分\n=\n“五育”课程成绩×",
        expected=83,
    ),
    dict(
        domain="hsart.hbpu.edu.cn",
        name="湖北理工学院艺术学院：已折算的各项分数直接相加",
        ids=["moral", "study", "sport", "art", "labor", "bonus"],
        maxima=[20, 50, 10, 10, 10, 15],
        values=[16, 40, 8, 8, 8, 3],
        expression="moral+study+sport+art+labor+bonus",
        quote="该项满分20 分，德育测评成绩",
        expected=83,
    ),
]
results = []
for c in cases:
    doc = next(d for d in store.all_of("document") if c["domain"] in d.get("source_url", ""))
    policy = dict(
        name=c["name"],
        inputs=[dict(id=id, type="number", min=0, max=maximum) for id, maximum in zip(c["ids"], c["maxima"])],
        tables=[],
        item_rules=[],
        formulas=[
            dict(
                id="result",
                label="汇总分",
                expression=c["expression"],
                citations=[dict(document_id=doc["id"], unit=1, quote=c["quote"])],
            )
        ],
        total="result",
        scope="仅验证原文总分结构；子项分数为独立验收输入，不代表完整细则解析",
    )
    assert not validate_policy(policy, {doc["id"]: doc})
    student = dict(inputs=dict(zip(c["ids"], c["values"])), tables={}, items=[])
    score = calculate(policy, student)["total"]
    assert score == c["expected"]
    results.append(
        dict(
            source_url=doc["source_url"], policy=policy, student=student, expected=c["expected"], actual=score
        )
    )
out = Path("tests/fixtures")
out.mkdir(exist_ok=True)
(out / "cross_school_totals.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
)
print("CROSS_SCHOOL_TOTALS_PASS", [(c["policy"]["name"], c["actual"]) for c in results])
