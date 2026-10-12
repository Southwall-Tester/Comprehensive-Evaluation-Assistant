'use strict';

const wfLabels = {
 format: {project:'自行制作项目',timed:'限时比赛',mixed:'项目与限时赛结合',unknown:'赛制待核对'},
 attendance:{remote:'全程远程',onsite:'需要到场',hybrid:'线上与线下结合',unknown:'到场要求待核对'},
 team:{solo:'个人参赛',team:'团队参赛',either:'个人或团队',unknown:'组队要求待核对'},
 recognition:{named:'细则明确列名（需核对赛道）',inferred:'通用条款推断',pending:'待认定',ineligible:'明确不适用'},
 status:{open:'报名中',closing:'报名中 · 7 天内截止',partial_open:'部分组别仍在报名',closed:'报名已结束',upcoming:'报名尚未开始',not_open:'报名尚未开放',suspended:'报名已暂停',deadline_only:'是否已开放报名待确认',unknown:'报名时间待核对'},
 scope:{school:'校内',national:'全国',unknown:'范围待核对'}
};
let wfScenarioNotice = null, wfScenarioResult = null, wfReview = null;
function workflowProofFields(item) {
 return `<details class="section-gap"><summary>关联证明文件 · ${(item.document_ids||[]).length} 份</summary><p class="muted">从资料库勾选此项成果的证明；导入批次的文件请逐项核对。</p><div class="wf-checklist">${(S.documents||[]).map(d=>`<label><input type="checkbox" data-wf-proof="${esc(d.id)}" ${(item.document_ids||[]).includes(d.id)?'checked':''}><span>${esc(d.name)}</span></label>`).join('')||'<p>先通过“添加成绩单或证明”上传文件。</p>'}</div></details>`;
}
function workflowNoticeDetails(n) {
 const a=n.analysis||{};
 return `<section class="section-gap"><div class="wf-tags">${['format','attendance','team'].map(key=>`<div><span class="tag">${esc(wfLabels[key][wfFact(n,key)]||'待核对')}</span>${citations(a.participation?.[key]?.verified?a.participation[key].citations:[])}</div>`).join('')}</div>${!a.participation?'<p class="muted">旧公告尚未提取结构化赛制，可点击“重新分析附件”补充。</p>':''}${(a.scoring_matches||[]).map(m=>`<p><b>${esc(m.evidence_verified?m.category||'类别待核对':'类别待核对')}</b> · ${esc(wfLabels.recognition[m.evidence_verified?m.recognition:'pending']||'待认定')}</p>`).join('')}</section>`;
}
function wfPreferences() { try {return JSON.parse(localStorage.getItem('cea-preferences:'+policyId+':'+(profileId||''))||'{}')} catch {return {}} }
function wfSavePreferences(value) {localStorage.setItem('cea-preferences:'+policyId+':'+(profileId||''),JSON.stringify(value))}
function wfFact(n,key) {const f=n.analysis?.participation?.[key];return f?.verified?f.value:'unknown'}
function wfSelect(id,label,options,value='') {return `<label class="field"><span>${esc(label)}</span><select id="${id}">${options.map(([v,l])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(l)}</option>`).join('')}</select></label>`}
function workflowFilters() {
 const p=wfPreferences();
 return `<section class="card"><div class="rule-heading"><h2>按我的安排筛选</h2>${btn('清空筛选','wf-reset-filters','','subtle')}</div><div class="field-grid wf-filters">
 ${wfSelect('wf-format','比赛形式',[['','不限'],['project','自行做项目'],['timed','限时比赛']],p.format)}
 ${wfSelect('wf-attendance','到场安排',[['','不限'],['remote','只考虑全程远程'],['hybrid','可接受到场或答辩']],p.attendance)}
 ${wfSelect('wf-team','组队意愿',[['','不限'],['solo','想个人参加'],['team','愿意组队']],p.team)}
 <label class="field"><span>每周可投入（小时）</span><input id="wf-hours" type="number" min="0" step="1" value="${esc(p.hours||'')}" placeholder="不限"></label>
 </div><label class="field"><span>在已收集公告中查找</span><input id="guidance-notice-filter" type="search" value="${esc(p.query||'')}" placeholder="赛事名称、类别或条件"></label>
 <label><input id="wf-unknown" type="checkbox" ${p.unknown!==false?'checked':''}> 保留条件不完整的公告，标为待核对</label><p class="muted">时间投入使用你在卡片上的估计。</p><small id="guidance-filter-count" aria-live="polite"></small></section>`;
}
function workflowOpportunityView() {
 return guidanceOpportunityView();
}
function workflowNoticeCard(n) {
 const t=n.timing||{status:'unknown',dates:[]}, a=n.analysis||{}, p=wfPreferences();
 return `<article class="card guidance-notice" data-notice-card data-notice-id="${esc(n.id)}"><div class="row"><span class="tag ${['open','closing'].includes(t.status)?'good':'warn'}">${wfLabels.status[t.status]}</span></div><h2>${esc(n.title)}</h2>
 ${safeUrl(n.url)!=='#'?`<a class="wf-official-link" href="${safeUrl(n.url)}" target="_blank" rel="noopener noreferrer">官方公告原文 ↗<small>${esc(n.url)}</small></a>`:'<p class="muted">原文链接尚未收集</p>'}
 <p class="muted guidance-notice-summary">${esc(a.summary||'尚未分析，打开公告后读取条件。')}</p>
 <div class="wf-tags">${['format','attendance','team'].map(key=>`<span class="tag">${esc(wfLabels[key][wfFact(n,key)]||'待核对')}</span>`).join('')}</div>
 ${(a.scoring_matches||[]).map(m=>`<p class="wf-recognition"><b>${esc(m.evidence_verified?m.category||'类别待核对':'类别待核对')}</b> · ${esc(wfLabels.recognition[m.evidence_verified?m.recognition:'pending']||'待认定')}<small>${esc(m.explanation||'')}</small></p>`).join('')||'<p class="muted">综测类别与认定依据待核对</p>'}
 ${t.registration_windows?.length?t.registration_windows.map(w=>`<div class="date-line"><b>${esc(w.track||'报名')}：${esc(wfLabels.status[w.status])}</b><div>${w.deadline?`${esc(w.deadline.label)}：${esc(w.deadline.date)}`:'报名截止日期待公布'}</div>${w.start_evidence?`<small>开始依据：${esc(w.start_evidence.quote)}</small>`:''}</div>`).join(''):(t.dates||[]).filter(d=>d.kind==='registration_end').map(d=>`<div class="date-line">${esc(wfLabels.scope[d.scope])} · ${esc(d.track||'')} ${esc(d.label)}：${esc(d.date)}</div>`).join('')||'<p class="muted">暂无有原文依据的报名截止日期</p>'}
 <label class="field"><span>我预计每周投入（小时）</span><input type="number" min="0" step="1" data-wf-effort="${esc(n.id)}" value="${esc(p.efforts?.[n.id]??'')}" placeholder="尚未估计"></label>
 <div class="card-footer"><div class="actions">${btn('条件与依据','notice',`data-id="${esc(n.id)}"`)}${btn('准备参加','wf-prepare',`data-id="${esc(n.id)}"`,'primary')}${btn('测算能加多少分','wf-scenario',`data-id="${esc(n.id)}"`)}</div></div></article>`;
}
function wfMatches(n,p) {
 const query=(p.query||'').trim().toLowerCase();
 if(query&&!JSON.stringify([n.title,n.analysis?.summary,n.analysis?.scoring_matches]).toLowerCase().includes(query))return false;
 for(const key of ['format','attendance','team']) {
  if(!p[key])continue;
  const value=wfFact(n,key);
  if(value==='unknown'){if(p.unknown===false)return false;continue}
  if(key==='team'&&value==='either')continue;
  if(key==='attendance'&&p[key]==='hybrid')continue;
  if(value!==p[key])return false;
 }
 if(Number(p.hours)>0){const effort=p.efforts?.[n.id];if(effort===undefined||effort===''){if(p.unknown===false)return false}else if(Number(effort)>Number(p.hours))return false}
 return true;
}
function workflowFilterRun() {
 if(page!=='opportunities')return;
 const p=wfPreferences(), visible=(S.notices||[]).filter(n=>n.policy_id===policyId&&wfMatches(n,p)), ids=new Set(visible.map(n=>n.id));
 for(const card of $$('[data-notice-card]'))card.hidden=!ids.has(card.dataset.noticeId);
 const count=$('#guidance-filter-count');if(count)count.textContent=`${visible.length} 份匹配公告；识别结果需对照赛道和原文，不等于学校认定。`;
 const old=$('.guidance-old-notices');if(old){old.hidden=!old.querySelector('[data-notice-card]:not([hidden])');if(p.query)old.open=true}
 const empty=$('#guidance-filter-empty');if(empty)empty.hidden=visible.length>0;
 const calendar=$('#wf-calendar');if(!calendar)return;
 const today=guidanceToday(), future=visible.flatMap(n=>(n.timing?.dates||[]).filter(d=>d.date>=today).map(d=>({n,d}))).sort((a,b)=>a.d.date.localeCompare(b.d.date));
 const expanded=calendar.querySelector('details')?.open;
 calendar.innerHTML=`<details class="card section-gap" ${expanded?'open':''}><summary>赛事日历 · ${future.length} 个后续节点${future.length?' · 最近 '+esc(future[0].d.date):''}</summary><div class="wf-calendar-summary">${['open','closing','upcoming','closed'].map(status=>`<span>${wfLabels.status[status]} <b>${visible.filter(n=>n.timing?.status===status).length}</b></span>`).join('')}</div><p class="muted">报名已结束的公告可用于准备下一届；新一届日期尚未公布时不推算。只有比赛日期不代表能报名。</p><div class="wf-calendar-list">${future.map(({n,d})=>`<div class="wf-calendar-row"><time>${esc(d.date)}</time><div><b>${esc(n.title)}</b><small>${esc(wfLabels.scope[d.scope])} · ${esc(d.track||'')} ${esc(d.label)}</small></div>${btn('查看','notice',`data-id="${esc(n.id)}"`,'subtle')}</div>`).join('')||'<p>暂无已核对的后续日期。</p>'}</div></details>`;
}
function workflowPlansView() {
 const plans=(S.plans||[]).filter(p=>(!p.policy_id||p.policy_id===policyId)&&(!p.profile_id||p.profile_id===profileId)).sort((a,b)=>Number(!!a.completed)-Number(!!b.completed)||(a.date||'9999').localeCompare(b.date||'9999'));
 return heading('行动计划','把报名、作品与材料准备逐项完成。',`<a href="/api/plans/calendar?policy_id=${encodeURIComponent(policyId||'')}&profile_id=${encodeURIComponent(profileId||'')}" download>导出未完成任务日历</a>`+btn('＋ 新建任务','add-plan','','primary'))+
 `<div class="wf-plan-list">${plans.map(p=>`<section class="card ${p.completed?'wf-complete':''}"><div class="rule-heading"><h2>${esc(p.title)}</h2><div class="actions">${btn('编辑','wf-edit-plan',`data-id="${esc(p.id)}"`)}${btn(p.completed?'恢复任务':'完成任务','wf-complete-plan',`data-id="${esc(p.id)}"`)}</div></div><p>${esc(p.date||'日期待核对')} · ${(p.checklist||[]).filter(x=>x.done).length}/${(p.checklist||[]).length} 项已完成</p><p class="muted">${esc(p.notes||'')}</p><div class="wf-checklist">${(p.checklist||[]).map((x,i)=>`<label><input type="checkbox" data-wf-check="${esc(p.id)}" data-index="${i}" ${x.done?'checked':''}><span>${esc(x.text)}</span></label>`).join('')}</div>${p.url?`<a href="${safeUrl(p.url)}" target="_blank" rel="noopener">查看原公告</a>`:''}</section>`).join('')||empty('还没有准备参加的项目','在公告卡片点击“准备参加”，会自动整理准备清单。')}</div>`;
}
function wfPlanDialog(p) {
 openDialog(dialogTitle('调整准备计划')+`<label class="field"><span>任务名称</span><input id="wf-plan-title" value="${esc(p.title)}"></label><label class="field"><span>提醒日期（可自行调整）</span><input id="wf-plan-date" type="date" value="${esc(p.date||'')}"></label><label class="field"><span>备注</span><textarea id="wf-plan-notes">${esc(p.notes||'')}</textarea></label><p class="muted">公告中的准备建议可删改；勾选进度会保留。</p><div id="wf-plan-rows">${(p.checklist||[]).map((x,i)=>wfPlanRow(x.text,i)).join('')}</div>${btn('添加准备事项','wf-add-check')}<div class="dialog-actions">${btn('删除整个任务','remove-plan',`data-id="${esc(p.id)}"`,'danger')}${btn('保存计划','wf-save-plan',`data-id="${esc(p.id)}"`,'primary')}</div>`,true);
}
function wfPlanRow(text,index='') {return `<div class="wf-check-edit"><input aria-label="准备事项" data-wf-check-text data-index="${index}" value="${esc(text)}">${btn('移除','wf-remove-check','','subtle')}</div>`}
function wfScenarioFields(rule) {
 return `<div class="field-grid">${rule.fields.map(f=>field(f,null,`data-wf-value="${esc(f.id)}"`)).join('')}</div>${list(rule.requirements)}${citations(rule.citations)}`;
}
function wfScenarioDialog(n) {
 if(!U())throw Error('先在上方建立自己的测评记录，再测算净增益');
 if(P().state!=='active')throw Error('请先核对并启用规则');
 const rules=P().item_rules||[], match=n.analysis?.scoring_matches?.find(m=>rules.some(r=>r.id===m.rule_id)), selected=rules.find(r=>r.id===match?.rule_id)||rules[0];
 if(!selected)throw Error('当前规则没有成果计分项');
 wfScenarioNotice=n.id;wfScenarioResult=null;
 openDialog(dialogTitle('假设获奖，能增加多少分？')+`<p>${esc(n.title)}</p><p class="notice">这是条件假设，不代表比赛已认定或已经获奖。会按当前记录计算封顶、权重与同项目冲突后的净增分。</p>${wfSelect('wf-scenario-rule','假设适用规则',rules.map(r=>[r.id,r.label||r.id]),selected.id)}<div id="wf-scenario-fields">${wfScenarioFields(selected)}</div><div class="field-grid"><label class="field"><span>假设获奖日期</span><input id="wf-scenario-date" type="date"></label><label class="field"><span>与已有哪个成果属于同一项目？</span><select id="wf-conflict"><option value="">独立新项目</option>${U().items.filter(i=>i.state!=='planned').map(i=>`<option value="${esc(i.id)}">${esc(i.name)}</option>`).join('')}</select></label></div><div id="wf-scenario-result" role="status"></div><div class="dialog-actions">${btn('计算净增益','wf-calculate','','primary')}${btn('准备参加','wf-prepare',`data-id="${esc(n.id)}"`)}</div>`);
}
async function wfCalculate() {
 await saveProfile(true);
 const n=S.notices.find(n=>n.id===wfScenarioNotice), original=U().items.find(i=>i.id===$('#wf-conflict').value);
 const item={name:n.title,rule_id:$('#wf-scenario-rule').value,date:$('#wf-scenario-date').value,values:Object.fromEntries($$('[data-wf-value]').map(el=>[el.dataset.wfValue,readControl(el)])),conflict_key:original?.conflict_key||'',same_item_id:original?.id||''};
 const result=await api('/api/profiles/'+profileId+'/scenario','POST',item);wfScenarioResult=result;
 const row=result.ledger.find(x=>x.id==='scenario');
 $('#wf-scenario-result').innerHTML=`<div class="notice"><b>预计净增 ${result.gain>=0?'+':''}${esc(result.gain)} 分</b><p>当前 ${esc(result.baseline)} → 假设达成 ${esc(result.total)} · 规则第 ${esc(result.policy_version)} 版</p>${row?.reason?`<p>${esc(row.reason)}</p>`:''}${list(result.notices.map(n=>n.message))}<small>此次测算不会加入已获成果；多个项目的净增分不能直接相加。</small></div>`;
}
function wfLookupLeaves(value,path=[]) {return Object.entries(value||{}).flatMap(([key,v])=>typeof v==='number'?[{path:[...path,key],value:v}]:v&&typeof v==='object'?wfLookupLeaves(v,[...path,key]):[])}
async function wfReviewDialog() {
 const p=P(), data=await api('/api/policies/'+p.id+'/review');
 wfReview={policy:structuredClone(p),data,changes:{version:p.version||1,formulas:{},item_rules:{},lookups:[]}};
 const rows=[...data.formulas.map(r=>({...r,section:'formulas'})),...data.item_rules.map(r=>({...r,section:'item_rules'}))];wfReview.rows=rows;
 openDialog(dialogTitle('对照原文核对规则')+`<p class="notice">改动保存为新草稿，核对后再启用。类别标识关联计分公式，显示供核对；需要更改归类逻辑时使用高级编辑。</p><div class="wf-review-grid"><section><h3>原文依据</h3><div id="wf-review-sources"></div><div id="wf-review-source" class="wf-source"></div></section><section>${wfSelect('wf-review-row','选择要核对的规则',rows.map((r,i)=>[String(i),r.label||r.id]),'0')}<div id="wf-review-fields"></div><details><summary>计分表（按类别、等级、奖项核对）</summary><div class="wf-lookup-list">${wfLookupLeaves(p.lookups).map((r,i)=>`<label class="field"><span>${esc(r.path.join(' / '))}</span><input type="number" step="any" data-wf-lookup="${i}" value="${r.value}"></label>`).join('')||'<p>当前方案没有独立计分表。</p>'}</div></details></section></div><div class="dialog-actions">${btn('保存核对改动','wf-save-review','','primary')}</div>`);
 wfReview.leaves=wfLookupLeaves(p.lookups);await wfReviewRow(0);
}
async function wfReviewRow(index) {
 const r=wfReview.rows[index];if(!r)return;wfReview.index=index;
 const edits=wfReview.changes[r.section][r.id]?.numbers||{};
 $('#wf-review-fields').innerHTML=`${r.category?`<p>成果分类标识：<b>${esc(r.category)}</b></p>`:''}<p class="formula">${esc(r.expression)}</p>${r.numbers.map(n=>`<label class="field"><span>${esc(n.label)}</span><input type="number" step="any" data-wf-number="${n.start}" value="${esc(edits[n.start]??n.value)}"></label>`).join('')||'<p class="muted">此项无可直接修改的数值；可在下方计分表核对分值。</p>'}${list(r.requirements)}`;
 const cs=r.citations||[];
 $('#wf-review-sources').innerHTML=cs.map((c,i)=>btn(`依据 ${i+1} · 第 ${c.unit} 页/段`,'wf-review-source',`data-index="${i}"`)).join('');
 await wfReviewSource(cs[0]);
}
let wfSourceRequest=0;
async function wfReviewSource(c) {
 const request=++wfSourceRequest, target=$('#wf-review-source');if(!target)return;
 if(!c){target.textContent='缺少来源引文，请补充原始细则再核对。';return}
 target.textContent='正在读取原文…';
 const d=await api('/api/documents/'+encodeURIComponent(c.document_id));
 if(request!==wfSourceRequest||!target.isConnected)return;
 const u=d.units[c.unit-1];target.innerHTML=`<blockquote>${esc(c.quote)}</blockquote><p>${esc(d.name)} · 第 ${esc(c.unit)} 页/段</p>${['.pdf','.png','.jpg','.jpeg','.webp'].includes(d.kind)?`<img src="/api/documents/${encodeURIComponent(d.id)}/preview/${c.unit}" alt="细则原文">`:''}<pre>${esc(u?.text||'未读取到该页文本')}</pre>`;
}
document.addEventListener('click',async event=>{
 const b=event.target.closest('[data-act^="wf-"]');if(!b||b.disabled)return;
 // The main handler only handles its own actions; this listener owns workflow actions.
 b.disabled=true;
 try {
 const act=b.dataset.act,id=b.dataset.id;
 if(act==='wf-reset-filters'){const p=wfPreferences();wfSavePreferences({efforts:p.efforts||{}});render()}
 else if(act==='wf-prepare'){
  if(!U())throw Error('请先在上方建立自己的测评记录');
  const p=await api('/api/notices/'+id+'/prepare','POST',{profile_id:profileId});await load(false);wfPlanDialog(p);notify('准备清单已保存；重复点击会打开同一份计划');
 }else if(act==='wf-scenario')wfScenarioDialog(S.notices.find(n=>n.id===id));
 else if(act==='wf-calculate'){await wfCalculate()}
 else if(act==='wf-edit-plan')wfPlanDialog(S.plans.find(p=>p.id===id));
 else if(act==='wf-add-check')$('#wf-plan-rows').insertAdjacentHTML('beforeend',wfPlanRow(''));
 else if(act==='wf-remove-check')b.closest('.wf-check-edit').remove();
 else if(act==='wf-save-plan'){
  const p=S.plans.find(p=>p.id===id),checklist=$$('[data-wf-check-text]').filter(el=>el.value.trim()).map(el=>({...p.checklist?.[Number(el.dataset.index)],id:el.dataset.index!==''?p.checklist?.[Number(el.dataset.index)]?.id:crypto.randomUUID(),text:el.value.trim(),done:el.dataset.index!==''?!!p.checklist?.[Number(el.dataset.index)]?.done:false}));
  await api('/api/plans/'+id,'PUT',{title:$('#wf-plan-title').value,date:$('#wf-plan-date').value,notes:$('#wf-plan-notes').value,checklist});$('#dialog').close();await load();notify('准备计划已保存');
 }else if(act==='wf-complete-plan'){const p=S.plans.find(p=>p.id===id);await api('/api/plans/'+id,'PUT',{completed:!p.completed});await load()}
 else if(act==='wf-pack'){await saveProfile(true);const response=await fetch('/api/profiles/'+profileId+'/application-pack');if(!response.ok)throw Error('材料包导出失败，请重试');const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='综测申报材料.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 else if(act==='wf-review')await wfReviewDialog();
 else if(act==='wf-review-source')await wfReviewSource(wfReview.rows[wfReview.index].citations[Number(b.dataset.index)]);
 else if(act==='wf-save-review'){
  await api('/api/policies/'+wfReview.policy.id+'/review','POST',wfReview.changes);$('#dialog').close();resetCalculation();await load();notify('已保存为新草稿，请核对后启用');
 }
 }catch(error){notify(error.message)}finally{b.disabled=false}
});
document.addEventListener('input',event=>{
 const el=event.target;
 if(el.matches('#guidance-notice-filter,#wf-hours')){const p=wfPreferences();p[el.id==='wf-hours'?'hours':'query']=el.value;wfSavePreferences(p);workflowFilterRun()}
 if(el.matches('[data-wf-number]')){const r=wfReview.rows[wfReview.index];wfReview.changes[r.section][r.id]??={numbers:{}};wfReview.changes[r.section][r.id].numbers[el.dataset.wfNumber]=readControl(el)}
 if(el.matches('[data-wf-lookup]')){const leaf=wfReview.leaves[Number(el.dataset.wfLookup)],edits=wfReview.changes.lookups;const i=edits.findIndex(e=>JSON.stringify(e.path)===JSON.stringify(leaf.path));const edit={path:leaf.path,value:readControl(el)};if(i<0)edits.push(edit);else edits[i]=edit}
 if(el.closest('#wf-scenario-fields')||el.matches('#wf-scenario-date,#wf-conflict')){const r=$('#wf-scenario-result');if(r)r.innerHTML='条件已变化，请重新计算。'}
});
document.addEventListener('change',async event=>{
 const el=event.target;
 try {
 if(el.matches('#wf-format,#wf-attendance,#wf-team,#wf-unknown')){const p=wfPreferences();p[el.id.slice(3)]=el.type==='checkbox'?el.checked:el.value;wfSavePreferences(p);workflowFilterRun()}
 if(el.matches('[data-wf-effort]')){const p=wfPreferences();p.efforts??={};p.efforts[el.dataset.wfEffort]=el.value;wfSavePreferences(p);workflowFilterRun()}
 if(el.matches('[data-wf-check]')){const controls=[...el.closest('.wf-checklist').querySelectorAll('input')];controls.forEach(x=>x.disabled=true);try{const p=structuredClone(S.plans.find(p=>p.id===el.dataset.wfCheck));p.checklist[Number(el.dataset.index)].done=el.checked;const updated=await api('/api/plans/'+p.id,'PUT',{checklist:p.checklist});S.plans=S.plans.map(x=>x.id===p.id?updated:x);if(page==='plans')render()}finally{controls.forEach(x=>x.disabled=false)}}
 if(el.id==='wf-scenario-rule'){$('#wf-scenario-fields').innerHTML=wfScenarioFields(P().item_rules.find(r=>r.id===el.value));$('#wf-scenario-result').innerHTML=''}
 if(el.id==='wf-review-row')await wfReviewRow(Number(el.value));
 }catch(error){if(el.matches('[data-wf-check]'))el.checked=!el.checked;notify(error.message)}finally{el.disabled=false}
});
