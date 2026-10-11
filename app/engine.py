"""Institution-independent, non-executable scoring expressions and audit trail.

No institution names, weights or category IDs belong in this module.
"""

import ast
import math
import operator
import re
from copy import deepcopy
from datetime import date

OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


def expression(text, names, functions=None):
    if not isinstance(text, str) or len(text) > 3000:
        raise ValueError("公式须为不超过 3000 字符的文本")
    try:
        root = ast.parse(text, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"公式语法错误：{text}") from e
    if len(list(ast.walk(root))) > 400:
        raise ValueError("公式过于复杂")
    funcs = {"min": min, "max": max, "round": round, "abs": abs, **(functions or {})}
    names = {"true": True, "false": False, **names}

    def visit(n):
        if isinstance(n, ast.Expression):
            return visit(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float, str, bool, type(None))):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in names:
                raise ValueError(f"缺少字段或前置公式：{n.id}")
            return names[n.id]
        if isinstance(n, (ast.List, ast.Tuple)):
            return [visit(x) for x in n.elts]
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            return OPS[type(n.op)](visit(n.left), visit(n.right))
        if isinstance(n, ast.UnaryOp):
            v = visit(n.operand)
            if isinstance(n.op, ast.USub):
                return -v
            if isinstance(n.op, ast.UAdd):
                return +v
            if isinstance(n.op, ast.Not):
                return not v
        if isinstance(n, ast.BoolOp):
            if isinstance(n.op, ast.And):
                return all(visit(v) for v in n.values)
            if isinstance(n.op, ast.Or):
                return any(visit(v) for v in n.values)
        if isinstance(n, ast.Compare):
            left = visit(n.left)
            for op, right in zip(n.ops, n.comparators):
                value = visit(right)
                if type(op) not in OPS:
                    raise ValueError("不支持的比较")
                if not OPS[type(op)](left, value):
                    return False
                left = value
            return True
        if isinstance(n, ast.IfExp):
            return visit(n.body if visit(n.test) else n.orelse)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs and not n.keywords:
            return funcs[n.func.id](*[visit(a) for a in n.args])
        raise ValueError("公式包含不支持的操作；支持算术、比较、条件表达式和规则函数")

    try:
        result = visit(root)
        if isinstance(result, float) and not math.isfinite(result):
            raise ValueError("公式产生非有限数值")
        return result
    except (ZeroDivisionError, TypeError, KeyError, IndexError) as e:
        raise ValueError(f"公式无法计算：{text}；{e}") from e


def normalize(s):
    return re.sub(r"\s|[．·]", "", str(s))


