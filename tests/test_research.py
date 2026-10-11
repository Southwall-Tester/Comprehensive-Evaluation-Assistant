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
