'use strict';

let benefitData = null;
let benefitRequest = 0;

function benefitsView() {
  return heading('校园福利', '查找本校的奖助补贴、勤工岗位和学生可用的服务。') +
    '<div id="benefit-panel" aria-busy="true"><p class="muted">正在读取当前学校…</p></div>';
}

function benefitSchoolForm(domain, suggested) {
  const form = `<form id="benefit-school-form" class="benefit-school-form">
    <label class="field"><span>学校官网域名</span><input id="benefit-domain" required
      value="${esc(domain || suggested)}" placeholder="例如 whu.edu.cn" autocapitalize="none" spellcheck="false"></label>
    <button class="primary" type="submit">保存并查找</button></form>`;
  if (!domain) return `<section class="card"><h2>选择当前学校</h2>
    <p>填写学校官网后即可查找，校内各部门的子域名也会纳入检索。</p>${form}</section>`;
  return `<section class="card"><div class="rule-heading"><div><h2>当前学校官网</h2><b>${esc(domain)}</b></div>
    ${btn('立即查找','benefit-search','','primary')}</div>
    <p class="muted">${S.settings?.auto_research ? `本地服务运行时，自动检索间隔为 ${esc(S.settings.refresh_hours)} 小时。` : '自动检索已关闭，可以手动查找。'}</p>
    ${domain === 'whu.edu.cn' ? `<p><a href="https://github.com/Southwall-Tester/Comprehensive-Evaluation-Assistant/blob/main/docs/whu-benefits-2026-11-25.md" target="_blank" rel="noopener noreferrer">武汉大学福利清单（2026 年 11 月 25 日） ↗</a></p>
      <p><a href="https://xzzgl.whu.edu.cn/" target="_blank" rel="noopener noreferrer">本科生困难补助申请</a> ·
      <a href="https://xsjy.whu.edu.cn/a/common/student/consultingNew/consultingCalendar" target="_blank" rel="noopener noreferrer">就业指导预约</a> ·
      <a href="https://museum.whu.edu.cn/fwzn.htm" target="_blank" rel="noopener noreferrer">万林艺术博物馆参观</a> ·
      <a href="https://oldwww.lib.whu.edu.cn/webfile/category/ydcd_jh/1084.html" target="_blank" rel="noopener noreferrer">图书馆词典笔借还</a></p>
      <details><summary>学生可领的校外 AI 额度</summary><ul class="list">
      <li><a href="https://opc.aliyun.com/summer-2026" target="_blank" rel="noopener noreferrer">阿里云高校 AI 通行证</a>　完成高校学生认证后，可领取 300 元高校专享券并选择模型额度方案。</li>
      ${guidanceToday() <= '2026-12-31' ? '<li><a href="https://cloud.tencent.com/document/product/1823/130053" target="_blank" rel="noopener noreferrer">腾讯云 TokenHub 新人体验包</a>　符合条件的主账号可在模型广场勾选语言模型，每个模型 100 万 Token，领取后有效 1 年。本期截至 2026 年 12 月 31 日。</li>' : ''}
      </ul><small>2026 年 11 月 25 日核对，领取条件见发放方原文。</small></details>` : ''}
    <details><summary>更换学校官网</summary>${form}</details></section>`;
}

