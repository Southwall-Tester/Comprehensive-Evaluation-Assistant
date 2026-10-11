"""Optional real network/model checks against the running local app."""

import json
import time
from pathlib import Path
import httpx

base = "http://127.0.0.1:8768"
policy = "44274322bad3478c8fa6685c1bb794c0"
with httpx.Client(base_url=base, timeout=200) as client:
    connection = client.post("/api/settings/test")
    connection.raise_for_status()
    print("MODEL_CONNECTION", connection.json()["model"], flush=True)
    jobs = {}
    for kind, path, body in [
        (
            "answer",
            "/api/ask",
            dict(
                policy_id=policy,
                profile_id="acceptance-fictional",
                question="只回答：当前虚构样例的课程成绩F2和综测总分分别是多少？指出选修系数依据页码。不要超过200字。",
            ),
        ),
        ("research", "/api/research", dict(policy_id=policy, query="2026 大学生竞赛 报名 通知", limit=1)),
    ]:
        r = client.post(path, json=body)
        r.raise_for_status()
        jobs[kind] = r.json()["id"]
    outputs = {}
    deadline = time.monotonic() + 600
    while jobs and time.monotonic() < deadline:
        for kind, id in list(jobs.items()):
            r = client.get("/api/jobs/" + id)
            r.raise_for_status()
            j = r.json()
            if j["state"] != "running":
                outputs[kind] = j
                print("LIVE_JOB", kind, j["state"], j.get("error", ""), flush=True)
                if kind == "answer" and j["state"] == "done":
                    print(j["result"]["answer"], flush=True)
                if kind == "research" and j["state"] == "done":
                    print(j["result"]["coverage"], flush=True)
                del jobs[kind]
        if jobs:
            time.sleep(2)
    Path("artifacts/live-acceptance.json").write_text(
        json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf8"
    )
    assert not jobs, "Live jobs exceeded deadline; background job status remains visible in UI"
    assert all(j["state"] == "done" for j in outputs.values())
    assert "80.02" in outputs["answer"]["result"]["answer"]
