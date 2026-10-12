"""Personal competition workflow. Unknown facts never become eligibility claims."""
from copy import deepcopy
import ast
from datetime import date
from io import BytesIO
from pathlib import Path
import csv
import hashlib
import io
import json
import math
import re
import uuid
import zipfile

from . import store
from .engine import calculate, normalize


def review_numbers(expression):
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, TypeError):
        return []
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    rows = []
    # AST offsets count UTF-8 bytes; edits below use the same representation.
    if "\n" in expression:
        return rows
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or type(node.value) not in (int, float):
            continue
        parent = parents.get(node)
        label = "计算常数"
        if isinstance(parent, ast.BinOp) and isinstance(parent.op, (ast.Mult, ast.Div)):
            label = "系数 / 权重（按原文核对）"
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name):
            label = {"min": "上限候选值（min）", "max": "下限候选值（max）"}.get(parent.func.id, label)
        rows.append(dict(start=node.col_offset, end=node.end_col_offset, value=node.value, label=label))
    return sorted(rows, key=lambda x: x["start"])


def apply_review(policy, changes):
    if changes.get("version") != policy.get("version", 1):
        raise ValueError("规则版本已变化，请重新打开核对页面")
    updated = deepcopy(policy)
    for section in ("formulas", "item_rules"):
        for row in updated.get(section, []):
            change = changes.get(section, {}).get(row["id"], {})
            numbers = {str(n["start"]): n for n in review_numbers(row["expression"])}
            raw = row["expression"].encode("utf-8")
            edits = change.get("numbers", {})
            for key in sorted(edits, key=int, reverse=True):
                value = edits[key]
                if key not in numbers or type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError("规则数值无效")
                n = numbers[key]
                replacement = str(value) if value >= 0 else f"({value})"
                raw = raw[:n["start"]] + replacement.encode() + raw[n["end"]:]
            row["expression"] = raw.decode("utf-8")
            if section == "item_rules" and "category" in change:
                # Category also connects awards(category) in formulas. Renaming only one
                # side silently drops scores, so keep this identifier read-only.
                raise ValueError("分类标识涉及公式关联，请通过高级编辑维护")
    for edit in changes.get("lookups", []):
        obj = updated.get("lookups", {})
        path = edit.get("path", [])
        if not path:
            raise ValueError("计分表位置无效")
        for key in path[:-1]:
            if not isinstance(obj, dict) or key not in obj:
                raise ValueError("计分表位置不存在")
            obj = obj[key]
        key, value = path[-1], edit.get("value")
        if not isinstance(obj, dict) or key not in obj or type(obj[key]) not in (int, float):
            raise ValueError("只能修改现有计分表数值")
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("请填写有效分值")
        obj[key] = value
    return updated


def supported(citation, documents):
    if not isinstance(citation, dict):
        return False
    doc = documents.get(citation.get("document_id"), {})
    unit = citation.get("unit")
    quote = normalize(str(citation.get("quote", "")))
    units = doc.get("units", [])
    return bool(isinstance(unit, int) and 1 <= unit <= len(units) and len(quote) >= 4
                and quote in normalize(units[unit - 1].get("text", "")))


def enrich_analysis(result, policy, documents):
    """Validate provenance; a matching quote is not a formal recognition decision."""
    allowed = {"format": {"project", "timed", "mixed"},
               "attendance": {"remote", "onsite", "hybrid"},
               "team": {"solo", "team", "either"}}
    facts = result.get("participation", {})
    result["participation"] = {}
    for key, values in allowed.items():
        fact = facts.get(key, {}) if isinstance(facts, dict) else {}
        if not isinstance(fact, dict):
            fact = {}
        verified = fact.get("value") in values and bool(fact.get("citations")) and all(
            supported(c, documents) for c in fact.get("citations", []))
        result["participation"][key] = {**fact, "verified": verified,
                                             "value": fact.get("value") if verified else "unknown"}
    rules = {r["id"]: r for r in policy.get("item_rules", [])}
    policy_docs = set(policy.get("document_ids", []))
    for match in result.get("scoring_matches", []):
        cs = match.get("citations", [])
        valid = match.get("rule_id") in rules and bool(cs) and all(supported(c, documents) for c in cs)
        has_policy = any(c.get("document_id") in policy_docs for c in cs)
        status = match.get("recognition", "pending")
        if not valid or not has_policy or status not in {"named", "inferred", "ineligible"}:
            status = "pending"
        match.update(recognition=status, evidence_verified=valid and has_policy)
    return result