function benefitCard(item, feed) {
  const facts = [
    ['官网发布日期', item.published_on || '日期待核对'],
    ['适用对象', item.audience && item.audience === item.offer ? '' : item.audience || '适用范围请核对官网原文。'],
    ['办理方式', item.method && (item.method === item.offer || item.method === item.audience) ? '' : item.method || '办理步骤请核对官网原文。'],
    ['使用或履约条件', (item.terms || []).filter(s => ![item.offer,item.audience,item.method].includes(s)).join(' ')],
    ['办理时间', (item.deadline_text || []).filter(s => s !== item.method).join(' ')],
    ['院系报送安排', (item.school_dates || []).join(' ')],
  ].filter(([, value]) => value);
  const prior = item.checked_at !== feed.checked_at;
  const dateText = item.deadline ? `个人办理截止日 ${item.deadline}` : '个人截止日待核对';
  const plan = U() && S.plans?.find(p => p.profile_id === profileId && p.benefit_id === item.id);
  return `<article class="card benefit-card" data-benefit-id="${esc(item.id)}">
    <div class="row"><span class="tag">${esc(item.category)}</span><small>${esc(dateText)}</small></div>
    <h2>${esc(item.title)}</h2>
    <a class="wf-official-link" href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">学校官网原文 ↗<small>${esc(item.url)}</small></a>
    ${item.offer ? `<p>${esc(item.offer)}</p>` : ''}
    ${facts.length ? `<dl>${facts.map(([label, value]) => `<dt>${label}</dt><dd>${esc(value)}</dd>`).join('')}</dl>` : ''}
    ${item.conditions?.length ? `<details><summary>查看申请条件原文</summary>${list(item.conditions)}</details>` : ''}
    ${prior ? `<p class="muted">本次未复核，上次读到原文的日期为 ${esc(new Date(item.checked_at).toLocaleDateString('zh-CN'))}。</p>` : ''}
    ${U() ? btn(plan ? '查看我的待办' : '加入我的待办','benefit-plan',`data-id="${esc(item.id)}"`) : ''}
    </article>`;
}

function showBenefitCards() {
  const target = $('#benefit-cards');
  if (!target || !benefitData?.feed) return;
  const feed = benefitData.feed, category = $('#benefit-category')?.value || '';
  const today = guidanceToday();
  const days = Number($('#benefit-published')?.value || 0);
  const firstDay = new Date(today + 'T00:00:00Z');
  firstDay.setUTCDate(firstDay.getUTCDate() - days + 1);
  const since = firstDay.toISOString().slice(0,10);
  const items = feed.entries.filter(i => (!category || i.category === category) &&
    (!days || (i.published_on >= since && i.published_on <= today))).sort((a,b) =>
    (b.published_on || '').localeCompare(a.published_on || '') ||
    Number(b.checked_at === feed.checked_at) - Number(a.checked_at === feed.checked_at) ||
    (a.deadline || '9999').localeCompare(b.deadline || '9999') || a.title.localeCompare(b.title,'zh-CN'));
  const old = items.filter(i => i.deadline && i.deadline < today);
  const cards = rows => `<div class="opportunity-grid benefit-grid">${rows.map(i => benefitCard(i,feed)).join('')}</div>`;
  if (!items.length) {
    target.innerHTML = feed.entries.length ? '<p class="notice">当前筛选条件下没有公告。</p>' : '';
    return;
  }
  target.innerHTML = cards(items.filter(i => !i.deadline || i.deadline >= today)) +
    (old.length ? `<details class="card section-gap"><summary>已过原文截止日（${old.length}）</summary>${cards(old)}</details>` : '');
}

