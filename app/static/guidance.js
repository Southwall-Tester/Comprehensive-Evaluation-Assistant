'use strict';

// User-facing views share app.js state and actions; they never write to the API.
function guidanceSources(values = []) {
  return citations((values || []).filter(x => x && x.document_id).map(x => ({
    ...x,
    unit: Number.isInteger(Number(x.unit)) && Number(x.unit) > 0 ? Number(x.unit) : 1,
  })));
}

function guidanceIsSample(profile) {
  return Boolean(profile && (profile.is_sample || /样例|示例|虚构|\bdemo\b|\bsample\b/i.test(profile.name || '')));
}

function guidanceRecordState(policy, profile) {
  if (!profile) return {hasData: false, missing: [], pending: [], planned: []};
  const inputs = profile.inputs || {}, tables = profile.tables || {}, items = profile.items || [];
  const blank = value => value === undefined || value === null || value === '';
  const fieldValue = (record, field) => Object.prototype.hasOwnProperty.call(record, field.id) ? record[field.id] : field.default;
  const missing = (policy.inputs || []).filter(f => f.required !== false && blank(fieldValue(inputs, f))).map(f => f.label || f.id);
  for (const table of policy.tables || []) {
    const rows = (tables[table.id] || []).filter(r => !r._excluded);
    const incomplete = rows.filter(row => (table.fields || []).some(f => f.required !== false && blank(fieldValue(row, f))));
    if (incomplete.length) missing.push(`${table.label || table.id}有 ${incomplete.length} 行待补全`);
  }
  if (policy.date_window_required && items.some(it => ['confirmed', 'planned'].includes(it.state))) {
    if (!profile.period_start) missing.push('材料起始日期');
    if (!profile.period_end) missing.push('材料截止日期');
  }
  const hasData = Object.values(tables).some(rows => rows.some(row => !row._excluded)) || items.length > 0 || (policy.inputs || []).some(f => !blank(inputs[f.id]) && inputs[f.id] !== f.default);
  return {hasData, missing, pending: items.filter(it => !['confirmed', 'planned'].includes(it.state)), planned: items.filter(it => it.state === 'planned')};
}

function guidancePolicyStatus(policy) {
  return policy.state === 'active'
    ? '<span class="tag">规则已启用</span>'
    : '<span class="tag warn">规则草稿 · 尚未核验</span>';
}

