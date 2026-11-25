"""Discover student benefits on the selected university's public websites."""

import asyncio
import hashlib
import re
from datetime import date
from itertools import zip_longest
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

from . import store
from .llm import settings
from .research import allowed, fetch, search

# Starting directories only. Benefit details are read from their current pages.
SCHOOLS = {
    "武汉大学": ("whu.edu.cn", (
        "https://zzgl.whu.edu.cn/", "https://ems.whu.edu.cn/", "https://oir.whu.edu.cn/",
        "https://future.whu.edu.cn/", "https://uc.whu.edu.cn/", "https://cs.whu.edu.cn/",
        "https://xgb.whu.edu.cn/", "https://gs.whu.edu.cn/", "https://zwhqb.whu.edu.cn/zhxx/tzgg.htm",
        "https://www.lib.whu.edu.cn/", "https://oldwww.lib.whu.edu.cn/",
    )),
}
TOPICS = (
    ("奖助与补贴", "学生 助学金 奖学金 补贴 申请",
     r"奖学金|助学金|励学金|寒衣补助|困难补[贴助]|生活补助|求职(?:创业)?补贴|学费(?:减免|补偿|代偿)|"
     r"助学贷款贴息|课程补贴|教材补贴|就业补贴|伙食补贴|临时补助|路费补助"),
    ("勤工助学", "学生 勤工助学 岗位 招聘", r"勤工助学|勤工俭学|学生助[理管].{0,8}招[聘募]|招[聘募].{0,20}学生助[理管]"),
    ("学习资源", "学生 正版软件 图书馆 文献传递 免费",
     r"正版软件|软件授权|软件许可|文献传递|馆际互借|数据库.{0,8}试用|开通试用|数据库免费|免费数据库"),
    ("校园生活", "在校学生 免费服务 学生优惠 领取",
     r"学生优惠|学生票|免费开放|免费使用|免费预约|免费体检|免费借用|免费领取|教育优惠|交通补贴|餐费补贴|无障碍房申请"),
)
# These headlines are leads. Only an explicit offer in the article earns a card.
CONDITIONAL_TOPICS = (
    ("国际交流资助", r"(?:选派|申请).{0,65}(?:赴|交流项目|暑期项目|寒假课程)",
     r"(?:可|有机会|有资格)[^。；，]{0,12}申请[^。；，]{0,12}(?:奖学金|资助)|"
     r"(?:提供|可获|设有)[^。；，]{0,14}(?:奖学金|资助|学费减免)|(?:减免|免收|免交|免缴)[^。；，]{0,8}学费"),
    ("科创支持", r"重点培育项目|组织参加.{0,50}设计竞赛",
     r"(?:给予|提供|获得).{0,16}经费支持|配备.{0,12}导师|协助匹配.{0,20}指导教师"),
    ("学习资源", r"培训预告|数据库.{0,12}发布",
     r"(?:培训|讲座).{0,15}(?:无需报名|免费)|(?:开放研究数据平台.{0,10}公开发布|公开下载|免费下载)"),
)
CHANNEL = re.compile(r"学生资助|资助中心|办事指南|图书馆|学生工作|通知公告|服务指南|岗位招聘|数据库资源|学生通知|海外学习")
EXCLUDED = re.compile(r"公示|获奖名单|受助名单|评选结果|评审结果|颁奖|颁发仪式|表彰大会|采购|招标|中标|"
                      r"新闻回顾|停止办理|停止服务|到账通知|劳酬统计填报|名额已满|[（(]已满[）)]")
TOPIC_INDEX = re.compile(r"^(?:奖助学金|奖学金|助学金|勤工助学|学生资助|校园福利)(?:\s*[-—_|｜].*)?$")
VALUE = (r"全额|免费|免收|减免|每(?:人|生|月|学年|学期).{0,12}\d|\d+\s*(?:元|%|％).{0,6}(?:补贴|补助)|"
         r"开通.{0,55}数据库|采购.{0,20}发给",
         r"提供|配备|资助标准|补贴标准|岗位报酬|可借|可享|资助金额|补助金额")
