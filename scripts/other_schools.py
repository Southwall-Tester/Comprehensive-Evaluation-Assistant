"""Fetch additional official test inputs; no school-specific application code."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.research import import_source
from app.pipeline import build_policy


async def main():
    sources = [
        ("https://hsart.hbpu.edu.cn/info/1111/5143.htm", "hbpu.edu.cn"),
        ("https://www.hnit.edu.cn/wgyxy/info/1028/6878.htm", "hnit.edu.cn"),
    ]
    for url, domain in sources:
        try:
            d, _ = await import_source(url, [domain])
            print("FETCHED", d["name"], d["id"], sum(len(u["text"]) for u in d["units"]), flush=True)
            p = await build_policy([d], lambda s: print(s, flush=True))
            print("POLICY_RESULT", p["id"], p["name"], p["validation_errors"], flush=True)
        except Exception as e:
            print("ERROR", url, type(e).__name__, str(e), flush=True)


asyncio.run(main())