def date_kind(d):
    label = d.get("label", "")
    # Use literal labels as well as structured metadata; finals never imply registration.
    if re.search("报名|注册|校内推荐|校内报送", label):
        if re.search("截止|结束", label):
            return "registration_end"
        if re.search("开始|启动|开放", label):
            return "registration_start"
    return "event"


def registration_assertion(item):
    """Read a source-backed state independently of whether a start day is known.

    New analyses provide the semantic state. Phrase families are a compatibility
    fallback for existing analyses, not a requirement on the model's wording.
    """
    if not item.get("verified"):
        return None
    text = re.sub(r"\s+", "", item.get("quote", ""))
    label = item.get("label", "")
    if not re.search("报名|注册", label):
        return None
    subject = r"(?:报名|注册)(?:工作|通道|渠道|系统|入口|窗口|活动)?"
    if re.search(subject + r"(?:现已|已经|已|现)(?:截止|结束|关闭|停止)", text):
        return "closed"
    if re.search(subject + r".{0,6}(?:暂停|暂缓)", text) or re.search(r"(?:暂停|暂缓)(?:接受|开放)?" + subject, text):
        return "suspended"
    if (re.search(subject + r".{0,6}(?:尚未|暂未|暂不|未曾|不再)", text)
            or re.search(r"(?:尚未|暂未|暂不|不再|不接受).{0,8}" + subject, text)):
        return "not_open"
    # Source validation is done in analyze_notice; semantic extraction is not
    # constrained to a particular phrase, publication date, or date format.
    extracted = item.get("registration_status")
    if extracted in {"open", "not_open", "closed", "suspended"}:
        return extracted
    if re.search(r"将于|拟于|计划于|预计于|另行通知|敬请期待|届时", text):
        return None
    relative = (r"即日(?:起|开始)|从(?:现在|今日|今天|即日)起|自(?:今日|今天|即日)起|"
                r"(?:自|从)?(?:本)?(?:通知|公告)(?:发布|公布|印发)(?:之日|当日|日)?起")
    if re.search(relative, text) and date_kind(item) in {"registration_start", "registration_end"}:
        return "open"
    if (re.search(subject + r"(?:现已|已经|已|现|正式|全面|正在|火热|持续|现正){1,3}(?:开放|开启|启动|开始|进行|启用)", text)
            or re.search(r"(?:现已|已经|正在|现正|现)(?:正式|全面)?(?:开放|开启|启动|开始|接受|受理)" + subject, text)
            or re.search(subject + r"(?:正在|进行|开放|受理)中", text)):
        return "open"
    return None