AUDIENCE = (r"(?:资助|面向|服务对象为|资助对象为|申请对象为|凡)[^。]{0,55}(?:学生|本科|研究生|师生)",
            r"(?:申请对象|适用对象|服务对象|申请条件)[为：:].{4,}",
            r"在校|全日制|本科生|研究生|全校师生|本校师生|本校用户|我校师生|本校读者")
METHOD = (r"登录|登陆|提交申请|填写.{0,15}申请|凭.{1,15}(?:领取|办理|预约)|扫描.{0,8}二维码",
          r"通过.{1,35}(?:申请|办理|领取|预约)|向.{1,24}(?:申请|提交)|申请入口|办理地点|领取地点|校园\s*(?:网\s*)?IP.{0,20}访问")
TERMS = re.compile(r"服务年限|毕业后.{0,35}(?:就业|工作|服务)|违约.{0,20}(?:返还|退还|偿还)|"
                   r"(?:不得|不可|不能).{0,10}(?:兼得|兼报|重复申领|同时享受)|未享受.{0,25}其他.{0,12}助学金|"
                   r"同一家庭.{0,15}(?:一人|1人)|仅对校园网开放|校外.{0,16}VPN|"
                   r"自理.{0,12}学费|学费.{0,20}自理|试用有效期", re.I)
APPLICATION = r"(?:申请|申报|申领|办理|领取|报名|提交材料)"
WINDOW = re.compile(rf"{APPLICATION}(?:的|受理)?(?:截止|截至|起止|时间|时限|期限|期间|日期)"
                    rf"|(?:在|于|自|从)[^，,。；;]{{0,45}}(?:年|月|日|号)[^，,。；;]{{0,32}}{APPLICATION}"
                    rf"|(?:截止|截至|前)[^，,。；;]{{0,10}}{APPLICATION}")
UNIT_SUBMISSION = re.compile(r"(?:^|[，,；;])\s*(?:[\d一二三四五六七八九十]+[.．、)]\s*)?(?:请)?(?:各|所在)?"
                             r"(?:学院|院系|培养单位|学校|分团委)[^。；;]{0,110}(?:报送|报至|汇总|送校|上报|发送)")
FULL_DATE = r"(?<!\d)(\d{4})\s*(?:年|[-./])\s*(\d{1,2})\s*(?:月|[-./])\s*(\d{1,2})(?!\d)\s*日?"
DATE_TOKEN = re.compile(FULL_DATE)
LANDING_CONTENT = (".v_news_content", "#vsb_content", ".wp_articlecontent", ".TRS_Editor",
                   ".article-content", ".article_content", ".titleContent .content", ".artice",
                   "article", "main", "#content", ".content")


def school_domain(value):
    value = str(value or "").strip().lower()
    address = urlsplit(value if "://" in value else "https://" + value)
    host = (address.hostname or "").rstrip(".").removeprefix("www.")
    if (address.scheme not in {"https", "http"} or address.username or address.password or address.port
            or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}", host)
            or host in {"edu.cn", "org.cn", "com.cn", "gov.cn", "net.cn", "ac.uk", "edu.au", "ac.cn"}):
        raise ValueError("请填写学校官网域名，例如 whu.edu.cn")
    return host


def academic_domain(value):
    """Only infer a campus root from a university-specific domain suffix."""
    try:
        host = school_domain(value)
    except ValueError:
        return ""
    match = re.search(r"(?:^|\.)([^.]+\.(?:edu\.cn|ac\.uk|edu\.au|edu))$", host)
    return match[1] if match else ""


