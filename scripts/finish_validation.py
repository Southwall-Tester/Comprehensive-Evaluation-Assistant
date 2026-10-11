"""Prepare transparent local acceptance records, then exercise live official retrieval."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import store
from app.engine import calculate, validate_policy
from app.research import collect_notice, analyze_notice, research
from tests.test_whu_acceptance import student, competition, item


async def main():
    p = store.get("policy", "44274322bad3478c8fa6685c1bb794c0")
    assert not validate_policy(p, {x: store.get("document", x) for x in p["document_ids"]})
    p["state"] = "active"
    store.put("policy", p)
    u = student()
    u.update(id="acceptance-fictional", name="验证样例（虚构数据）", policy_id=p["id"])
    u["tables"]["courses"][0]["_label"] = "示例必修课程"
    u["tables"]["courses"][1]["_label"] = "示例其他选修课程"
    u["items"] = [competition(), item("certification", {"level": "软考中级"})]
    for i, r in enumerate(u["items"]):
        r.update(id=f"acceptance-{i}", name=["示例B类全国一等奖", "示例软考中级"][i])
    store.put("profile", u)
    assert calculate(p, u)["total"] == 80.02
    for id in ["27fc36da29a44c2499cfa058645464ca", "51393665445a4c9ebb89791e56eb4fc1"]:
        try:
            old = store.get("policy", id)
            store.put("policy_history", dict(policy_id=id, policy=old))
            store.delete("policy", id)
        except ValueError:
            pass
    store.delete("notice", "754f8688961c496295c6d16fdb1cc18b")
    store.delete("document", "dec30c42d848d3943d8835a6")
    urls = [
        "https://www.ccf.org.cn/Media_list/ccsp/2026-09-09/931087.shtml",
        "https://ccsp.ccf.org.cn/Media_list/ccsp/2026-09-09/931087.shtml",
    ]
    for url in urls:
        try:
            n = await collect_notice(url, p, lambda x: print(x, flush=True))
            print("CCSP_COLLECTED", n["id"], flush=True)
            await analyze_notice(n, p, lambda x: print(x, flush=True))
            break
        except Exception as e:
            print("CCSP_FAILED", url, str(e)[:160], flush=True)
    report = await research(p, lambda x: print(x, flush=True), "CCSP 2026 报名", 1)
    Path("artifacts/research-live.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("RESEARCH_COVERAGE", report["coverage"], flush=True)


if __name__ == "__main__":
    asyncio.run(main())
