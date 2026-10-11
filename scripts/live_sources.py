import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import store
from app.research import import_source, collect_notice, analyze_notice
from app.pipeline import build_policy


async def main():
    policy = store.all_of("policy")[0]
    # Live verification sources. These are test inputs, not application defaults.
    source = "https://www.moe.gov.cn/srcsite/A08/s5672/202607/t20260731_1445670.html"
    policy["official_domains"] = list(
        set(policy.get("official_domains", []) + ["moe.gov.cn", "ccf.org.cn", "cspro.org"])
    )
    for url in [source, "https://www.ccf.org.cn/ccsp/Bulletin/"]:
        try:
            n = await collect_notice(url, policy, lambda s: print(s, flush=True))
            n = await analyze_notice(n, policy, lambda s: print(s, flush=True))
            print("NOTICE_RESULT", n["id"], len(n["attachments"]), len(n["document_ids"]), flush=True)
        except Exception as e:
            print("SOURCE_ERROR", url, type(e).__name__, str(e), flush=True)
    try:
        url = "https://gggl.gduf.edu.cn/info/1143/2890.htm"
        d, _ = await import_source(url, ["gduf.edu.cn"])
        print("SECOND_SCHOOL", d["name"], len(d["units"]), flush=True)
        p = await build_policy([d], lambda s: print(s, flush=True))
        print("SECOND_POLICY", p["id"], p["validation_errors"], flush=True)
    except Exception as e:
        print("SECOND_ERROR", type(e).__name__, str(e), flush=True)


asyncio.run(main())