function guidanceHomeView() {
  const p = P(), u = U();
  if (!p) return heading('先把细则交给助手', '上传学校的综测细则，之后直接查规则、整理材料和估算分数。') + `
    <section class="card guidance-welcome">
      <span class="guidance-kicker">从一份细则开始</span>
      <h2>少翻文件，少算一次分。</h2>
      <p>选择同一学校、同一学年的细则和补充通知，助手会整理成可查询的规则草稿。</p>
      <div class="actions">${btn('上传细则并整理', 'upload-rules', '', 'primary')}${(S.documents || []).length ? btn('从已有资料选择细则', 'nav', 'data-page="files"') : ''}</div>
      <small>成绩单和获奖证明可以在建立个人记录后直接添加。</small>
    </section>
    <div class="guidance-benefits"><div><b>想知道什么，直接问</b><p>回答附原文位置，方便确认条件。</p></div><div><b>材料里有的，帮你填</b><p>上传成绩单与证明，核对后加入记录。</p></div><div><b>准备做什么，先算收益</b><p>结合封顶、重复计分，查看计划能增加多少分。</p></div></div>`;

  const state = guidanceRecordState(p, u), sample = guidanceIsSample(u);
  const result = calcResult && (!calcResult.policy_id || calcResult.policy_id === p.id) && (!calcResult.profile_id || calcResult.profile_id === u?.id) && (!calcResult.policy_version || calcResult.policy_version === p.version) ? calcResult : null;
  const usable = Boolean(u && state.hasData && result && p.state === 'active' && !state.missing.length);
  const gains = (result?.planned_gains || []).filter(x => !x.error && Number.isFinite(Number(x.gain))).sort((a, b) => Number(b.gain) - Number(a.gain));
  const plans = (S.plans || []).filter(x => !x.policy_id || x.policy_id === p.id).filter(x => !x.date || x.date >= guidanceToday()).sort((a, b) => (a.date || '9999').localeCompare(b.date || '9999')).slice(0, 3);
  let nextTitle = '添加成绩单或证明，看看你现在有多少分';
  let nextDetail = '上传材料后核对提取结果，也可以直接填写。';
  if (u && state.hasData) {
    nextTitle = state.missing.length ? '先补齐这些信息，就能继续估算' : state.pending.length ? `有 ${state.pending.length} 项成果等你确认` : '继续整理记录，或看看下一步做什么';
    nextDetail = state.missing.length ? state.missing.slice(0, 3).join('、') : state.pending.length ? '待确认成果尚未计入分数，核对材料和计分条件后再确认。' : '分数由当前记录估算；新增材料后会重新计算。';
  }
  return heading('我的综测', esc(p.name), btn('资料与方案', 'nav', 'data-page="files"', 'subtle')) + `
    ${sample ? `<div class="notice guidance-sample"><b>当前是虚构样例，不是你的个人记录。</b><p>以下数据仅供体验。创建自己的记录后再添加真实材料。</p>${btn('建立我的记录', 'new-profile', '', 'primary')}</div>` : ''}
    <section class="card guidance-next">
      <div><div class="row">${guidancePolicyStatus(p)}${u ? `<small>${esc(u.name)}</small>` : ''}</div><h2>${esc(nextTitle)}</h2><p class="muted">${esc(nextDetail)}</p>${p.state !== 'active' ? '<p class="guidance-caveat">规则仍是自动整理的草稿；核验并启用后才能计算。</p>' : ''}</div>
      <div class="actions">${btn(u && state.hasData ? '继续我的记录' : '开始我的测评', 'start-score', '', 'primary')}${u ? btn('添加成绩单或证明', 'extract-records') : ''}</div>
    </section>
    <div class="guidance-status-grid">
      <section class="card"><span class="eyebrow">${sample ? '样例' : '当前记录'}${result?.include_planned ? '（含计划）' : ''}估算</span><div class="guidance-value">${usable ? esc(result.total) : '待补充'}</div><p class="muted">${!state.hasData ? '添加个人数据后再显示分数。' : state.missing.length ? '基础信息未齐，暂不展示总分。' : result ? result.include_planned ? '包含尚未取得的计划成果。' : '按已录入数据计算，待确认成果不计分。' : '记录准备好后自动估算；缺少的信息会在记录页提示。'}</p>${usable ? btn('查看怎么算的', 'ledger', '', 'subtle') : btn('查看我的记录', 'start-score', '', 'subtle')}</section>
      <section class="card"><span class="eyebrow">接下来需要补什么</span><div class="guidance-value">${state.missing.length ? `${state.missing.length}<small>处信息</small>` : state.pending.length ? `${state.pending.length}<small>项成果待确认</small>` : state.hasData ? '继续完善' : '添加材料'}</div><p class="muted">${state.missing.length ? esc(state.missing.slice(0, 2).join('、')) : state.pending.length ? esc(state.pending.slice(0, 2).map(it => it.name).join('、')) : state.hasData ? '补录遗漏成果，检查材料与计分条件。' : '成绩单、证书、实践证明都可直接上传。'}</p>${btn(state.pending.length ? '核对记录' : '补充记录', 'start-score', '', 'subtle')}</section>
      <section class="card"><span class="eyebrow">计划项目的净增益</span><div class="guidance-value">${gains.length && state.hasData && !state.missing.length ? `${Number(gains[0].gain) >= 0 ? '+' : ''}${esc(gains[0].gain)}` : '待测算'}</div><p class="muted">${gains.length && state.hasData && !state.missing.length ? `${esc(gains[0].name)}，单独加入当前记录的估算增分。` : state.planned.length ? '完成基础数据后，比较计划能增加多少分。' : '先找适合的项目，再比较投入的收益。'}</p>${btn('看看加分机会', 'nav', 'data-page="opportunities"', 'subtle')}</section>
    </div>
    ${result?.notices?.length ? `<section class="card guidance-alerts"><h2>这些条件还需要留意</h2>${list(result.notices.map(n => n.message))}</section>` : ''}
    <div class="guidance-home-bottom"><section class="card"><h2>不用从头读细则</h2><p class="muted">查能否加分、准备哪些证明、同一项目能否重复计分，回答可追溯原文。</p><div class="actions">${btn('问规则助手', 'nav', 'data-page="rules"')}${btn('查看近期公告', 'nav', 'data-page="opportunities"')}</div></section><section class="card"><h2>接下来的安排</h2>${plans.length ? plans.map(x => `<div class="guidance-plan"><span>${esc(x.title)}</span><small>${esc(x.date || '日期待定')}</small></div>`).join('') : '<p class="muted">把感兴趣公告的时间与准备事项加入计划，就能集中查看。</p>'}${btn('查看行动计划', 'nav', 'data-page="plans"', 'subtle')}</section></div>`;
}