def timing(notice, today=None):
    today = today or date.today()
    dates = []
    raw_dates = notice.get("analysis", {}).get("dates", [])
    def track_for(item):
        if item.get("track"):
            return item["track"]
        # Older analyses put the group in the label rather than a separate field.
        match = re.search(r"[（(]([^）)]+)[）)]", item.get("label", ""))
        return match[1] if match and re.search("组|赛道", match[1]) else ""

    def scope_for(item):
        scope = item.get("scope")
        return scope if scope in {"school", "national", "unknown"} else (
            "school" if "校内" in item.get("label", "") else "unknown")

    assertions = []
    for item in raw_dates + notice.get("analysis", {}).get("registration_statuses", []):
        state = registration_assertion(item)
        if state:
            assertions.append({**item, "scope": scope_for(item), "track": track_for(item), "registration_status": state})
    for item in raw_dates:
        try:
            when = date.fromisoformat(item.get("date") or "")
        except (ValueError, TypeError):
            continue
        if not item.get("verified"):
            continue
        dates.append({**item, "kind": date_kind(item), "scope": scope_for(item), "track": track_for(item)})
    dates.sort(key=lambda d: d["date"])
    ends = [d for d in dates if d["kind"] == "registration_end"]
    starts = [d for d in dates if d["kind"] == "registration_start"]
    tracks = list(dict.fromkeys(d["track"] for d in ends))
    windows = []
    for track in tracks:
        track_ends = [d for d in ends if d["track"] == track]
        cutoff = track_ends[0]  # earliest applicable deadline, including school recommendation
        matching = [d for d in starts if d["scope"] == cutoff["scope"] and d["track"] in ("", track)]
        begin = matching[-1] if matching else None
        evidence = [d for d in assertions if d["scope"] == cutoff["scope"]
                    and d["track"] in ("", track)
                    and d.get("document_id") == cutoff.get("document_id")]
        states = {d["registration_status"] for d in evidence}
        start_now = next((d for d in evidence if d["registration_status"] == "open"), None)
        status = "unknown"
        if cutoff["date"] < today.isoformat():
            status = "closed"
        elif "suspended" in states:
            status = "suspended"
        elif "closed" in states:
            status = "unknown" if "open" in states else "closed"
        elif "not_open" in states:
            status = "unknown" if "open" in states else "not_open"
        elif begin and begin["date"] > today.isoformat():
            status = "upcoming"
        elif begin or start_now:
            status = "closing" if (date.fromisoformat(cutoff["date"]) - today).days <= 7 else "open"
        else:
            status = "deadline_only"
        windows.append(dict(track=track, status=status, deadline=cutoff,
                            start=begin, start_evidence=start_now, status_evidence=evidence))
    if not ends:
        for track in dict.fromkeys(d["track"] for d in assertions):
            evidence = [d for d in assertions if d["track"] == track]
            states = {d["registration_status"] for d in evidence}
            status = next(iter(states)) if len(states) == 1 else "unknown"
            windows.append(dict(track=track, status=status, deadline=None, start=None,
                                start_evidence=next((d for d in evidence if d["registration_status"] == "open"), None),
                                status_evidence=evidence))
    statuses = {w["status"] for w in windows}
    status = "unknown"
    if len(statuses) == 1:
        status = next(iter(statuses))
    elif statuses and statuses <= {"open", "closing"}:
        status = "open"
    elif statuses & {"open", "closing"}:
        status = "partial_open"
    # A plan cannot silently pick one group's deadline on behalf of the student.
    cutoff = windows[0]["deadline"] if len(windows) == 1 else None
    return {"dates": dates, "status": status, "deadline": cutoff,
            "registration_windows": windows,
            "next": next((d for d in dates if d["date"] >= today.isoformat()), None)}


def prepare_plan(notice, profile):
    if notice["policy_id"] != profile["policy_id"]:
        raise ValueError("公告与当前测评规则不一致")
    for old in store.all_of("plan"):
        if old.get("notice_id") == notice["id"] and old.get("profile_id") == profile["id"]:
            return old
    a = notice.get("analysis", {})
    tasks = ["核对当前届次、赛道、参赛资格与校内报名安排"]
    tasks += [str(x) for x in a.get("actions", []) + a.get("materials", [])]
    tasks = list(dict.fromkeys(tasks))
    t = timing(notice)
    plan_id = hashlib.sha256((profile["id"] + ":" + notice["id"]).encode()).hexdigest()[:32]
    return store.put("plan", dict(id=plan_id, title=notice["title"], policy_id=notice["policy_id"],
        profile_id=profile["id"], notice_id=notice["id"], url=notice.get("url", ""),
        date=(t["deadline"] or {}).get("date", ""), notes="公告提取的准备建议，请逐项核对。",
        checklist=[dict(id=uuid.uuid4().hex, text=x, done=False) for x in tasks], completed=False))


def scenario(policy, profile, item):
    if policy.get("state") != "active":
        raise ValueError("请先核对并启用当前规则方案")
    rule = next((r for r in policy["item_rules"] if r["id"] == item.get("rule_id")), None)
    if not rule:
        raise ValueError("请选择当前方案中的计分规则")
    for f in rule.get("fields", []):
        if item.get("values", {}).get(f["id"]) in (None, ""):
            raise ValueError("请先填写假设条件：" + f.get("label", f["id"]))
    if policy.get("date_window_required") and not item.get("date"):
        raise ValueError("请填写假设的获奖日期，用于核对测评时间范围")
    baseline = calculate(policy, profile)
    trial = deepcopy(profile)
    trial["items"] = [i for i in trial.get("items", []) if i.get("state") != "planned"]
    item = deepcopy(item)
    if item.get("same_item_id"):
        original = next((i for i in trial["items"] if i.get("id") == item["same_item_id"]), None)
        if not original:
            raise ValueError("选择的已有成果已变化，请重新打开测算")
        key = original.get("conflict_key") or "scenario-work:" + original["id"]
        original["conflict_key"] = item["conflict_key"] = key
    trial["items"].append({**item, "id": "scenario", "state": "planned"})
    after = calculate(policy, trial, True)
    return dict(baseline=baseline["total"], total=after["total"],
        gain=round(after["total"] - baseline["total"], 6),
        ledger=after["ledger"], notices=after["notices"], policy_version=policy.get("version", 1))


