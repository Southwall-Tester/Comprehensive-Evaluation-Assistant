import asyncio
import json
import re
import hashlib
from copy import deepcopy
from . import store
from .engine import validate_policy
from .ingestion import preview
from .llm import complete, context_for, extract_policy, settings, POLICY_CONTRACT


async def audit_policy(policy, docs, log):
    """Compile small rule groups independently, then reconcile the aggregates.

    This prevents a long document's final formulas from hiding incorrect item rules.
    """
    sem = asyncio.Semaphore(2)

    async def one(rule):
        async with sem:
            cache_key = hashlib.sha256(
                json.dumps(
                    [rule, [(d["id"], d.get("updated_at")) for d in docs], settings()["model"], "audit-v2"],
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            cache_dir = store.DATA / "rule-audits"
            cache_dir.mkdir(exist_ok=True)
            cache = cache_dir / (cache_key + ".json")
            if cache.exists():
                return json.loads(cache.read_text(encoding="utf8"))
            log("逐项复核：" + rule.get("label", rule["id"]))
            selected = []
            cited = {(c.get("document_id"), c.get("unit")) for c in rule.get("citations", [])}
            for d in docs:
                units = [
                    u
                    for u in d["units"]
                    if any(
                        d["id"] == did and isinstance(i, int) and abs(u["index"] - i) <= 1 for did, i in cited
                    )
                ]
                if units:
                    selected.append({**d, "units": units})
            if not selected:
                selected = docs
            prompt = (
                """复核一个综测计分子项，依据原文修复其条件和数学逻辑。输出严格JSON：
{"rule":{完整修复后的当前item_rule，id和category保持不变},"lookups":{此子项引用的完整计分表},"issues":["发现且已修复的问题"],"unresolved":["仍需人工确定的真实歧义"]}。
item_rule包含id,label,category,fields,expression,requirements,citations，可选group_by。
只处理本子项，不修改其他子项或生成总分公式。每个字段都有中文label及number/select/boolean/text类型，select.options为字符串数组。
表达式只能使用fields中的变量及min/max/round/abs/lookup，支持算术、比较、条件表达式与and/or/not。不能使用str、int、索引、属性、自定义函数。布尔写True/False。
每个lookup返回数值或原文映射的字符串，键值与fields选项严格一致。不要默认已经经过学院认定。
比例上限是min(实际贡献比例,位次上限)，不要将两比例再次相乘；独立倍率例如short paper与best paper需按原文是否可同时应用检查。
赛事级别必须是显式字段，类别系数与级别升降分开运算；不能把所有比赛当全国级、不能误把所有A类赛事当ICPC。
同种资格认证取最高的group_by按考试种类分组，而不是按奖项/分数分组。
不同论文、作品、专利、实践事件可累计时禁止按级别/作者排名/类型添加group_by；统一由用户填写同一项目conflict_key实现去重。除了原文明定“同种考试仅取最高”等条款，不设置group_by。
原文无法确定的加分，建立人工认定分数字段和已认定布尔值，认定前返回0并列unresolved，不能自行套错表。
跨类别封顶由外部汇总，不在本规则伪造每条记录独立封顶。不要把“同一项目不得重复计分”实现为两份成果都计零。
引文须是来源中连续出现的原文，不可拼接跨页文字。用短正文引用，公式和表格数字可由视觉校读复核。
待修复子项："""
                + json.dumps(rule, ensure_ascii=False)
                + "\n当前计分表："
                + json.dumps(policy.get("lookups", {}), ensure_ascii=False)
                + "\n相关原文："
                + context_for(selected)
            )
            result, meta = await complete(prompt, json_output=True, max_tokens=8000)
            fixed = result["rule"]
            if fixed.get("id") != rule["id"] or fixed.get("category") != rule.get("category"):
                raise ValueError("子项复核改变了稳定标识，请重试")
            record = [
                fixed,
                result.get("lookups", {}),
                result.get("issues", []),
                result.get("unresolved", []),
                meta,
            ]
            cache.write_text(json.dumps(record, ensure_ascii=False), encoding="utf8")
            return record

    raw_results = await asyncio.gather(*[one(r) for r in policy["item_rules"]], return_exceptions=True)
    results = []
    for original, res in zip(policy["item_rules"], raw_results):
        if isinstance(res, Exception):
            log(original.get("label", original["id"]) + " 复核暂未完成，已保留草稿")
            results.append([original, {}, [], ["模型复核失败：" + str(res)], {}])
        else:
            results.append(res)
    policy = dict(policy)
    policy["item_rules"] = [x[0] for x in results]
    issue_log = []
    for r, lookups, issues, unknown, meta in results:
        # Give revised lookups per-rule namespaces so parallel audits cannot overwrite a sibling.
        for name, value in lookups.items():
            new_name = r["id"] + "__" + name
            r["expression"] = (
                r["expression"]
                .replace("'" + name + "'", "'" + new_name + "'")
                .replace('"' + name + '"', '"' + new_name + '"')
            )
            policy.setdefault("lookups", {})[new_name] = value
        issue_log.append(dict(rule_id=r["id"], issues=issues, unresolved=unknown, generation=meta))
    log("复核跨子项封顶、课程筛选和总分公式")
    errors = validate_policy(policy, {d["id"]: d for d in docs})
    prompt = (
        """复核综测方案的基础字段、课程表、汇总公式与资格约束。只返回JSON {"inputs":完整输入数组,"tables":完整课程表数组,"formulas":完整公式数组,"constraints":完整约束数组,"total":"总分公式id","unresolved":["剩余真实歧义"]}。
已逐项审校的item_rules不要修改。根据每个item_rule的category/id正确汇总，子项封顶、分类封顶与总上限分层实施，每项只算一次。
特别核对课程分数为0仍参与平均，重修等是否排除，必选课是否从其他选修加分里排除，最多选几门应由明确的选择字段而不是偷偷按积分最优挑选。
同一项目已由引擎去重，无需再次扣分；通报表扬等分组上限必须在总汇总处封顶，而非每条记录单独封顶。
所有“经学院认定满分”布尔输入必须参与对应公式。无法确认资格时提示，而非虚构禁止算分。
不要把默认基准分做成可任意调整的字段，应以原文常数减去填写的扣分来计算。
只有必填学生事实为inputs，不要求用户填写项目无关的冗余参数。全部保留文档引用，引用用短正文连续原文。
安全公式函数 min/max/round/abs/lookup/sum_rows/mean_rows/count_rows/awards/award_rule，其他语法仅算术、布尔、比较、条件表达式。公式依次执行。
表sum_rows(table,行算式,筛选条件,可选topN)；mean_rows(table,分数算式,学分算式,筛选条件)。
完整方案："""
        + json.dumps(policy, ensure_ascii=False)
        + "\n校验错误："
        + json.dumps(errors, ensure_ascii=False)
        + "\n原文："
        + context_for(docs)
    )
    try:
        aggregate, meta = await complete(prompt, json_output=True, max_tokens=14000)
        candidate = deepcopy(policy)
        for k in ["inputs", "tables", "formulas", "constraints", "total", "unresolved"]:
            candidate[k] = aggregate[k]
        candidate_errors = validate_policy(candidate)
        structural = [
            e
            for e in candidate_errors
            if any(word in e for word in ["须为", "每项", "缺少字段", "无效标识", "标识重复"])
        ]
        if structural:
            raise ValueError("汇总复核结构未通过校验：" + "；".join(structural[:5]))
        policy = candidate
    except (ValueError, KeyError) as e:
        meta = {"error": str(e)}
        policy.setdefault("unresolved", []).append("汇总复核未完成：" + str(e))
    policy["audit"] = issue_log
    for entry in issue_log:
        policy.setdefault("unresolved", []).extend(entry["unresolved"])
    policy["aggregate_audit"] = meta
    policy["validation_errors"] = validate_policy(policy, {d["id"]: d for d in docs})
    # Resolve a wrong page number only when the literal quotation uniquely matches another unit.
    for obj in policy["item_rules"] + policy["formulas"]:
        for c in obj.get("citations", []):
            from .engine import normalize

            quote = normalize(c.get("quote", ""))
            matches = [
                (d["id"], u["index"])
                for d in docs
                for u in d["units"]
                if len(quote) >= 4
                and (quote in normalize(u["text"]) or quote in normalize(u.get("vision_text", "")))
            ]
            if len(matches) == 1:
                c.update(document_id=matches[0][0], unit=matches[0][1])
    policy["validation_errors"] = validate_policy(policy, {d["id"]: d for d in docs})
    policy["state"] = "draft"
    try:
        return await repair_policy_errors(policy, docs, log)
    except ValueError as e:
        policy.setdefault("unresolved", []).append("自动修正未完成：" + str(e))
        return policy


async def repair_policy_errors(policy, docs, log):
    for attempt in range(2):
        errors = validate_policy(policy, {d["id"]: d for d in docs})
        if not errors:
            break
        log(f"修正可定位的公式或引文错误：{len(errors)} 项")
        targets = [
            obj
            for obj in policy["item_rules"] + policy["formulas"]
            if any(e.startswith(obj["id"] + " ") for e in errors)
        ]
        result, meta = await complete(
            '仅修复下面规则对象的语法错误、未定义变量和原文引用，输出JSON {"repairs":[{"id":"对象id","expression":"修正公式，没变可省略","citations":[{"document_id":"id","unit":1,"quote":"短句连续逐字原文，不能跨页拼接，不能复制不存在的数学公式"}]}]}。保持已正确的公式数值及逻辑不变。确保括号配对，每个引文优先复制正文短句。\n错误：'
            + json.dumps(errors, ensure_ascii=False)
            + "\n需要修复对象："
            + json.dumps(targets, ensure_ascii=False)
            + "\n所有可用字段与表格："
            + json.dumps({"inputs": policy["inputs"], "tables": policy["tables"]}, ensure_ascii=False)
            + "\n原文："
            + context_for(docs),
            json_output=True,
            max_tokens=12000,
        )
        byid = {obj["id"]: obj for obj in policy["item_rules"] + policy["formulas"]}
        for fix in result.get("repairs", []):
            if fix.get("id") not in byid:
                continue
            for k in ["expression", "citations"]:
                if k in fix:
                    byid[fix["id"]][k] = fix[k]
        policy.setdefault("repairs", []).append(meta)
    policy["validation_errors"] = validate_policy(policy, {d["id"]: d for d in docs})
    return policy


async def visual_read(doc, log, all_pages=False):
    selected = [
        u
        for u in doc["units"]
        if (
            u.get("needs_ocr")
            or u.get("needs_visual_check")
            or u.get("tables")
            or re.search(r"[∑\ufffd]|计算公式|公式为", u["text"])
            or all_pages
        )
        and not u.get("vision_text")
    ]
    if not selected:
        return doc
    if not settings().get("vision"):
        if any(u.get("needs_ocr") for u in selected):
            raise ValueError("扫描页待识别，请配置支持图像的模型并启用视觉输入")
        log("公式/表格尚未视觉校读，已保留页面图像")
        return doc
    for u in selected:
        if doc["kind"] not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            continue
        log(f"视觉校读：{doc['name']} · {u['label']}")
        text, meta = await complete(
            "请逐字转写这张规则文件页面为中文Markdown。完整保留所有正文、公式、表格的行列关系、数字小数点和脚注。公式同时用可读的数学表达写出。不要解释或总结，不补写被截断的句子。表格空单元格保留。只输出转写内容。",
            images=[await asyncio.to_thread(preview, doc, u["index"])],
            max_tokens=7000,
        )
        u["vision_text"] = text
        u["vision_generation"] = meta
        u["needs_ocr"] = False
        store.put("document", doc)
    return doc


async def build_policy(docs, log):
    for i, d in enumerate(docs):
        docs[i] = await visual_read(d, log)
    log("从完整材料建立字段、公式、计分条件和赛事目录")
    policy, meta = await extract_policy(docs)
    policy.update(document_ids=[d["id"] for d in docs], state="draft", generation=meta)
    policy["validation_errors"] = validate_policy(policy, {d["id"]: d for d in docs})
    policy = store.put("policy", policy)
    errors = validate_policy(policy, {d["id"]: d for d in docs})
    log("审校公式引用、层级封顶、零分课程和特殊条款")
    prompt = (
        POLICY_CONTRACT
        + """
本轮是修复审校：输出修正后的完整方案JSON。检查草稿的每条公式与源文对应。
重点排查：错误小数点、同一规则被两个类别重复累计、子类封顶未生效、排除零分课程、认定满分输入未使用、成员与负责人资格混淆、同种认证重复计算、漏列规则。
同类资格多次只取最高可定义item_rule.group_by表达式，例如固定字符串 'exam_family' 或 fields 中的类型，再由全局 duplicate_mode 处理；group_by返回全局唯一前缀加分类名。
每类成果独立item_rule及category，fields保持必要，不同时要求论文和其他作品互不相关字段。公式必须使用正确的常量布尔 True/False。
不应默认省略未满足材料要求的成果；用规则字段呈现条件，并在expression显式判断。
原始文字提取的公式/表格乱序时，使用视觉校读准确公式；引文选可逐字匹配的短正文而非你重建的公式。
完整补上漏掉的全部计分项目和赛事赛道；人工资格判断列requirements，未被计算处理的例外明确放unresolved。
返回修正后的完整JSON而不是问题列表。
当前校验错误："""
        + json.dumps(errors, ensure_ascii=False)
        + "\n草稿："
        + json.dumps(policy, ensure_ascii=False)
        + "\n全文来源："
        + context_for(docs)
    )
    try:
        fixed, review_meta = await complete(prompt, json_output=True, max_tokens=32000)
    except ValueError as e:
        fixed = policy
        review_meta = {"error": str(e)}
        log("整体审校未完成，保留草稿并继续逐项核查")
    if not isinstance(fixed, dict) or validate_policy(fixed, {d["id"]: d for d in docs}):
        log("整体修订尚有校验问题，继续核查已保存的原始草稿")
        fixed = policy
    fixed.update(
        id=policy["id"],
        document_ids=policy["document_ids"],
        state="draft",
        generation=meta,
        review_generation=review_meta,
    )
    store.put("policy", fixed)
    try:
        fixed = await audit_policy(fixed, docs, log)
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        fixed.setdefault("unresolved", []).append("自动复核未完成：" + str(e))
        fixed["validation_errors"] = validate_policy(fixed, {d["id"]: d for d in docs})
        log("已保留可编辑草稿；自动复核未完成")
    if fixed["validation_errors"]:
        log(f"生成完毕，有 {len(fixed['validation_errors'])} 处引文/结构待修正")
    else:
        log("规则已生成，等待核对后启用")
    return store.put("policy", fixed)