function guidanceRulesView() {
  const p = P();
  if (!p) return guidanceHomeView();
  return heading('问细则，找依据', esc(p.name), btn('去整理我的材料', 'start-score')) + `
    ${p.state !== 'active' ? '<div class="notice"><b>这是自动整理的规则草稿，尚未核验。</b> 解读与计分条件需要对照引用原文；核验并启用后才能计算。</div>' : ''}
    <section class="card guidance-question"><h2>你想确认什么？</h2><div class="question-form"><textarea id="question" aria-label="向规则助手提问" placeholder="例如：我的这项比赛能加分吗？需要准备哪些证明？"></textarea>${btn('查细则', 'ask', '', 'primary')}</div><div class="actions guidance-quick">${['帮我找容易漏报的加分项', '成果证明需要满足哪些条件？', '同一比赛拿了多个奖，怎么计分？'].map(q => btn(esc(q), 'quick-ask', `data-question="${esc(q)}"`, 'subtle')).join('')}</div>${answer ? `<div class="answer-block prose">${esc(answer.answer)}</div><div class="citations">${(answer.document_ids || []).map(id => btn(esc(docName(id).slice(0, 28)), 'source', `data-doc="${esc(id)}" data-unit="1"`, 'citation')).join('')}</div>` : ''}</section>
    <section class="card"><h2>这份细则怎么影响你</h2><p class="guidance-rule-summary">${esc(p.summary || '暂未生成概览，可以直接提问并查看原文依据。')}</p></section>
    <div class="guidance-rule-columns"><section class="card"><h2>哪些投入可能有帮助</h2>${(p.strategies || []).length ? p.strategies.map(s => `<div class="rule-row"><h3>${esc(s.title)}</h3><p>${esc(s.detail)}</p>${guidanceSources(s.citations)}</div>`).join('') : '<p class="muted">告诉规则助手你的成绩和已有成果，查找适合自己的方向。</p>'}</section><section class="card"><h2>先留意这些条件</h2>${(p.constraints || []).map(c => `<div class="rule-row"><p>${esc(c.message)}</p>${guidanceSources(c.citations)}</div>`).join('')}<p class="muted">同一项目：${({max: '按规则取最高分，不能直接把所有奖项相加。', sum: '按这份细则规定累计计分。', block: '需要先确定使用哪一项计分。'})[p.duplicate_mode] || '计分方式需要对照原文确认。'}</p>${(p.unresolved || []).length ? `<details><summary>还有 ${p.unresolved.length} 处规则含义待确认</summary>${list(p.unresolved)}</details>` : ''}</section></div>
    <section class="card"><h2>报成果时，要准备什么</h2><p class="muted">找到对应成果，展开查看材料要求和原文。</p>${(p.item_rules || []).map(r => `<details><summary>${esc(r.label)}${r.category ? ` <span class="tag">${esc(r.category)}</span>` : ''}</summary>${(r.requirements || []).length ? list(r.requirements) : '<p class="muted">当前未列出材料清单，请查看引用原文或向助手提问。</p>'}${guidanceSources(r.citations)}</details>`).join('') || '<p class="muted">尚未整理出成果要求。</p>'}</section>
    <details class="card guidance-maintenance"><summary>规则维护与计算依据</summary><div class="guidance-maintenance-body"><p class="muted">需要核验或修正规则时再展开查看；普通查询无需编辑公式。</p><div class="row">${guidancePolicyStatus(p)}<small>第 ${esc(p.version || 1)} 版</small></div>${p.validation_errors?.length ? `<div class="notice error"><b>${p.validation_errors.length} 处结构问题需要修正</b>${list(p.validation_errors)}</div>` : ''}<div class="actions">${btn('编辑规则', 'edit-policy')}${btn('导出方案', 'export-policy')}${btn(p.state === 'active' ? '重新启用方案' : '已核对原文，启用方案', 'activate', '', 'primary')}</div><h3 class="section-gap">总分与分项如何计算</h3>${(p.formulas || []).map(f => `<div class="rule-row"><h3>${esc(f.label)}${f.id === p.total ? ' · 总分' : ''}</h3><div class="formula">${esc(f.expression)}</div>${guidanceSources(f.citations)}</div>`).join('')}<details><summary>成果的计算表达式</summary>${(p.item_rules || []).map(r => `<div class="rule-row"><h3>${esc(r.label)}</h3><div class="formula">${esc(r.expression)}</div>${guidanceSources(r.citations)}</div>`).join('')}</details></div></details>`;
}

function guidanceToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

function guidanceNoticeTiming(notice) {
  const today = guidanceToday();
  const dates = (notice.analysis?.dates || []).filter(d => {
    if (!d.verified || !/^\d{4}-\d{2}-\d{2}$/.test(d.date || '')) return false;
    const parsed = new Date(d.date + 'T00:00:00Z');
    return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === d.date;
  }).sort((a, b) => a.date.localeCompare(b.date));
  const upcoming = dates.filter(d => d.date >= today);
  const deadlines = dates.filter(d => /截止|结束/.test(d.label || '') && /报名|申请|提交|报送|注册/.test(d.label || ''));
  const expired = deadlines.length ? deadlines.every(d => d.date < today) : dates.length > 0 && !upcoming.length;
  return {dates, upcoming, expired, sort: upcoming[0]?.date || '9999'};
}

function guidanceNoticeCard(notice, timing) {
  const dates = timing.upcoming.length ? timing.upcoming : timing.dates;
  const matches = notice.analysis?.scoring_matches || [];
  const search = `${notice.title || ''} ${notice.analysis?.summary || ''} ${matches.map(m => m.explanation || '').join(' ')}`.toLocaleLowerCase();
  return `<article class="card guidance-notice" data-notice-card data-filter-text="${esc(search)}"><div class="row"><span class="tag ${timing.expired ? '' : timing.upcoming.length ? 'accent' : 'warn'}">${timing.expired ? '已过已知时间节点' : timing.upcoming.length ? '有后续时间节点' : '时间待核对'}</span>${!notice.analysis ? '<small>待解读</small>' : ''}</div><h2>${esc(notice.title)}</h2><p class="muted guidance-notice-summary">${esc(notice.analysis?.summary || '公告已收集，打开后可分析报名条件、材料要求与计分对应。')}</p>${dates.slice(0, 2).map(d => `<div class="date-line">${esc(d.label || '公告日期')} · ${esc(d.date)}</div>`).join('') || '<p class="muted">尚无核对到的明确日期，请以公告原文为准。</p>'}${timing.upcoming.length && !timing.expired ? '<small>所列日期不代表现在仍可报名，请查看报名起止时间。</small>' : ''}<div class="card-footer"><small>${matches.length ? '已整理与细则的对应条件' : '是否可计分仍需核对'}</small><div class="actions">${btn('看条件与材料', 'notice', `data-id="${esc(notice.id)}"`, 'primary')}${btn('加入计划', 'plan-notice', `data-id="${esc(notice.id)}"`)}</div></div></article>`;
}