function showBenefitFeed(feed, category, period, running) {
  if (!feed) return `<p class="notice" role="status">${running ? '正在检索并核对学校官网，完成后会在这里显示。' : '尚未查找过这所学校的福利。'}</p>`;
  const categories = [...new Set(feed.entries.map(i => i.category))];
  return `<section class="card section-gap"><div class="rule-heading"><div><h2>检索结果</h2>
    <p class="muted">最近检索 ${esc(new Date(feed.checked_at).toLocaleString('zh-CN'))}，读取 ${esc(feed.pages_read)} 个候选页面，核实 ${esc(feed.fresh)} 项${Number.isInteger(feed.added) ? '，其中新增 ' + esc(feed.added) + ' 项' : ''}。${feed.deferred ? '另有 ' + esc(feed.deferred) + ' 个候选页面将在后续检索中轮流核对。' : ''}</p></div></div>
    ${categories.length ? `<div class="field-grid">${wfSelect('benefit-category','福利类别',[['','全部类别'], ...categories.map(c => [c,c])],category)}
      ${wfSelect('benefit-published','官网发布日期',[['','全部日期'],['7','近 7 天'],['30','近 30 天']],period)}</div>` : ''}
    ${feed.directories?.length ? `<details><summary>本次读到的学校栏目（${feed.directories.length}）</summary><ul class="list benefit-issues">${feed.directories.map(d =>
      `<li><a href="${safeUrl(d.url)}" target="_blank" rel="noopener noreferrer">${esc(d.title)}</a>　${esc(d.url)}</li>`).join('')}</ul></details>` : ''}
    ${feed.pending?.length ? `<details><summary>待核对公告（${feed.pending.length}）</summary><ul class="list benefit-issues">${feed.pending.map(p =>
      `<li><a href="${safeUrl(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.title)}</a>　${esc(p.reason)}</li>`).join('')}</ul></details>` : ''}
    ${feed.failures.length ? `<details><summary>${feed.failures.length} 处来源或检索未完成</summary><ul class="list benefit-issues">${feed.failures.map(f =>
      `<li>${safeUrl(f.source) === '#' ? esc(f.source) : `<a href="${safeUrl(f.source)}" target="_blank" rel="noopener noreferrer">${esc(f.source)}</a>`}　${esc(f.reason)}</li>`).join('')}</ul></details>` : ''}
    ${!feed.entries.length ? '<p>本次未读到有办理依据的福利正文。</p>' : ''}</section><div id="benefit-cards"></div>`;
}

async function refreshBenefits() {
  const panel = $('#benefit-panel');
  if (!panel) return;
  const request = ++benefitRequest;
  try {
    const data = await api('/api/benefits?policy_id=' + encodeURIComponent(policyId || ''));
    if (!panel.isConnected || request !== benefitRequest) return;
    const key = JSON.stringify([data.domain, data.suggested]);
    if (panel.dataset.school !== key) {
      panel.innerHTML = benefitSchoolForm(data.domain,data.suggested) + '<div id="benefit-feed"></div>';
      panel.dataset.school = key;
      delete panel.dataset.revision;
    }
    benefitData = data;
    const search = panel.querySelector('[data-act="benefit-search"]');
    if (search) {
      search.disabled = !!data.running;
      search.textContent = data.running ? '正在查找…' : '立即查找';
    }
    const revision = JSON.stringify([data.feed?.updated_at, data.feed ? null : data.running]);
    if (data.domain && panel.dataset.revision !== revision) {
      $('#benefit-feed').innerHTML = showBenefitFeed(data.feed, $('#benefit-category')?.value,
        $('#benefit-published')?.value, data.running);
      panel.dataset.revision = revision;
      showBenefitCards();
    }
  } catch (error) {
    if (panel.isConnected && request === benefitRequest) {
      if (!panel.dataset.school) panel.textContent = error.message;
      else notify(error.message);
    }
  } finally {
    if (panel.isConnected && request === benefitRequest) panel.setAttribute('aria-busy','false');
  }
}

async function benefitAction(action, button) {
  if (action === 'benefit-search') {
    await track(await api('/api/benefits/search','POST',{policy_id:policyId}));
    await refreshBenefits();
  } else if (action === 'benefit-plan') {
    const selected = profileId;
    const plan = await api(`/api/benefits/${encodeURIComponent(button.dataset.id)}/plan`,'POST',{profile_id:selected});
    await load(false);
    if (page === 'benefits' && profileId === selected) {
      showBenefitCards();
      wfPlanDialog(plan);
    }
  }
}

document.addEventListener('submit', async event => {
  if (event.target.id !== 'benefit-school-form') return;
  event.preventDefault();
  const button = event.target.querySelector('button');
  button.disabled = true;
  try {
    await track(await api('/api/benefits/school','PUT',{policy_id:policyId, domain:$('#benefit-domain').value.trim()}));
    await refreshBenefits();
  } catch (error) { notify(error.message); }
  finally { button.disabled = false; }
});
document.addEventListener('change', event => {
  if (['benefit-category', 'benefit-published'].includes(event.target.id)) showBenefitCards();
});
setInterval(() => { if (page === 'benefits' && !document.hidden) refreshBenefits(); }, 10000);
