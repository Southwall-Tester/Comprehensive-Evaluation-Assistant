import json
from pathlib import Path
import pytest
from app.engine import calculate

CASES = json.loads((Path(__file__).parent / "fixtures/cross_school_totals.json").read_text(encoding="utf8"))


@pytest.mark.parametrize("case", CASES, ids=[c["policy"]["name"] for c in CASES])
def test_official_schools_have_different_total_structures(case):
    assert calculate(case["policy"], case["student"])["total"] == case["expected"]
