"""Offline acceptance with synthetic data; no personal workspace or model calls."""
from datetime import date, timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_engine import example, student, event
from scripts.check_usability import wait_ready, nav, put

ART = ROOT / 'artifacts'


def fixtures(folder):
    today = date.today()
    day = lambda offset: (today + timedelta(days=offset)).isoformat()
    policy = example()
    policy.update(id='policy', state='active', version=1, document_ids=['test'])
    policy['item_rules'][0].update(label='测试赛事', requirements=['获奖证明'])
    profile = student([dict(event(), id='old', document_ids=['proof'])])
    profile.update(id='person', name='虚构验收记录', policy_id='policy', inputs={k:80 for k in ['ethics','study','sport','art','work']})
    (folder / 'proof.txt').write_text('虚构证明文件', encoding='utf-8')
    proof = dict(id='proof', name='虚构证明.txt', path=str(folder/'proof.txt'), kind='.txt', units=[dict(index=1,label='第1段',text='虚构证明文件',tables=[])])
    citation = dict(document_id='test', unit=1, quote='五项指标按各自权重计算')
    doc = dict(id='test', name='虚构规则.txt', kind='.txt', units=[dict(index=1,label='第1段',text='五项指标按各自权重计算',tables=[])])
    def notice(id, title, values=None, closed=False):
        facts = {k:dict(value=v,verified=True,citations=[citation]) for k,v in (values or {}).items()}
        return dict(id=id, title=title, policy_id='policy', url='https://example.invalid/'+id,
            state='analyzed', document_ids=['test'], attachments=[], analysis=dict(
                summary='虚构赛事，仅用于功能验收', participation=facts, eligibility=['本科生'],
                dates=[dict(label='校内报名开始',scope='school',date=day(-20),verified=True,**citation),
                       dict(label='校内报名截止',scope='school',date=day(-1 if closed else 5),verified=True,**citation),
                       dict(label='全国决赛',scope='national',date=day(40),verified=True,**citation)],
                actions=['核对报名资格','准备项目报告'],materials=['项目演示视频'],
                scoring_matches=[dict(rule_id='event',recognition='inferred',category='A类',evidence_verified=True,
                    explanation='按虚构通用条款推断，需核对赛道',citations=[citation])]))
    notices = [notice('project','项目甲',dict(format='project',attendance='remote',team='solo')),
        notice('timed','限时乙',dict(format='timed',attendance='onsite',team='team')),
        notice('unknown','条件未知丙'),
        notice('closed','往届项目丁',dict(format='project',attendance='remote',team='solo'),True)]
    with sqlite3.connect(folder/'workspace.sqlite') as c:
        c.execute('CREATE TABLE objects(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))')
        for kind, obj in [('policy',policy),('profile',profile),('document',doc),('document',proof)]+[('notice',n) for n in notices]:
            put(c,kind,obj)
    (folder/'settings.json').write_text(json.dumps(dict(auto_research=False)),encoding='utf-8')