def school_for(policy, saved):
    if saved:
        return saved["domain"]
    if policy.get("school_domain"):
        try:
            return school_domain(policy["school_domain"])
        except ValueError:
            pass
    for name, (domain, _) in SCHOOLS.items():
        if name in policy.get("name", ""):
            return domain
    roots = set()
    for doc_id in policy.get("document_ids", []):
        doc = store.get("document", doc_id, default={})
        root = academic_domain(doc.get("source_url"))
        if root:
            roots.add(root)
    return roots.pop() if len(roots) == 1 else ""


def scope(policy_id=None):
    policy = store.get("policy", policy_id) if policy_id else {}
    key = policy_id or "_workspace"
    saved = store.get("benefit_school", key, default=None)
    domain = school_for(policy, saved)
    # A competition organizer may also be a university. Suggest this domain
    # for confirmation when neither the rules nor their source identify it.
    suggestions = {academic_domain(d) for d in policy.get("official_domains", [])} - {""}
    return domain, suggestions.pop() if len(suggestions) == 1 else ""


def category(title):
    if EXCLUDED.search(title) or TOPIC_INDEX.fullmatch(title.strip()):
        return ""
    direct = next((name for name, _, terms in TOPICS if re.search(terms, title)), "")
    return direct or next((name for name, headline, _ in CONDITIONAL_TOPICS if re.search(headline, title)), "")


def publication_date(soup):
    values = [tag.get("content", "") for tag in soup.select("meta[content]")
              if str(tag.get("name") or tag.get("property") or tag.get("itemprop")).lower()
              in {"pubdate", "articlepublishtime", "article:published_time", "datepublished", "publishdate"}]
    values += [tag.get("datetime", "") for tag in soup.select("time[pubdate], time[itemprop=datePublished]")]
    label = re.compile(r"^(?:发布日期|发布时间|发表时间|发布于)\s*[：:]?\s*")
    for node in soup.find_all(string=label):
        line = node.parent.get_text(" ", strip=True)
        if label.fullmatch(line) and node.parent.parent:
            line = node.parent.parent.get_text(" ", strip=True)
        if len(line) <= 100 and label.match(line):
            values.append(label.sub("", line, count=1))
    for value in values:
        if match := DATE_TOKEN.match(value.strip()):
            try:
                return date(*map(int, match.groups())).isoformat()
            except ValueError:
                continue
    return ""


def first_excerpt(lines, patterns):
    return next((line for pattern in patterns for line in lines
                 if 8 <= len(line) <= 450 and re.search(pattern, line)), "")


def application_deadline(lines):
    excerpts = []
    for i, line in enumerate(lines):
        if re.fullmatch(rf"(?:[一二三四五六七八九十]+[、.．]\s*)?{APPLICATION}(?:截止(?:时间|日期)?|时间|期限)[：:]?", line):
            if i + 1 < len(lines) and re.search(r"\d|另行|随时|长期", lines[i + 1]):
                line += " " + lines[i + 1]
        group_cutoff = re.search(r"(?:本科生?|研究生|硕士|博士|[甲乙丙AB]组).{0,12}(?:截止|截至)", line)
        if (WINDOW.search(line) or group_cutoff) and not UNIT_SUBMISSION.search(line) and not re.search(r"公示|审核时间", line):
            excerpts.append(line)
    dates = set()
    for line in excerpts:
        # Associate the date with an actual cutoff, never with a posting date
        # or the first date of an application period. Keep ambiguity in prose.
        matches = list(DATE_TOKEN.finditer(line))
        cutoffs = [m for m in matches if (
            re.search(r"(?:截止(?:日期|时间)?|截至|[至到—–~～])\s*[为是至到：:\s]*$", line[:m.start()])
            or re.match(r"\s*(?:(?:\d{1,2}[:：时]\d{0,2}分?)\s*)?(?:前|截止)", line[m.end():]))]
        if len(cutoffs) != 1 or re.search(r"另行通知|另行公布|待定|(?:截止|截至)[为至到：:\s]*\d{1,2}月", line):
            return "", excerpts
        try:
            dates.add(date(*map(int, cutoffs[0].groups())).isoformat())
        except ValueError:
            return "", excerpts
    return (dates.pop() if len(dates) == 1 else ""), excerpts