function guidanceOpportunityView() {
  const p = P();
  if (!p) return guidanceHomeView();
  const records = (S.notices || []).filter(n => n.policy_id === p.id).map(n => ({n, timing: guidanceNoticeTiming(n)})).sort((a, b) => a.timing.sort.localeCompare(b.timing.sort) || String(b.n.checked_at || '').localeCompare(String(a.n.checked_at || '')));
  const current = records.filter(x => !x.timing.expired), old = records.filter(x => x.timing.expired);
  const r = (S.research || []).find(x => x.policy_id === p.id);
  return heading('找值得参加的项目', '先看公告条件和时间，再结合自己的记录判断收益。', btn('查找最新公告', 'research-all', '', 'primary')) + `
    ${records.length ? `<section class="card guidance-filter"><label for="guidance-notice-filter">在已收集公告中查找</label><input id="guidance-notice-filter" type="search" placeholder="输入比赛、认证或活动名称"><small id="guidance-filter-count" aria-live="polite">${records.length} 份公告；旧信息在下方折叠区。</small></section>` : ''}
    ${current.length ? `<div class="opportunity-grid guidance-current-notices">${current.map(x => guidanceNoticeCard(x.n, x.timing)).join('')}</div>` : `<section class="card empty"><strong>${old.length ? '暂时没有新的时间节点' : '还没有收集到公告'}</strong><p>查找细则认可的赛事和认证，也可以直接粘贴官方公告链接。</p>${btn('查找最新公告', 'research-all', '', 'primary')}</section>`}
    <p id="guidance-filter-empty" class="notice" hidden>没有匹配的已收集公告，可以在下方搜索新的公告。</p>
    ${old.length ? `<details class="card guidance-old-notices section-gap"><summary>查看已过时间节点的公告（${old.length}）</summary><p class="muted">保留用于查材料与计分要求；新一届安排请查看新的官方通知。</p><div class="opportunity-grid">${old.map(x => guidanceNoticeCard(x.n, x.timing)).join('')}</div></details>` : ''}
    <section class="card section-gap"><h2>没有找到想参加的项目？</h2><label for="search-query" class="guidance-input-label">搜索新的公告</label><div class="search-bar"><input id="search-query" placeholder="例如：2026 程序设计竞赛 报名">${btn('搜索公告', 'research-query')}</div><label for="notice-url" class="guidance-input-label">已有官方公告链接</label><div class="search-bar"><input id="notice-url" type="url" placeholder="粘贴公告链接，读取报名条件和附件">${btn('读取公告', 'import-notice')}</div></section>
    <details class="card guidance-maintenance"><summary>认可项目、更新情况与检索记录</summary><div class="guidance-maintenance-body"><p class="muted">自动更新：${S.settings?.auto_research ? `本地服务运行时每 ${esc(S.settings.refresh_hours)} 小时检查` : '已关闭'}。这里保留来源和失败记录，方便需要时核查。</p><h3>细则列出的项目</h3><div class="scroll">${(p.opportunities || []).map(o => `<div class="rule-row"><div class="rule-heading"><b>${esc(o.name)}</b>${btn('找公告', 'research-one', `data-query="${esc(new Date().getFullYear() + ' ' + o.name + ' 报名 通知')}"`)}</div><p class="muted">${esc(o.eligibility || o.category || '')}</p></div>`).join('') || '<p class="muted">暂无明确项目清单。</p>'}</div>${r ? `<h3 class="section-gap">最近一次检索 · ${dateLabel(r.searched_at)}</h3><div class="coverage"><div><b>${esc(r.coverage?.queries || 0)}</b><small>检索词</small></div><div><b>${esc(r.coverage?.official_hits || 0)}</b><small>官方域名结果</small></div><div><b>${esc(r.coverage?.downloaded || 0)}</b><small>新收集公告</small></div><div><b>${esc(r.coverage?.failed || 0)}</b><small>失败</small></div></div><details><summary>查看原始检索与待处理来源</summary><div class="scroll">${(r.queries || []).map(q => `<div class="rule-row"><b>${esc(q.query)}</b><p class="muted">${q.status === 'failed' ? '失败：' + esc(q.error) : (q.results || []).length + ' 条结果'}</p></div>`).join('')}${(r.leads || []).map(l => `<div class="rule-row"><a href="${safeUrl(l.url)}" target="_blank" rel="noopener">${esc(l.title)}</a> <span class="tag">${l.official_domain ? '官方域名匹配' : '域名待核对'}</span>${l.error ? `<p class="muted">${esc(l.error)}</p>` : ''}${!l.notice_id && l.official_domain ? btn('读取并分析', 'collect-url', `data-url="${esc(l.url)}"`) : ''}</div>`).join('')}</div></details>` : '<p class="muted">还没有检索记录。</p>'}</div></details>`;
}

document.addEventListener('input', event => {
  if (event.target.id !== 'guidance-notice-filter') return;
  const query = event.target.value.trim().toLocaleLowerCase();
  let visible = 0, oldVisible = 0;
  for (const card of document.querySelectorAll('[data-notice-card]')) {
    card.hidden = !card.dataset.filterText.includes(query);
    if (!card.hidden) {
      visible += 1;
      if (card.closest('.guidance-old-notices')) oldVisible += 1;
    }
  }
  const counter = document.getElementById('guidance-filter-count');
  if (counter) counter.textContent = `${visible} 份匹配公告${oldVisible ? `，其中 ${oldVisible} 份已过已知时间节点` : ''}`;
  const oldSection = document.querySelector('.guidance-old-notices');
  if (oldSection) {
    oldSection.hidden = Boolean(query) && !oldVisible;
    if (query && oldVisible) oldSection.open = true;
    if (!query) oldSection.open = false;
  }
  const emptyState = document.getElementById('guidance-filter-empty');
  if (emptyState) emptyState.hidden = visible > 0;
});