def application_pack(profile, policy):
    """Export only explicitly linked proof files, never the entire document library."""
    missing, lines = [], ["综测申报材料整理包", f"记录：{profile.get('name', '')}",
        f"规则：{policy.get('name', '')} 第 {policy.get('version', 1)} 版",
        "本包用于整理与自行核对，不代表学校审核通过。"]
    result = None
    try:
        if policy.get("state") != "active":
            raise ValueError("规则尚未核对启用")
        result = calculate(policy, profile)
        lines.append(f"当前已确认记录估算：{result['total']}（不含计划、待核对成果）")
        for step in result["steps"]:
            lines.append(f"{step.get('label', step['id'])} = {step['value']}；计算：{step['expression']}")
            for c in step.get("citations", []):
                lines.append(f"依据：{c.get('document_id')} 第{c.get('unit')}页/段：{c.get('quote', '')}")
        missing.extend(n.get("message", "") for n in result.get("notices", []))
    except ValueError as e:
        missing.append("无法计算：" + str(e))
    output = BytesIO()
    table = io.StringIO(newline="")
    writer = csv.writer(table)
    writer.writerow(["成果", "状态", "日期", "计分规则", "原始分", "计分说明", "材料说明"])
    rules = {r["id"]: r for r in policy.get("item_rules", [])}
    ledger = {r.get("id"): r for r in (result or {}).get("ledger", [])}
    def cell(v):
        s = str(v if v is not None else "")
        return "'" + s if s.startswith(("=", "+", "-", "@", "\t", "\r")) else s
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        linked = set(profile.get("document_ids", []))
        for index, item in enumerate(profile.get("items", []), 1):
            name = item.get("name", "未命名成果")
            rule = rules.get(item.get("rule_id"), {})
            row = ledger.get(item.get("id"), {})
            writer.writerow([cell(v) for v in [name, item.get("state"), item.get("date"),
                rule.get("label"), row.get("score"), row.get("reason"), item.get("evidence")]])
            lines += [f"\n{index}. {name}", "条件：" + "；".join(rule.get("requirements", []))]
            for c in rule.get("citations", []):
                lines.append(f"依据：{c.get('document_id')} 第{c.get('unit')}页/段：{c.get('quote', '')}")
            if item.get("state") != "confirmed":
                missing.append(f"{name}：{ '计划尚未取得' if item.get('state') == 'planned' else '材料待本人核对'}")
            if not item.get("date"):
                missing.append(f"{name}：缺少证明落款日期")
            if row.get("reason"):
                missing.append(f"{name}：{row['reason']}")
            if not item.get("document_ids"):
                missing.append(f"{name}：尚未关联证明文件；文字说明不等于原始附件")
            linked.update(item.get("document_ids", []))
        for index, doc_id in enumerate(sorted(linked), 1):
            try:
                doc = store.get("document", doc_id)
                path = Path(doc.get("path") or "")
                if not path.is_file():
                    raise ValueError("原文件不可用")
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", doc.get("name", path.name))
                z.write(path, f"证明文件/{index:03d}-{name}")
                lines.append(f"附文件：{name}（{doc_id}）")
            except (ValueError, OSError) as e:
                missing.append(f"文件 {doc_id}：{e}")
        z.writestr("成果汇总.csv", "\ufeff" + table.getvalue())
        z.writestr("计分与依据.txt", "\n".join(lines))
        z.writestr("待补材料.txt", "\n".join(missing) or "未发现自动检查项，请继续核对学校申报要求。")
        z.writestr("记录快照.json", json.dumps(dict(profile=profile, policy=policy, result=result), ensure_ascii=False, indent=2))
    return output.getvalue()