def application_conditions(lines):
    collecting = False
    conditions = []
    for line in lines:
        if re.fullmatch(r"(?:[一二三四五六七八九十]+[、.．]\s*)?(?:申请|申报|评选|资助)条件[：:]?", line):
            collecting = True
        elif collecting:
            if (re.match(r"^[一二三四五六七八九十]+[、.．]", line)
                    or re.fullmatch(r"(?:申请流程|申请材料|申请程序|办理方式|资助标准|联系方式)[：:]?", line)):
                break
            if 6 <= len(line) <= 450:
                conditions.append(line)
    return conditions[:10]


def read_benefit(soup, url):
    meta = soup.find("meta", attrs={"name": re.compile("^articletitle$", re.I), "content": True})
    candidates = ([meta["content"].strip()] if meta else []) + [
        tag.get_text(" ", strip=True) for tag in (soup.select_one("h1"), soup.title) if tag]
    if not any(category(t) for t in candidates):
        heading = soup.select_one("article h2, main h2, h2.article-title, h2.news-title")
        if heading:
            candidates.append(heading.get_text(" ", strip=True))
    if any(EXCLUDED.search(title) for title in candidates):
        return None
    title = next((t for t in candidates if category(t)), "")
    if not title:
        return None
    published_on = publication_date(soup)
    content = next((node for selector in LANDING_CONTENT if (node := soup.select_one(selector))), None)
    content = content or soup.body
    if not content:
        return None
    for node in content.select("script,style,nav,header,footer,aside,noscript,menu,.menu,.breadcrumb"):
        node.decompose()
    for node in content.select("p,li,div,section,h2,h3,tr,br"):
        node.insert_before("\n")
        node.insert_after("\n")
    for cell in content.select("td,th"):
        cell.insert_after(" ")
    body = re.sub(r"20\s*(\d)\s*(\d)(?=\s*年)", r"20\1\2", content.get_text())
    lines = list(dict.fromkeys(s.strip() for s in re.split(r"\n|(?<=[。！？；])", body) if s.strip()))
    kind = category(title)
    conditional = next((evidence for name, headline, evidence in CONDITIONAL_TOPICS
                        if name == kind and re.search(headline, title)), "")
    if conditional:
        eligible_lines = [line for line in lines if not re.search(
            r"(?:不|未|无)(?:再|会|能|可|得|予|另行|额外|可以)?(?:提供|申请|减免|资助|发放|享受|免收)", line)]
        offer = first_excerpt(eligible_lines, (conditional,))
    else:
        offer = first_excerpt(lines, VALUE)
    if conditional and not offer:
        return None
    audience = first_excerpt(lines, AUDIENCE)
    method = first_excerpt(lines, METHOD)
    if not (offer or method) or not (audience or method or conditional):
        return None
    deadline, deadline_lines = application_deadline(lines)
    terms = []
    for i, line in enumerate(lines):
        if TERMS.search(line) and len(line) <= 450:
            if line.rstrip("：:") == "试用有效期" and i + 1 < len(lines) and re.search(r"\d{4}年", lines[i + 1]):
                line += " " + lines[i + 1]
            terms.append(line)
    school_dates = [line for line in lines if UNIT_SUBMISSION.search(line)
                    and re.search(r"\d月|\d日|\d{4}[-./]\d", line)]
    # Identical notices may appear in two columns of the same site. Preserve
    # distinct years, department wording and attachment destinations.
    links = [urljoin(url, a["href"]) for a in content.select("a[href]") if a["href"] and a["href"][0] != "#"]
    evidence = "\n".join((urlsplit(url).hostname, title, re.sub(r"\s+", "", "".join(lines)), *links))
    return dict(id=hashlib.sha256(url.encode()).hexdigest()[:24], url=url, title=title, published_on=published_on,
                category=kind, offer=offer, audience=audience, method=method,
                terms=terms[:2], conditions=application_conditions(lines), school_dates=school_dates[:2],
                deadline=deadline, deadline_text=deadline_lines[:3],
                fingerprint=hashlib.sha256(evidence.encode()).hexdigest())


