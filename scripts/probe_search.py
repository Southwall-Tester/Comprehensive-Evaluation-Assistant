import asyncio
import httpx
from bs4 import BeautifulSoup


async def main():
    urls = [
        ("https://www.bing.com/search", {"q": '"CCSP" "2026" 报名', "format": "rss", "mkt": "zh-CN"}),
        ("https://www.bing.com/search", {"q": "CCF CCSP 2026 报名", "mkt": "zh-CN"}),
        ("https://html.duckduckgo.com/html/", {"q": "CCF CCSP 2026 报名"}),
    ]

    async def one(url, params):
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
                r = await c.get(url, params=params)
            s = BeautifulSoup(r.content, "html.parser")
            print(
                url,
                r.status_code,
                [
                    (a.get_text(" ", strip=True)[:150], a.get("href", "")[:180])
                    for a in s.select("item, li.b_algo h2 a, a.result__a")[:5]
                ],
                flush=True,
            )
        except Exception as e:
            print(type(e).__name__, str(e))

    await asyncio.gather(*[one(*u) for u in urls])


asyncio.run(main())
