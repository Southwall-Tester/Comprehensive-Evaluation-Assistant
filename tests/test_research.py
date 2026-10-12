import pytest
from app.research import html_document
from app.research import date_supported


def test_calendar_never_fabricates_first_day_of_month():
    assert not date_supported("2026-09-01", "本次比赛定于2026年9月启动")
    assert date_supported("2026-11-20", "2026年11月1日至11月20日")
    assert date_supported("2026-11-20", "2026年11月1日至20日")
    assert not date_supported("2027-11-20", "2026年11月20日")


def test_navigation_is_not_an_official_attachment():
    raw = """<html><title>赛事报名通知</title><body><nav><a href="/downloads">下载中心</a></nav><article>本校竞赛报名通知，参赛队伍应在截止时间前提交盖章文件及身份证明。本次报名有关安排如下。<a href="/rules.pdf">附件1 竞赛规则</a></article><footer><a href="/download">常用下载</a></footer></body></html>""".encode()
    doc, attachments = html_document(raw, "https://school.edu.cn/notice")
    assert len(attachments) == 1
    assert attachments[0]["url"] == "https://school.edu.cn/rules.pdf"
    assert "下载中心" not in doc["units"][0]["text"]


def test_waf_is_not_a_notice():
    with pytest.raises(ValueError, match="验证页"):
        html_document(b"<html><body>CF_APP_WAF browser verification</body></html>", "https://example.org/")


def test_semantic_registration_status_requires_source_and_keeps_start_undated(tmp_path, monkeypatch):
    import asyncio
    from app import research, store
    from app.workflow import timing

    monkeypatch.setattr(store, "DATA", tmp_path)
    text = "参赛登记正在受理，请同学们递交资料。截止2026年10月31日。"
    store.put("document", dict(id="notice", name="测试公告", units=[dict(index=1, label="正文", text=text)]))
    citation = dict(document_id="notice", unit=1)

    async def complete(*args, **kwargs):
        return dict(
            dates=[dict(label="报名截止", date="2026-10-31", quote="截止2026年10月31日。", **citation),
                   dict(label="报名开始", date="2026-09-01", quote="参赛登记正在受理，请同学们递交资料。", **citation)],
            registration_statuses=[
                dict(registration_status="open", quote="参赛登记正在受理，请同学们递交资料。", **citation),
                dict(registration_status="closed", quote="这句关闭报名说明不存在于原文", **citation)],
        ), {}
    monkeypatch.setattr(research, "complete", complete)
    result = asyncio.run(research.analyze_notice(dict(id="n", document_ids=["notice"]), {}, lambda _: None))
    states = result["analysis"]["registration_statuses"]
    assert states[0]["verified"] is True and states[1]["verified"] is False
    assert result["analysis"]["dates"][1]["date"] is None
    from datetime import date
    assert timing(result, date(2026, 10, 12))["status"] == "open"