def candidate_batch(urls, next_url, limit=48):
    if len(urls) <= limit:
        return urls, ""
    # Recheck the leading department notices and advance through the rest on later visits.
    split = limit // 2
    remaining = urls[split:]
    offset = remaining.index(next_url) if next_url in remaining else 0
    rotated = remaining[offset:] + remaining[:offset]
    return urls[:split] + rotated[:limit - split], rotated[limit - split]


async def discover_benefits(domain, log):
    cfg = settings()
    domain = school_domain(domain)
    checked_at = store.now()
    previous = store.get("benefit_feed", domain, default={})
    entries = {e["url"]: e for e in previous.get("entries", []) if category(e["title"])}
    failures = []
    slots = asyncio.Semaphore(5)

    async def page(url):
        async with slots:
            try:
                async with asyncio.timeout(30):
                    raw, final, ctype, _ = await fetch(url, limit=3 * 1024 * 1024, domains=[domain])
                if "html" not in ctype.lower():
                    raise ValueError("此来源不是 HTML 网页")
                soup = BeautifulSoup(raw, "html.parser")
                if soup.title and re.search(r"统一身份认证|用户登录|身份认证平台", soup.title.get_text(strip=True)):
                    raise ValueError("官网要求登录")
                if not soup.body or re.search(r"访问验证|checking your browser|verify you are human|CF_APP_WAF",
                                               soup.get_text(" ", strip=True)[:600], re.I):
                    raise ValueError("未取得公开网页正文")
                return soup, urldefrag(final).url
            except Exception as error:
                failures.append(dict(source=url, reason=str(error)[:180] or "读取超时"))
                return None

    async def query(words):
        text = f"site:{domain} {words}"
        try:
            async with asyncio.timeout(18):
                hits = await search(text, cfg)
            return [(urldefrag(h["url"]).url, h["title"]) for h in hits
                    if category(h.get("title", "")) and in_school(h.get("url", ""))]
        except Exception as error:
            failures.append(dict(source=text, reason=str(error)[:180] or "检索超时"))
            return []

    def in_school(url):
        try:
            return urlsplit(url).scheme in {"http", "https"} and allowed(url, [domain])
        except ValueError:
            return False

    async def directory(url):
        found, channels = [], []
        loaded = await page(url)
        if loaded:
            soup, final = loaded
            for link in soup.select("a[href]"):
                try:
                    href = urldefrag(urljoin(final, link["href"])).url
                except ValueError:
                    continue
                if not in_school(href) or href == final:
                    continue
                labels = [link.get("title", "").strip(), link.get_text(" ", strip=True)]
                if any(EXCLUDED.search(t) for t in labels):
                    continue
                label = next((t for t in labels if category(t)), "")
                if label:
                    found.append((href, label))
                if any(len(t) <= 14 and (CHANNEL.search(t) or TOPIC_INDEX.fullmatch(t)) for t in labels):
                    channels.append(href)
        return list(dict.fromkeys(found)), list(dict.fromkeys(channels))

    roots = [u for root, urls in SCHOOLS.values() if root == domain for u in urls]
    roots += [f"https://{domain}/", f"https://www.{domain}/"]
    log(f"正在查找 {domain} 的奖助、勤工岗位和校园服务")
    searches, directories = await asyncio.gather(
        asyncio.gather(*(query(words) for _, words, _ in TOPICS)),
        asyncio.gather(*(directory(url) for url in roots)),
    )
    # Give each department a turn before following its next navigation link.
    channel_rounds = zip_longest(*(links for _, links in directories))
    channels = list(dict.fromkeys(u for row in channel_rounds for u in row if u and u not in roots))[:12]
    directories += await asyncio.gather(*(directory(u) for u in channels))
    # Interleave sources so a single large directory cannot crowd out other categories.
    known = [(e["url"], e["title"]) for e in sorted(entries.values(), key=lambda e: e["checked_at"])
             if in_school(e["url"])]
    groups = [links for links, _ in directories] + list(searches) + [known]
    candidates = {}
    for row in zip_longest(*groups):
        for hit in row:
            if hit:
                url, label = hit
                candidates.setdefault(url, label)
    urls, next_url = candidate_batch(list(candidates), previous.get("next_candidate_url"))
    log(f"正在核对 {len(urls)} 个本校来源的正文")
    previous_ids = {e["fingerprint"]: e["id"] for e in entries.values() if e.get("fingerprint")}
    read = 0
    pending = []
    for url, loaded in zip(urls, await asyncio.gather(*(page(u) for u in urls))):
        if not loaded:
            pending.append(dict(title=candidates[url], url=url, reason="公开正文未读到"))
            continue
        soup, final = loaded
        read += 1
        try:
            item = read_benefit(soup, final)
        except ValueError as error:
            failures.append(dict(source=final, reason=str(error)[:180]))
            pending.append(dict(title=candidates[url], url=final, reason="正文格式需核对"))
            continue
        previous_entry = entries.get(final) or entries.get(url)
        entries.pop(url, None)
        entries.pop(final, None)
        if item:
            if previous_entry:
                item["id"] = previous_entry["id"]
            else:
                item["id"] = previous_ids.get(item["fingerprint"], item["id"])
            entries[final] = dict(**item, checked_at=checked_at)
        elif (soup.title and category(soup.title.get_text(" ", strip=True)) and
              not any(re.search(headline, candidates[url]) for _, headline, _ in CONDITIONAL_TOPICS)):
            pending.append(dict(title=soup.title.get_text(" ", strip=True), url=final,
                                reason="请到官网核对办理正文及附件"))
    unique = {}
    for item in sorted(entries.values(), key=lambda x: x["checked_at"], reverse=True):
        unique.setdefault(item.get("fingerprint", item["url"]), item)
    items = list(unique.values())[:80]
    fresh = sum(item["checked_at"] == checked_at for item in items)
    known_ids = {e["id"] for e in previous.get("entries", [])}
    added = sum(item["id"] not in known_ids for item in items)
    store.put("benefit_feed", dict(id=domain, checked_at=checked_at, entries=items, failures=failures, pending=pending,
                                  pages_read=read, fresh=fresh, added=added, next_candidate_url=next_url,
                                  deferred=len(candidates) - len(urls)))
    log(f"已核对 {read} 个候选页面，核实 {fresh} 项福利，其中新增 {added} 项")
    return dict(domain=domain, fresh=fresh, added=added)


def prepare_benefit(item_id, profile):
    domain, _ = scope(profile["policy_id"])
    feed = store.get("benefit_feed", domain)
    item = next((i for i in feed["entries"] if i["id"] == item_id), None)
    if not item:
        raise ValueError("当前学校没有这项福利，请刷新页面")
    plan_id = hashlib.sha256(f"benefit:{profile['id']}:{item_id}".encode()).hexdigest()[:32]
    due = item["deadline"]
    if item["checked_at"] != feed["checked_at"] or due < date.today().isoformat():
        due = ""
    excerpts = (item.get("offer"), item["audience"], item["method"], *item.get("terms", []), *item["deadline_text"])
    notes = list(dict.fromkeys(s for s in excerpts if s))
    if item.get("school_dates"):
        notes.append("院系报送安排\n" + "\n".join(item["school_dates"]))
    return store.put("plan", dict(id=plan_id, title=item["title"], url=item["url"],
                               policy_id=profile["policy_id"], profile_id=profile["id"], benefit_id=item_id,
                               date=due, notes="\n".join(notes), checklist=[], completed=False), if_absent=True)
