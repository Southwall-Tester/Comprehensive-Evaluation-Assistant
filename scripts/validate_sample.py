"""Integration verification only. The app has no school-specific branches."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ingestion import extract
from app.store import put
from app.llm import extract_policy
from app.engine import validate_policy


async def main():
    pdf = next(p for p in Path("D:/desktop").glob("*/*.pdf") if "综合测评" in p.name)
    d = put("document", extract(pdf))
    print(
        "EXTRACTED",
        d["name"],
        len(d["units"]),
        "pages",
        sum(len(u["tables"]) for u in d["units"]),
        "tables",
        flush=True,
    )
    Path("artifacts/source-pages.txt").write_text(
        "\n".join(f"---PAGE {u['index']}---\n{u['text']}" for u in d["units"]),
        encoding="utf8",
    )
    import fitz

    with fitz.open(pdf) as rendered:
        for i in [4, 6, 9, 11, 13]:
            rendered[i].get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).save(f"artifacts/source-{i + 1}.png")
    p, meta = await extract_policy([d])
    p.update(document_ids=[d["id"]], state="draft", generation=meta)
    p["validation_errors"] = validate_policy(p, {d["id"]: d})
    p = put("policy", p)
    Path("artifacts/whu-generated-policy.json").write_text(
        json.dumps(p, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(
        "POLICY",
        p["id"],
        "rules",
        len(p.get("item_rules", [])),
        "formulas",
        len(p.get("formulas", [])),
        "errors",
        p["validation_errors"],
        "meta",
        meta,
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