def check_browser(base):
    errors, blocked, checks = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport=dict(width=1440,height=1000))
        def guard(route):
            url=route.request.url
            if not url.startswith(base+'/') or any(x in url for x in ['/api/research','/api/ask','/analyze','/ocr']):
                blocked.append(url);route.abort()
            else:
                route.continue_()
        context.route('**/*',guard)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(base)
        expect(page.locator('nav [data-page="opportunities"]')).to_be_visible()
        nav(page,'opportunities')
        expect(page.locator('#wf-format')).to_be_visible()
        page.locator('#wf-format').select_option('project')
        page.locator('#wf-attendance').select_option('remote')
        expect(page.locator('[data-notice-id="timed"]')).to_be_hidden()
        expect(page.locator('[data-notice-id="unknown"]')).to_be_visible()
        page.locator('#wf-unknown').uncheck()
        expect(page.locator('[data-notice-id="unknown"]')).to_be_hidden()
        page.locator('#guidance-notice-filter').fill('项目甲')
        page.reload()
        expect(page.locator('#wf-format')).to_have_value('project')
        expect(page.locator('#guidance-notice-filter')).to_have_value('项目甲')
        expect(page.locator('[data-notice-id="project"]')).to_contain_text('全程远程')
        expect(page.locator('#wf-calendar')).to_contain_text('校内报名截止')
        page.locator('#wf-hours').fill('4')
        expect(page.locator('[data-notice-id="project"]')).to_be_hidden()
        page.locator('#wf-unknown').check()
        page.locator('[data-wf-effort="project"]').fill('3')
        page.locator('[data-wf-effort="project"]').press('Tab')
        page.locator('#wf-unknown').uncheck()
        expect(page.locator('[data-notice-id="project"]')).to_be_visible()
        checks.append('Saved personal filters preserve unknowns; weekly budget uses personal estimate')
        page.screenshot(path=str(ART/'workflow-desktop.png'),full_page=True)

        page.locator('[data-act="wf-prepare"][data-id="project"]').click()
        expect(page.locator('#wf-plan-title')).to_have_value('项目甲')
        expect(page.locator('[data-wf-check-text]')).to_have_count(4)
        page.locator('[data-act="wf-add-check"]').click()
        page.locator('[data-wf-check-text]').last.fill('联系指导老师（本人安排）')
        page.locator('[data-act="wf-save-plan"]').click()
        expect(page.locator('#dialog')).not_to_be_visible()
        nav(page,'plans')
        page.locator('[data-wf-check]').first.check()
        expect(page.locator('.wf-plan-list')).to_contain_text('1/5 项已完成')
        page.reload()
        expect(page.locator('[data-wf-check]').first).to_be_checked()
        nav(page,'opportunities')
        page.locator('[data-act="wf-prepare"][data-id="project"]').click()
        expect(page.locator('[data-wf-check-text]')).to_have_count(5)
        page.locator('#dialog [data-act="close"]').click()
        data=page.request.get(base+'/api/state').json()
        assert len(data['plans'])==1 and data['plans'][0]['checklist'][0]['done']
        checks.append('Prepare is idempotent; editable checklist progress persists across reloads')

        before=page.request.get(base+'/api/state').json()['profiles']
        page.locator('[data-act="wf-scenario"][data-id="project"]').click()
        page.locator('[data-wf-value="level"]').select_option('省级')
        page.locator('[data-wf-value="ratio"]').fill('1')
        page.locator('#wf-scenario-date').fill('2026-10-12')
        page.locator('[data-act="wf-calculate"]').click()
        expect(page.locator('#wf-scenario-result')).to_contain_text('预计净增 +3 分')
        page.locator('#wf-conflict').select_option('old')
        page.locator('[data-act="wf-calculate"]').click()
        expect(page.locator('#wf-scenario-result')).to_contain_text('预计净增 +0 分')
        page.locator('#dialog [data-act="close"]').click()
        assert page.request.get(base+'/api/state').json()['profiles']==before
        checks.append('Scenario respects cap and existing work conflict without changing earned achievements')

        nav(page,'score')
        with page.expect_download() as download:
            page.locator('[data-act="wf-pack"]').click()
        with zipfile.ZipFile(download.value.path()) as z:
            assert any(n.endswith('虚构证明.txt') for n in z.namelist())
            assert '计分与依据.txt' in z.namelist()
        page.locator('[data-act="edit-item"]').first.click()
        page.locator('#item-name').fill('改名后保留证明')
        page.locator('[data-act="save-item"]').click()
        expect(page.locator('#dialog')).not_to_be_visible()
        assert page.request.get(base+'/api/state').json()['profiles'][0]['items'][0]['document_ids']==['proof']
        checks.append('ZIP contains linked proofs and readable scoring; editing an item preserves proof association')

        nav(page,'rules')
        page.locator('[data-act="wf-review"]').click()
        expect(page.locator('#wf-review-source')).to_contain_text('五项指标按各自权重计算')
        page.locator('[data-wf-number]').first.fill('10')
        page.locator('#wf-review-row').select_option('1')
        page.locator('#wf-review-row').select_option('0')
        expect(page.locator('[data-wf-number]').first).to_have_value('10')
        page.screenshot(path=str(ART/'workflow-rule-review.png'),full_page=True)
        page.locator('[data-act="wf-save-review"]').click()
        expect(page.locator('#dialog')).not_to_be_visible()
        policy=page.request.get(base+'/api/state').json()['policies'][0]
        assert policy['state']=='draft' and policy['version']==2
        assert policy['formulas'][0]['expression']=="min(10,awards('bonus'))"
        checks.append('Source comparison retains edits while switching rules; save creates a versioned draft')

        page.set_viewport_size(dict(width=390,height=844))
        for section in ['opportunities','plans','score','rules']:
            nav(page,section)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),section
        page.locator('[data-act="wf-review"]').click()
        expect(page.locator('#wf-review-source')).to_contain_text('五项指标按各自权重计算')
        assert page.locator('#dialog').evaluate('el=>el.scrollWidth<=el.clientWidth')
        page.screenshot(path=str(ART/'workflow-mobile-review.png'),full_page=True)
        page.locator('#dialog [data-act="close"]').click()
        nav(page,'plans')
        page.locator('[data-act="wf-complete-plan"]').click()
        expect(page.locator('.wf-plan-list')).to_contain_text('恢复任务')
        assert 'BEGIN:VEVENT' not in page.request.get(base+'/api/plans/calendar?policy_id=policy&profile_id=person').text()
        checks.append('Desktop and mobile fit; completed tasks excluded from calendar')
        browser.close()
    assert not errors, errors
    assert not blocked, blocked
    return dict(checks=checks,javascript_errors=errors,external_requests=blocked,status='passed')


def main():
    ART.mkdir(exist_ok=True)
    report = ART/'workflow-check.json'
    report.write_text(json.dumps(dict(status='running')), encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='cea-workflow-') as temporary:
        folder=Path(temporary);fixtures(folder)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env=os.environ.copy();env.update(CEA_DATA=str(folder),PYTHONIOENCODING='utf-8')
        with (folder/'server.log').open('w+b') as log:
            process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--log-level','warning'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                wait_ready(process,base)
                result=check_browser(base)
                report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as error:
                report.write_text(json.dumps(dict(status='failed', error=str(error)),ensure_ascii=False,indent=2),encoding='utf-8')
                raise
            finally:
                process.terminate();process.wait(timeout=10)
    print('WORKFLOW_PASS: filters, calendar, checklist, scenario, ZIP, source review, desktop/mobile')


if __name__=='__main__':
    main()
