"""Development acceptance fixture, transcribed against the supplied PDF.

This is NOT used by app ingestion/generation or any school detection. It records
the corrections found during independent acceptance of one generated draft.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import store
from app.engine import validate_policy

POLICY_ID = "44274322bad3478c8fa6685c1bb794c0"


def build():
    old = store.get("policy", POLICY_ID)
    doc = store.get("document", old["document_ids"][0])

    def cite(unit, quote):
        return [dict(document_id=doc["id"], unit=unit, quote=quote)]

    def num(id, label, default=0, lo=0, hi=100):
        return dict(id=id, label=label, type="number", min=lo, max=hi, default=default)

    def flag(id, label):
        return dict(id=id, label=label, type="boolean", default=False)

    def select(id, label, options):
        return dict(id=id, label=label, type="select", options=options)

    def rule(id, label, category, fields, expr, unit, quote, requirements=None, **extra):
        return dict(
            id=id,
            label=label,
            category=category,
            fields=fields,
            expression=expr,
            citations=cite(unit, quote),
            requirements=requirements or [],
            **extra,
        )

    def formula(id, label, expr, unit, quote):
        return dict(id=id, label=label, expression=expr, citations=cite(unit, quote))

    levels = ["国际", "全国", "省级", "校级", "院级"]
    awards = ["一等", "二等", "三等", "优秀", "参与且取得成绩"]
    scores = [[12, 10, 8, 5, 1], [10, 8, 6, 4, 1], [7, 5, 4, 3, 1], [5, 4, 3, 2, 0.5], [2, 1.5, 1, 0.5, 0.25]]
    lookup = {
        "competition": {level: dict(zip(awards, row)) for level, row in zip(levels, scores)},
        "class_factor": {"A": 1.2, "B": 1, "C": 0.8, "D": 1, "E": 1},
        "D_level": dict(zip(levels, ["省级", "省级", "校级", "院级", "院级"])),
        "E_level": dict(zip(levels, ["校级", "校级", "校级", "校级", "院级"])),
        "paper": {
            "CCF A会议": 25,
            "CCF B期刊 / SCI二区": 17,
            "CCF B会议 / CCF C期刊 / SCI三区": 13,
            "SCI四区": 10,
            "CCF C会议 / 认可中文目录": 8,
            "计算机EI期刊": 5,
            "985高校学报计算机论文": 3,
            "计算机中文核心": 2,
        },
        "works": {
            "国家权威": 5,
            "省级重要": 3,
            "其他公开发行 / 地方新闻 / 学校公开发行": 2,
            "学校其他媒体": 1,
        },
        "patent": {"发明授权": 15, "发明公示": 8, "实用新型或外观授权": 5, "软件著作权授权": 5},
        "project": {"国家": {"优秀": 10, "良好": 8, "合格": 6}, "省级": {"优秀": 5, "良好": 4, "合格": 3}},
        "social_leader": {
            "国家": {"标兵": 10, "普通": 8},
            "省部": {"标兵": 7, "普通": 5},
            "校市": {"标兵": 5, "普通": 4},
            "院": {"标兵": 2, "普通": 1},
        },
        "social_member": {
            "国家": {"标兵": 4, "普通": 3},
            "省部": {"标兵": 3, "普通": 2},
            "校市": {"标兵": 2, "普通": 1},
            "院": {"标兵": 1, "普通": 0.5},
        },
        "report": {
            level: dict(zip(["前二", "三至五", "其他"], row))
            for level, row in zip(
                ["国家", "省级", "校一", "校二", "校三", "院"],
                [[8, 4, 1], [6, 3, 1], [4, 2, 1], [3.5, 1.75, 0.5], [3, 1.5, 0.5], [2, 1, 0.5]],
            )
        },
        "cert": {"软考高级": 8, "软考中级": 5, "CSP前1%": 8, "CSP前3%": 6.5, "CSP前5%": 5},
        "startup": {"A轮": 10, "天使轮": 8, "注册公司并有项目": 4},
    }
    p = {
        **old,
        "version": old.get("version", 1) + 1,
        "state": "draft",
        "lookups": lookup,
        "inputs": [
            num("deduct_" + str(i), label + "累计扣分", hi=1000)
            for i, label in enumerate(["思想政治", "个人品德", "学习态度", "组织纪律", "身心健康"], 1)
        ]
        + [
            flag("all_required_done", "已完成规定必修及公共基础选修（影响奖学金资格）"),
            flag("honors_course_a_done", "已完成荣誉课程体系A类课程（影响排名顺序）"),
        ],
        "tables": [
            dict(
                id="courses",
                label="课程成绩",
                fields=[
                    num("score", "成绩", default=None),
                    num("credits", "学分", default=None, lo=0.1, hi=100),
                    select("kind", "计分归属", ["必修或培养方案必选", "其他选修或辅修"]),
                    select("status", "课程状态", ["正常", "重修", "重考", "缓考", "免修", "未选修"]),
                    flag("selected", "计入本次测评（选修最多8门）"),
                ],
            )
        ],
        "item_rules": [],
        "formulas": [],
        "total": "final_score",
        "duplicate_mode": "max",
        "date_window_required": True,
    }
    rules = p["item_rules"]
    rules.append(
        rule(
            "paper",
            "科研论文",
            "c1_paper",
            [
                select("level", "论文档次", list(lookup["paper"])),
                num("rank", "按教师递进规则调整后的作者位次", default=1, lo=1),
                num("ratio", "教师证明的贡献比例", default=1, hi=1),
                flag("best", "CCF会议 best paper"),
                flag("nomination", "CCF会议 best paper 提名"),
                flag("short", "short paper"),
                flag(
                    "eligible", "署名单位、学业相关、检索或录用材料符合要求，且不在灰名单、非poster/workshop"
                ),
            ],
            "lookup('paper',level)*(1.5 if best else (1.3 if nomination else 1))*(0.5 if short else 1)*min(ratio,1 if rank==1 else (0.8 if rank==2 else (0.6 if rank==3 else 0))) if eligible else 0",
            6,
            "第四名及之后的作者不计分",
            [
                "第一作者为本院教师时位次前移一位；多位教师也只减一人。",
                "不同论文可累计；同一论文转载使用相同项目标识。",
                "SCI分区、灰名单和署名单位对照原文第6—9页；CCF A期刊/SCI一区认定满分使用“特别认定”项目。",
            ],
        )
    )
    rules.append(
        rule(
            "work_publication",
            "文学、艺术、新闻作品",
            "c1_works",
            [
                select("level", "媒体级别", list(lookup["works"])),
                flag(
                    "eligible",
                    "刊物/作品有效性符合认定要求；非工作稿件、商业征文；社会实践投稿为省级以上官方媒体",
                ),
            ],
            "lookup('works',level) if eligible else 0",
            6,
            "担任学生组织或者学生社团的工作人员所撰写的工作稿件不予加分",
        )
    )
    rules.append(
        rule(
            "art_exhibition",
            "重要艺术展演（认定后填写）",
            "c1_works",
            [
                num("recognized_score", "按作品评分认定的分值", hi=10),
                flag("recognized", "中央/省级/校职能部门活动，已取得有效计分认定"),
            ],
            "recognized_score if recognized else 0",
            6,
            "参与重要艺术展演活动可参照发表文学、艺术、新闻等作品评分加分",
        )
    )
    rules.append(
        rule(
            "patent",
            "专利与软件著作权",
            "c2",
            [
                select("kind", "类型", list(lookup["patent"])),
                num("rank", "按教师递进规则调整后的负责人位次", default=1, lo=1),
                flag("eligible", "学校科研院办理、专业相关、导师身份及授权/公示材料符合原文"),
            ],
            "lookup('patent',kind)*(1 if rank==1 else (0.5 if rank==2 else 0)) if eligible else 0",
            9,
            "第二负责人按50%计，第三作者及以后不计分",
            [
                "仅第一作者是本院教师时位次前移一位，多位教师也只减一人。不同成果累计，同一成果使用相同标识。软著按授权日期。"
            ],
        )
    )
    rules.append(
        rule(
            "innovation_project",
            "大创 / 珞珈基金结题",
            "c2",
            [
                select("level", "项目级别", ["国家", "省级", "校级", "珞珈基金"]),
                select("result", "结题结果", ["优秀", "良好", "合格"]),
                num("rank", "负责人排名", default=1, lo=1),
                num("ratio", "教师证明的贡献比例", default=1, hi=1),
                flag("eligible", "项目结题及学校评定材料齐备"),
            ],
            "(2 if level=='校级' else ((10 if result=='优秀' else (8 if result=='良好' else 0)) if level=='珞珈基金' else lookup('project',level,result)))*min(ratio,1 if rank==1 else (.8 if rank==2 else (.6 if rank==3 else (.4 if rank==4 else (.2 if rank==5 else 0))))) if eligible else 0",
            9,
            "同一大学生创新创业训练计划项目取最高计分，不累加",
            ["实质一致的国家大创和珞珈基金项目使用相同项目标识，取最高一次，不是两项都计零。"],
        )
    )
    mapped = (
        "lookup('D_level',level) if class_id=='D' else (lookup('E_level',level) if class_id=='E' else level)"
    )
    rules.append(
        rule(
            "discipline_competition",
            "普通学科竞赛",
            "c3_academic",
            [
                select("class_id", "表3-2赛事类别", ["A", "B", "C", "D", "E"]),
                select("level", "获奖证书级别", levels),
                select("award", "获奖等次", awards),
                num("member_rank", "队员排名", default=1, lo=1),
                flag("special", "本人获得特等奖"),
                flag("eligible", "赛事/赛道在认可范围或已获专家认定，且代表武汉大学"),
            ],
            f"lookup('competition',({mapped}),('一等' if special else award))*lookup('class_factor',class_id)*(1.2 if special else 1)*(1 if member_rank<=5 else (.5 if member_rank<=10 else 0)) if eligible else 0",
            10,
            "D 类竞赛奖励按照表3-1 标准中降一级别计分",
            [
                "D类：校→院、省→校、国际/全国→省。E类最高校级。",
                "数学/英语竞赛按证书标题认定级别后仍适用类别调整；美国数模、ICPC使用专门条目。",
                "已获C3满分认定请使用“特别认定”项目。",
            ],
        )
    )
    rules.append(
        rule(
            "icpc",
            "ICPC同一参赛周期",
            "c3_academic",
            [
                flag("world", "参加世界总决赛"),
                select("region_award", "最高区域赛奖励", awards),
                num("extra_gold", "最高荣誉之外的额外区域金奖数"),
                num("extra_silver", "额外区域银奖数"),
                num("extra_bronze", "额外区域铜奖数"),
                flag("eligible", "代表武汉大学，成绩与参赛周期已核对"),
            ],
            "((15 if world else lookup('competition','国际',region_award))+extra_gold*3+extra_silver*2+extra_bronze) if eligible else 0",
            10,
            "每多一项金奖加3 分，每多一项银奖加2 分，每多一项铜奖加1 分",
            ["将同周期成绩合并为一条；区域赛适用的竞赛级别若年度通知另有认定，须修正规则。额外奖不乘120%。"],
        )
    )
    rules.append(
        rule(
            "mcm",
            "美国大学生数学建模竞赛",
            "c3_academic",
            [
                select(
                    "award",
                    "美赛奖项",
                    ["Outstanding Winner", "Finalist", "Meritorious Winner", "Honorable Mention及以下"],
                ),
                num("member_rank", "队员排名", default=1, lo=1),
                flag("eligible", "代表武汉大学，奖项材料齐备"),
            ],
            "(5 if award=='Outstanding Winner' else (5 if award=='Finalist' else (4 if award=='Meritorious Winner' else 0)))*(1 if member_rank<=5 else (.5 if member_rank<=10 else 0)) if eligible else 0",
            11,
            "Honorable Mention 及以下奖项不计分",
            [
                "先按专项条款映射为国家二/省一/省二，再适用D类降级，得5/5/4。专项条款与D类通则的叠加口径请向学院确认。"
            ],
        )
    )
    rules.append(
        rule(
            "sports_competition",
            "文体竞赛",
            "c3_sports",
            [
                select("level", "赛事级别", levels),
                select("award", "奖项", awards),
                num("team_size", "提交名单人数", default=1, lo=1),
                num("rank", "队员排名", default=1, lo=1),
                flag("roster", "团队超过5人时已提供主力名单"),
                flag("boost", "金秋艺术节 / 校运会 / 振兴杯 / 腾飞杯 / 火炬杯"),
                flag("special", "本人获得特等奖"),
                flag("eligible", "主办方与盖章材料符合规定，且代表武汉大学"),
            ],
            "lookup('competition',level,('一等' if special else award))*(1.2 if boost else 1)*(1.2 if special else 1)*(1 if rank<=5 and (team_size<=5 or roster) else .5) if eligible and team_size<=20 else 0",
            11,
            "否则全部按队员减半计分",
        )
    )
    rules.append(
        rule(
            "social_activity",
            "社会表彰 / 集体荣誉",
            "c4",
            [
                select("level", "表彰级别", ["国家", "省部", "校市", "院"]),
                select("kind", "表彰类别", ["标兵", "普通"]),
                select("role", "本人身份", ["负责人或先进个人", "成员", "工作人员或志愿者"]),
                select("special", "团日活动", ["普通荣誉", "月度十佳", "月度优秀"]),
                flag("eligible", "表彰认定与名单齐备，且不是三好学生/优秀学生称号"),
            ],
            "((lookup('social_leader','校市','标兵' if special=='月度十佳' else '普通') if role=='负责人或先进个人' else lookup('social_member','校市','标兵' if special=='月度十佳' else '普通'))*.7 if special!='普通荣誉' else (lookup('social_leader',level,kind) if role=='负责人或先进个人' else lookup('social_member',level,kind))*(.5 if role=='工作人员或志愿者' else 1)) if eligible else 0",
            14,
            "三好学生、优秀学生荣誉称号不参与本项计分",
            [
                "具体荣誉负责人/成员身份按第14页第7项认定。工作人员50%适用于原文明定的学院团委、学生会集体荣誉。"
            ],
        )
    )
    rules.append(
        rule(
            "social_report",
            "社会调查 / 实践报告获奖",
            "c4",
            [
                select("level", "级别", list(lookup["report"])),
                select("rank", "作者位次", ["前二", "三至五", "其他"]),
            ],
            "lookup('report',level,rank)",
            13,
            "撰写的社会调查报告、社会实践报告获奖参照表4-2 按获奖等级实际加分",
        )
    )
    rules.append(
        rule(
            "commendation",
            "通报表扬 / 单项志愿先进个人",
            "c4_commend",
            [select("level", "级别", ["院级或单项志愿先进个人", "校级"]), num("count", "次数", default=1)],
            "count*(1 if level=='校级' else .5)",
            13,
            "通报表扬计分可累加",
            ["总上限3分在C4汇总时统一应用。"],
        )
    )
    rules.append(
        rule(
            "certification",
            "软考 / CSP认证",
            "c5",
            [select("level", "成绩档位", list(lookup["cert"]))],
            "lookup('cert',level)",
            15,
            "多次参加同一种类考试，按本次测评年度时间范围内所取得的最高成绩计分",
            group_by="'软考' if level in ['软考高级','软考中级'] else 'CSP'",
        )
    )
    rules.append(
        rule(
            "startup",
            "创业团队",
            "c5",
            [
                select("stage", "本年度达到阶段", list(lookup["startup"])),
                num("team_size", "团队人数", default=1, lo=1),
                flag("principal", "持股且股权排名前4的主要负责人"),
                flag("roster", "团队超过4人时有全部主要负责人名单"),
                flag("progress", "本学年有阶段进展及证明"),
            ],
            "lookup('startup',stage)*(1 if principal and (team_size<=4 or roster) else .5) if progress else 0",
            15,
            "测评年度内所处阶段未发生变化的团队不能获得加分",
            ["与同一项目竞赛成果填写相同项目标识，避免跨类别叠加。不同团队可分别填。"],
        )
    )
    for cat, points, page, quote in [
        ("c1", 30, 6, "经学院认定，本项计满分"),
        ("c2", 30, 9, "本项按满分计算"),
        ("c3", 30, 11, "经学院认定，C3 项可按照满分计"),
        ("c4", 20, 14, "经学院认定，C4 项可按照满分计"),
    ]:
        rules.append(
            rule(
                "special_" + cat,
                cat.upper() + "特别认定满分",
                cat + "_full",
                [flag("recognized", "已取得原文所列满分条件的学院认定")],
                f"{points} if recognized else 0",
                page,
                quote,
                ["须上传或注明认定证明与落款日期；尚未认定可作为计划项目测算。"],
            )
        )
    for i in range(1, 6):
        p["formulas"].append(
            formula(
                "a" + str(i),
                "A" + str(i) + "基本素质得分",
                f"max(0,20-deduct_{i})",
                3,
                "每项累计减分不超过基准分20 分",
            )
        )
    req = "kind=='必修或培养方案必选' and status=='正常' and selected"
    ele = "kind=='其他选修或辅修' and status=='正常' and selected"
    p["formulas"] += [
        formula("f1", "基本素质 F1", "a1+a2+a3+a4+a5", 4, "基本素质五个方面测评分累计所得总分"),
        formula(
            "b1",
            "必修课程 B1",
            f"mean_rows('courses','score','credits',\"{req}\") if count_rows('courses',\"{req}\")>0 else 0",
            5,
            "纳入测评的每门必修课的成绩",
        ),
        formula(
            "b2",
            "选修辅修 B2",
            f"sum_rows('courses','score*credits',\"{ele}\")*.002",
            5,
            "其他选修课程、辅修课程成绩测评得分记作B2",
        ),
        formula("f2", "课程成绩 F2", "b1+b2", 5, "课程学习成绩按测评学年度的成绩进行计算"),
        formula(
            "c1",
            "论文及作品 C1",
            "min(30,awards('c1_paper')+min(10,awards('c1_works'))+awards('c1_full'))",
            6,
            "发表文学、艺术、新闻等作品累计加",
        ),
        formula("c2", "科研成果 C2", "min(30,awards('c2')+awards('c2_full'))", 9, "本项总得分"),
        formula(
            "c3",
            "竞赛 C3",
            "min(30,awards('c3_academic')+min(15,awards('c3_sports'))+awards('c3_full'))",
            10,
            "文体竞赛总得分不超过",
        ),
        formula(
            "c4",
            "社会活动 C4",
            "min(20,awards('c4')+min(3,awards('c4_commend'))+awards('c4_full'))",
            13,
            "通报表扬计分可累加",
        ),
        formula("c5", "资格及创业 C5", "min(20,awards('c5'))", 14, "资格认证及创业"),
        formula("f3", "实践创新 F3", "min(100,c1+c2+c3+c4+c5)", 15, "F3 累计设定上限为100"),
        formula("final_score", "综测总分", "f1*.1+f2*.75+f3*.15", 1, "各部分所占比例分别为10%、75%、15%"),
    ]
    p["constraints"] = [
        dict(
            expression=f"count_rows('courses',\"{req}\")>0",
            severity="block",
            message="请录入并勾选本年度可计入B1的课程",
        ),
        dict(
            expression=f"count_rows('courses',\"{ele}\")<=8",
            severity="block",
            message="B2最多8门，请按原文自行勾选",
        ),
        dict(
            expression="all_required_done",
            severity="warning",
            message="必修及公共基础选修完成情况待核实，影响奖学金资格",
        ),
        dict(
            expression="honors_course_a_done",
            severity="warning",
            message="荣誉A类课程完成情况待核实，影响排名顺序",
        ),
    ]
    p["unresolved"] = [
        "美国数模专项级别映射是否再适用D类降级，建议向学院确认；当前验证方案按通则叠加处理。",
        "ICPC区域赛在表3-1的级别口径需以学院当年认定为准，当前按国际赛记录；同周期合并一条。",
        "官方媒体文艺征文诗歌比赛按文体标准80%计分，但原文“见C4”与文体C3编号不一致；请取得计分归属确认后在规则中加入，当前未自动计入。",
        "当年补充规定、期刊/贡献比例/赛事类别及证明有效性由学院认定；本工具不代替该认定。",
    ]
    by_id = {f["id"]: f for f in p["formulas"]}
    p["strategies"] = [
        dict(title=title, detail=detail, citations=by_id[source]["citations"])
        for title, detail, source in [
            (
                "先比较实际总分收益",
                "F2权重75%。B1提高1分，综测提高0.75分。其他选修每增加1个“分数×学分”单位，综测增加0.0015分；例如90分、2学分课程贡献0.27总分。必修与培养方案必选不能再计入其他选修。最多8门，按原文口径勾选。",
                "f2",
            ),
            (
                "封顶后换到尚有余量的类别",
                "C1、C2、C3各上限30，C4、C5各上限20，F3合计上限100。每增加1个有效F3分，综测提高0.15分。类别或总上限已满时，继续累积同类成果可能没有增益；用计划项目测算实际变化。",
                "f3",
            ),
            (
                "同类考试升级按差额算",
                "同年度同一种考试只取最高。软考中级5分升到高级8分，通常净增3个F3分，即0.45总分；不是再加8分。CSP属于另一种考试，可按规则合并，但还受C5与F3上限约束。",
                "c5",
            ),
            (
                "不要漏报符合条件的小额表扬",
                "院级通报表扬每次0.5分、校级每次1分，相关表扬累计上限3分，最多贡献0.45总分。取得真实正式材料再确认；已达封顶继续增加同类次数无收益。",
                "c4",
            ),
            (
                "竞赛同时比较类别、级别、位次和投入",
                "相同级别与奖项，A/B/C类别系数为1.2/1/0.8，D类涉及降级，E类有级别限制；队员位次还可能减半或不计分。收益高不等于最易获得，先确认赛事赛道与本人资格，再比较计划项目增益。",
                "c3",
            ),
            (
                "不同成果累计，同一成果避免重复",
                "不同论文、专利等可按细则累计；同一项目的多个获奖或不同类别申报，应填写相同项目标识按规则取最高。论文贡献比例用实际比例与位次上限取较小值，不把两比例重复相乘。",
                "c2",
            ),
        ]
    ]
    p["review_note"] = (
        "开发验收：由助手对照16页原文与表格修订测试方案；不是学院审核，也不是通用解析器的固定模板。"
    )
    p["validation_errors"] = validate_policy(p, {doc["id"]: doc})
    if p["validation_errors"]:
        print(p["validation_errors"])
        raise RuntimeError("fixture citations invalid")
    store.put("policy_history", dict(policy_id=p["id"], policy=old))
    store.put("policy", p)
    Path("artifacts/whu-reviewed-policy.json").write_text(
        json.dumps(p, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print("REVIEWED", p["id"], len(rules), "rules")
    return p


if __name__ == "__main__":
    build()