def validate_policy(p, documents=None):
    errors = []
    if not isinstance(p, dict):
        return ["规则方案须为 JSON 对象"]
    for key in ["name", "inputs", "tables", "item_rules", "formulas", "total"]:
        if key not in p:
            errors.append(f"缺少 {key}")
    if errors:
        return errors
    ids = []
    for part in ["inputs", "tables", "item_rules", "formulas"]:
        if not isinstance(p[part], list):
            errors.append(f"{part} 须为数组")
            continue
        for obj in p[part]:
            if not isinstance(obj, dict):
                errors.append(f"{part} 的每项须为对象")
                continue
            id = obj.get("id", "")
            if not isinstance(id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", id):
                errors.append(f"无效标识：{id}")
            ids.append(id)
    if errors:
        return errors
    for obj in p["tables"] + p["item_rules"]:
        fields = obj.get("fields", [])
        if not isinstance(fields, list) or any(
            not isinstance(f, dict) or not isinstance(f.get("id"), str) for f in fields
        ):
            errors.append(f"{obj['id']} fields 须为包含 id 的字段对象数组")
    for obj in p["item_rules"] + p["formulas"]:
        if not isinstance(obj.get("expression"), str):
            errors.append(f"{obj['id']} expression 须为文本")
        cites = obj.get("citations", [])
        if not isinstance(cites, list) or any(not isinstance(c, dict) for c in cites):
            errors.append(f"{obj['id']} citations 须为引用对象数组")
    if not isinstance(p.get("constraints", []), list) or any(
        not isinstance(c, dict) for c in p.get("constraints", [])
    ):
        errors.append("constraints 须为对象数组")
    if not isinstance(p.get("lookups", {}), dict):
        errors.append("lookups 须为对象")
    if errors:
        return errors
    if len(ids) != len(set(ids)):
        errors.append("标识重复")
    if p["total"] not in [x.get("id") for x in p["formulas"]]:
        errors.append("total 必须指向一个公式")
    for t in p["tables"]:
        if not t.get("fields"):
            errors.append(f"表 {t['id']} 缺少字段")
    for obj in p["item_rules"] + p["formulas"]:
        expr = obj.get("expression", "")
        try:
            ast.parse(expr, mode="eval")
        except SyntaxError:
            errors.append(f"{obj['id']} 公式语法错误")
        cites = obj.get("citations", [])
        if not cites:
            errors.append(f"{obj['id']} 缺少原文依据")
        if documents is not None:
            for c in cites:
                doc = documents.get(c.get("document_id"))
                idx = c.get("unit", 0)
                if not doc or not isinstance(idx, int) or idx < 1 or idx > len(doc["units"]):
                    errors.append(f"{obj['id']} 来源位置无效")
                    continue
                source = doc["units"][idx - 1]["text"] + "\n" + doc["units"][idx - 1].get("vision_text", "")
                # Tables may add normalized strings absent from extraction reading order.
                source += " ".join(
                    str(cell)
                    for grid in doc["units"][idx - 1].get("tables", [])
                    for row in grid
                    for cell in row
                    if cell
                )
                if len(normalize(c.get("quote", ""))) < 4 or normalize(c["quote"]) not in normalize(source):
                    errors.append(f"{obj['id']} 引文与来源不匹配：{c.get('quote', '')[:60]}")
    # Validate expression dependencies even in branches not exercised by current data.
    names = {f["id"] for f in p["inputs"]} | {"true", "false"}
    table_fields = {t["id"]: {f["id"] for f in t["fields"]} for t in p["tables"]}
    functions = {
        "min",
        "max",
        "round",
        "abs",
        "lookup",
        "sum_rows",
        "mean_rows",
        "count_rows",
        "awards",
        "award_rule",
    }
    rule_ids = {r["id"] for r in p["item_rules"]}
    categories = {r.get("category", "") for r in p["item_rules"]}

    def check(expr, available, label):
        try:
            tree = ast.parse(expr, mode="eval")
        except (SyntaxError, TypeError):
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id not in available | functions:
                errors.append(f"{label} 使用未定义字段：{node.id}")
            if isinstance(
                node,
                (
                    ast.Attribute,
                    ast.Subscript,
                    ast.Lambda,
                    ast.ListComp,
                    ast.DictComp,
                    ast.GeneratorExp,
                    ast.NamedExpr,
                ),
            ):
                errors.append(f"{label} 使用不支持的表达式")
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id not in functions:
                errors.append(f"{label} 调用不支持的函数")
                continue
            fn = node.func.id
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            target = node.args[0].value
            if fn in {"sum_rows", "mean_rows", "count_rows"}:
                if target not in table_fields:
                    errors.append(f"{label} 引用不存在的表 {target}")
                    continue
                count = {"sum_rows": 3, "mean_rows": 4, "count_rows": 2}[fn]
                for arg in node.args[1:count]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        check(arg.value, available | table_fields[target], label)
            if fn == "award_rule" and target not in rule_ids:
                errors.append(f"{label} 引用不存在的成果规则 {target}")
            if fn == "awards" and target not in categories:
                errors.append(f"{label} 引用不存在的成果分类 {target}")
            if fn == "lookup" and target not in p.get("lookups", {}):
                errors.append(f"{label} 引用不存在的计分表 {target}")

    for r in p["item_rules"]:
        check(r.get("expression", ""), names | {f["id"] for f in r.get("fields", [])}, r["id"])
        if r.get("group_by"):
            check(r["group_by"], names | {f["id"] for f in r.get("fields", [])}, r["id"])
    for f in p["formulas"]:
        check(f.get("expression", ""), names, f["id"])
        names.add(f["id"])
    for c in p.get("constraints", []):
        check(c.get("expression", ""), names, "资格条件")
    return list(dict.fromkeys(errors))


def field_values(fields, values):
    result = {}
    for f in fields:
        name = f["id"]
        v = values.get(name, f.get("default"))
        if v is None or v == "":
            if f.get("required", True):
                raise ValueError(f"请填写 {f.get('label', name)}")
            v = 0 if f.get("type", "number") == "number" else ""
        if f.get("type", "number") == "number":
            v = float(v)
            if not math.isfinite(v):
                raise ValueError(f"{name} 不是有效数值")
            if "min" in f and v < f["min"] or "max" in f and v > f["max"]:
                raise ValueError(f"{f.get('label', name)} 超出允许范围")
        if f.get("type") == "boolean":
            if not isinstance(v, bool):
                raise ValueError(f"{name} 须为是或否")
        if f.get("options") and v not in [x["value"] if isinstance(x, dict) else x for x in f["options"]]:
            raise ValueError(f"{f.get('label', name)} 选项无效")
        result[name] = v
    return result


def calculate(policy, profile, include_planned=False):
    env = field_values(policy["inputs"], profile.get("inputs", {}))
    tables = {}
    for t in policy["tables"]:
        tables[t["id"]] = [
            field_values(t["fields"], r)
            for r in profile.get("tables", {}).get(t["id"], [])
            if not r.get("_excluded")
        ]

    def lookup(name, *keys):
        obj = policy.get("lookups", {}).get(name)
        for k in keys:
            if not isinstance(obj, dict) or str(k) not in obj:
                raise ValueError(f"计分表 {name} 中缺少 {keys}")
            obj = obj[str(k)]
        return obj

    funcs = {"lookup": lookup}

    def rows(table, cond="True"):
        if table not in tables:
            raise ValueError(f"缺少表格 {table}")
        return [r for r in tables[table] if expression(cond, {**env, **r}, funcs)]

    def sum_rows(table, expr, cond="True", top=0):
        values = [expression(expr, {**env, **r}, funcs) for r in rows(table, cond)]
        if top:
            if int(top) != top or top < 0:
                raise ValueError("取前 N 项的 N 必须为正整数")
            values = sorted(values, reverse=True)[: int(top)]
        return sum(values)

    def mean_rows(table, value, weight, cond="True"):
        denom = sum_rows(table, weight, cond)
        if denom <= 0:
            raise ValueError(f"{table} 没有可计入的有效权重")
        return sum_rows(table, f"({value})*({weight})", cond) / denom

    funcs.update(
        sum_rows=sum_rows,
        mean_rows=mean_rows,
        count_rows=lambda table, cond="True": len(rows(table, cond)),
    )
    ledger = []
    rules = {r["id"]: r for r in policy["item_rules"]}
    for item in profile.get("items", []):
        row = {**deepcopy(item), "score": 0, "status": "excluded", "reason": ""}
        if item.get("state") == "planned" and not include_planned:
            row["reason"] = "计划项目，未计入已获成果"
            ledger.append(row)
            continue
        if item.get("state", "pending") not in {"confirmed", "planned"}:
            row["reason"] = "材料待确认"
            ledger.append(row)
            continue
        rule = rules.get(item.get("rule_id"))
        if not rule:
            raise ValueError("成果使用了不存在的规则")
        if policy.get("date_window_required", False):
            if not profile.get("period_start") or not profile.get("period_end"):
                raise ValueError("请填写本次测评材料起止日期")
            start = date.fromisoformat(profile["period_start"])
            end = date.fromisoformat(profile["period_end"])
            if end < start:
                raise ValueError("测评结束日期早于开始日期")
            if not item.get("date"):
                row["reason"] = "缺少证明材料日期"
                ledger.append(row)
                continue
            when = date.fromisoformat(item["date"])
            if not start <= when <= end:
                row["reason"] = "不在测评时间范围内"
                ledger.append(row)
                continue
        vals = field_values(rule.get("fields", []), item.get("values", {}))
        row["score"] = float(expression(rule["expression"], {**env, **vals}, funcs))
        row["status"] = "counted"
        row["category"] = rule.get("category", "")
        row["citations"] = rule.get("citations", [])
        row["expression"] = rule["expression"]
        row["values"] = vals
        if rule.get("group_by"):
            row["auto_group"] = str(expression(rule["group_by"], {**env, **vals}, funcs))
        ledger.append(row)
    # Explicit conflict identifiers refer to the same work/event. They work across categories.
    # Each group can allow sum, max or require a choice, as declared by the active policy.
    groups = {}
    for row in ledger:
        if row["status"] == "counted":
            if row.get("auto_group"):
                groups.setdefault("auto:" + row["auto_group"], []).append(row)
            if row.get("conflict_key"):
                groups.setdefault("work:" + row["conflict_key"].strip(), []).append(row)
    for key, group in groups.items():
        if len(group) < 2:
            continue
        mode = policy.get("duplicate_mode", "max")
        if mode == "sum":
            continue
        if mode == "block":
            raise ValueError(f"同一项目 {key} 有重复记录，请选择计分项")
        group = [r for r in group if r["status"] == "counted"]
        if not group:
            continue
        best = max(group, key=lambda r: r["score"])
        for row in group:
            if row is not best:
                row["status"] = "excluded"
                row["reason"] = f"同一项目取最高，已计入 {best.get('name', '另一记录')}"
                row["score"] = 0
    funcs["awards"] = lambda category: sum(
        r["score"] for r in ledger if r["status"] == "counted" and r.get("category") == category
    )
    funcs["award_rule"] = lambda id: sum(
        r["score"] for r in ledger if r["status"] == "counted" and r.get("rule_id") == id
    )
    steps = []
    for f in policy["formulas"]:
        v = expression(f["expression"], env, funcs)
        env[f["id"]] = v
        steps.append({**f, "value": round(v, 8)})
    notices = []
    for c in policy.get("constraints", []):
        if not expression(c["expression"], env, funcs):
            notices.append(c)
            if c.get("severity") == "block":
                raise ValueError(c["message"])
    return dict(
        total=round(env[policy["total"]], policy.get("precision", 4)),
        steps=steps,
        ledger=ledger,
        notices=notices,
        include_planned=include_planned,
        policy_id=policy.get("id"),
        policy_version=policy.get("version", 1),
    )


def marginal(policy, profile):
    base = calculate(policy, profile)
    results = []
    for f in policy["inputs"]:
        if f.get("type", "number") != "number":
            continue
        p = deepcopy(profile)
        value = float(p.get("inputs", {}).get(f["id"], f.get("default", 0)) or 0)
        step = f.get("step", 1)
        if value + step > f.get("max", math.inf):
            continue
        p.setdefault("inputs", {})[f["id"]] = value + step
        try:
            gain = calculate(policy, p)["total"] - base["total"]
            results.append(dict(label=f.get("label", f["id"]), change=step, gain=round(gain, 6)))
        except ValueError:
            pass
    return sorted(results, key=lambda r: -abs(r["gain"]))


def planned_gains(policy, profile):
    baseline = calculate(policy, profile)["total"]
    values = []
    for item in profile.get("items", []):
        if item.get("state") != "planned":
            continue
        scenario = deepcopy(profile)
        scenario["items"] = [
            i for i in scenario["items"] if i.get("state") != "planned" or i.get("id") == item.get("id")
        ]
        try:
            result = calculate(policy, scenario, True)
            values.append(
                dict(id=item.get("id"), name=item.get("name"), gain=round(result["total"] - baseline, 6))
            )
        except ValueError as e:
            values.append(dict(id=item.get("id"), name=item.get("name"), gain=None, error=str(e)))
    return sorted(values, key=lambda x: -(x["gain"] or 0))
