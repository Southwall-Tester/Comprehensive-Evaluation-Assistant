'use strict';

// Keep edits in order and refresh only the result panel while the user is typing.
let scoreMessage = '', saveMessage = '', calculationKey = '', calculationRequest = 0;
let editRevision = 0, saveQueue = Promise.resolve(), savingCount = 0;
const dirtyProfiles = new Map();
const profileEdits = new Map(), profileSavedRevisions = new Map();

function resetCalculation() {
 calcResult = null; calculationKey = ''; scoreMessage = ''; calculationRequest++;
}
function mergeLocalProfiles(incoming, revision, persisted) {
 for (const [id, local] of profileEdits) {
  if (local.revision <= revision && local.revision <= (persisted.get(id) || 0)) continue;
  const index = incoming.profiles.findIndex(u => u.id === id);
  if (index >= 0) incoming.profiles[index] = structuredClone(local.snapshot);
  else incoming.profiles.push(structuredClone(local.snapshot));
 }
}

function profileHasData(u) {
 return !!u && (Object.values(u.tables || {}).some(rows => rows.length) || (u.items || []).length > 0 || Object.values(u.inputs || {}).some(v => v !== null && v !== ''));
}
function scoreFingerprint() {
 const u = U(), p = P();
 return u && p ? JSON.stringify([p.id, p.version, p.state, u.id, u.inputs, u.tables, u.items, u.period_start, u.period_end]) : '';
}
function readableScoreError(message) {
 let text = message;
 for (const table of P()?.tables || []) text = text.replaceAll(table.id + ' 没有可计入的有效权重', `请补充${table.label}，并选择要计入的课程`);
 return text;
}
function updateScoreDisplays() {
 const summary = $('[data-score-summary]');
 if (summary) summary.innerHTML = scoreSummaryView();
 const status = $('#save-status');
 if (status) status.textContent = saveMessage;
 if (page === 'home' && !$('#dialog').open) $('#main').innerHTML = guidanceHomeView();
}
async function saveProfile(quiet = false) {
 clearTimeout(saveTimer);
 const snapshots = [...dirtyProfiles.entries()];
 for (const [id, snapshot] of snapshots) if (dirtyProfiles.get(id) === snapshot) dirtyProfiles.delete(id);
 if (snapshots.length) {
  savingCount++;
  const task = saveQueue.catch(() => {}).then(async () => {
   for (let i = 0; i < snapshots.length; i++) {
    const [id, snapshot] = snapshots[i];
    const local = profileEdits.get(id), revision = local?.snapshot === snapshot ? local.revision : 0;
    try { await api('/api/profiles/' + id, 'PUT', snapshot); if (revision) profileSavedRevisions.set(id, revision); }
    catch (error) {
     for (const [remainingId, remaining] of snapshots.slice(i)) if (!dirtyProfiles.has(remainingId) && profileEdits.get(remainingId)?.snapshot === remaining) dirtyProfiles.set(remainingId, remaining);
     throw error;
    }
   }
  });
  saveQueue = task;
  try { await task; saveMessage = dirtyProfiles.size ? '有修改待保存' : '已自动保存'; }
  catch (error) { saveMessage = '保存未完成，请点击重试'; throw error; }
  finally { savingCount--; updateScoreDisplays(); }
 } else await saveQueue;
 if (!quiet) notify('记录已保存');
}
function autosave() {
 const u = U(); if (!u) return;
 editRevision++;
 const snapshot = structuredClone(u);
 dirtyProfiles.set(u.id, snapshot); profileEdits.set(u.id, {revision:editRevision, snapshot});
 calcResult = null; calculationKey = ''; calculationRequest++;
 scoreMessage = '正在更新…'; saveMessage = '正在保存…';
 clearTimeout(saveTimer); updateScoreDisplays();
 saveTimer = setTimeout(() => saveProfile(true).then(() => refreshCalculation()).catch(error => {
  scoreMessage = '保存失败：' + error.message; updateScoreDisplays();
 }), 550);
}
async function refreshCalculation(includePlanned = false, force = false) {
 const u = U(), p = P();
 if (!u || !p) return;
 const fingerprint = scoreFingerprint(), key = fingerprint + ':' + includePlanned;
 if (!force && key === calculationKey) return;
 calculationKey = key;
 const request = ++calculationRequest;
 const stillCurrent = () => request === calculationRequest && fingerprint === scoreFingerprint();
 calcResult = null;
 if (p.state !== 'active') { scoreMessage = '当前细则仍是草稿，完成规则核对后才能估算。'; updateScoreDisplays(); return; }
 if (!profileHasData(u)) { scoreMessage = '上传成绩单，或添加一门课程 / 一项成果后开始。'; updateScoreDisplays(); return; }
 scoreMessage = '正在更新分数…'; updateScoreDisplays();
 try {
  await saveProfile(true);
  if (!stillCurrent()) return;
  const result = await api('/api/profiles/' + u.id + '/calculate', 'POST', {include_planned: includePlanned});
  if (!stillCurrent()) return;
  calcResult = result; scoreMessage = '';
 } catch (error) {
  if (!stillCurrent()) return;
  scoreMessage = readableScoreError(error.message);
 } finally { if (stillCurrent()) updateScoreDisplays(); }
}
function scoreSummaryView() {
 const u = U(), p = P(); if (!u || !p) return '';
 const pending = u.items.filter(it => it.state === 'pending').length;
 const planned = u.items.filter(it => it.state === 'planned').length;
 const assumptions = p.inputs.filter(f => u.inputs[f.id] === undefined && f.default !== undefined && f.default !== null);
 return `<h2>${calcResult?.include_planned ? '计划达成后的估算' : '按已录入数据估算'}</h2><div class="score-number" aria-live="polite">${calcResult ? esc(calcResult.total) : '—'}</div>
 ${scoreMessage ? `<p class="muted" role="status">${esc(scoreMessage)}</p>` : '<small>随资料修改自动更新；最终以学院审核为准。</small>'}
 ${/样例|虚构|测试/.test(u.name) ? '<div class="notice">这是虚构样例，不是你的实际成绩。</div>' : ''}
 ${pending ? `<p class="notice">${pending} 项成果待确认，尚未计分。</p>` : ''}
 ${calcResult ? `${calcResult.notices.map(n => `<div class="notice">${esc(n.message)}</div>`).join('')}<div class="actions section-gap">${btn('为什么是这个分数','ledger')}${btn('导出可读报告','readable-report')}</div>
 <details><summary>各项分数</summary>${calcResult.steps.map(s => `<div class="step-line"><span>${esc(s.label)}</span><strong>${Number(s.value).toFixed(3)}</strong></div>`).join('')}</details>
 ${planned ? `<div class="section-gap"><h3>计划项目能多带来多少分</h3>${(calcResult.planned_gains || []).map(x => `<p>${esc(x.name)} <b>${x.error ? esc(readableScoreError(x.error)) : (x.gain >= 0 ? '+' : '') + x.gain + ' 分'}</b></p>`).join('')}<small>分别相对当前分数测算，不能直接相加。</small></div>` : ''}
 <details><summary>基础数据变化的影响</summary>${(calcResult.sensitivity || []).map(s => `<p>${esc(s.label)} ${s.change > 0 ? '+' : ''}${s.change} → 总分 ${s.gain >= 0 ? '+' : ''}${s.gain}</p>`).join('')}</details>` : ''}
 ${assumptions.length ? `<details><summary>${assumptions.length} 项基础信息暂按规则默认值</summary>${assumptions.map(f => `<p>${esc(f.label)}：${esc(typeof f.default === 'boolean' ? (f.default ? '是' : '否') : f.default)}</p>`).join('')}<small>可在“基础信息与测评日期”中修改。</small></details>` : ''}
 <div class="actions section-gap">${planned && calcResult ? btn(calcResult.include_planned ? '返回当前估算' : '查看全部计划达成后', calcResult.include_planned ? 'calculate' : 'project-score') : ''}${btn('重新计算','calculate','','subtle')}</div>`;
}
function scoreView() {
 const p = P(), u = U(); if (!p) return needPolicy();
 if (!u) return empty('先放入你的成绩和成果','上传材料后核对提取的信息，就能开始估算。',btn('开始我的测评','start-score','','primary'));
 const requiredInputs = p.inputs.filter(f => f.default === undefined || f.default === null);
 const otherInputs = p.inputs.filter(f => !requiredInputs.includes(f));
 return btn('导出申报材料包', 'wf-pack', '', 'wf-pack-button') + heading('成绩与成果',esc(u.name),`<span id="save-status" role="status">${esc(saveMessage || '修改后自动保存、更新分数')}</span>${btn('上传成绩单 / 证明','extract-records','','primary')}`)+
 (p.state !== 'active' ? `<div class="notice">这份细则仍是待核对草稿。可以先整理材料；算分需要先完成规则核对。${btn('查看待确认内容','nav','data-page="rules"')}</div>` : '')+
 `<div class="score-layout"><div><section class="card"><h2>把材料交给助手整理</h2><p class="muted">上传成绩单、证书或证明，核对提取的成绩和成果。也可以在下面手动添加。</p>${btn('选择材料','extract-records')}<details class="section-gap" ${requiredInputs.length ? 'open' : ''}><summary>基础信息与测评日期${requiredInputs.length ? ' · 有必填信息' : ''}</summary><p class="muted">日期用于判断成果是否属于本次测评；有默认值的字段会在右侧列明。</p><div class="field-grid">${field({id:'period_start',label:'材料起始日期',type:'date'},u.period_start,'data-profile-meta="period_start"')}${field({id:'period_end',label:'材料截止日期',type:'date'},u.period_end,'data-profile-meta="period_end"')}${[...requiredInputs,...otherInputs].map(f=>field(f,u.inputs[f.id],`data-input="${esc(f.id)}"`)).join('')}</div></details></section>
 ${p.tables.map(t=>`<section class="card"><div class="rule-heading"><h2>${esc(t.label)}</h2>${btn('＋ 添加一行','add-row',`data-table="${esc(t.id)}"`)}</div><div class="table-wrap course-table"><table><thead><tr><th>名称 / 备注</th>${t.fields.map(f=>`<th>${esc(f.label)}</th>`).join('')}<th></th></tr></thead><tbody>${(u.tables[t.id]||[]).map((r,i)=>`<tr><td data-label="${esc(t.label)} / ${i+1}"><input value="${esc(r._label||'')}" data-table="${esc(t.id)}" data-row="${i}" data-column="_label" aria-label="名称 / 备注"></td>${t.fields.map(f=>`<td data-label="${esc(f.label)}">${field({...f,label:'',help:''},r[f.id],`data-table="${esc(t.id)}" data-row="${i}" data-column="${esc(f.id)}" aria-label="${esc(f.label)}"`)}</td>`).join('')}<td>${btn('×','remove-row',`data-table="${esc(t.id)}" data-row="${i}" aria-label="删除第 ${i+1} 行"`,'subtle danger')}</td></tr>`).join('')}</tbody></table></div>${!(u.tables[t.id]||[]).length?'<p class="muted">还没有记录，可以上传材料或手动添加。</p>':''}<details><summary>批量粘贴 CSV</summary><small>表头：${t.fields.map(f=>esc(f.id)).join(', ')}；布尔值 true/false。</small><textarea data-csv="${esc(t.id)}" placeholder="粘贴含表头的 CSV"></textarea>${btn('导入行','import-csv',`data-table="${esc(t.id)}"`)}</details></section>`).join('')}
 <section class="card"><div class="rule-heading"><h2>成果与计划</h2>${btn('＋ 添加成果','add-item')}</div>${u.items.length?u.items.map((it,i)=>`<div class="rule-row"><div class="rule-heading"><b>${esc(it.name)}</b><span class="tag ${it.state==='confirmed'?'good':'warn'}">${statusLabel(it.state)}</span></div><small>${esc(p.item_rules.find(r=>r.id===it.rule_id)?.label||'请重新选择计分类型')} · ${esc(it.date||'日期待填写')}</small><p class="muted">${esc(it.evidence||'可以补充证明信息')}</p><div class="actions">${btn(it.state==='pending'?'核对这项成果':'修改','edit-item',`data-index="${i}"`)}${btn('删除','remove-item',`data-index="${i}"`,'subtle danger')}</div></div>`).join(''):'<p class="muted">证书、竞赛、实践等成果放在这里。尚未获得的成果可以作为计划，看看实际能增加多少分。</p>'}</section>
 <details><summary>记录备份与手动保存</summary><div class="actions section-gap">${btn('保存 / 重试','save-profile')}<a href="/api/profiles/${esc(u.id)}/report" download>导出完整 JSON 备份</a></div></details></div>
 <aside class="card score-summary" data-score-summary>${scoreSummaryView()}</aside></div>`;
}
function exportReadableReport() {
 const p = P(), u = U(), r = calcResult; if (!p || !u || !r) throw Error('请先补充资料，得到估算结果');
 const lines = ['综测估算与材料清单', '', '测评记录：'+u.name, '细则：'+p.name, '材料期间：'+(u.period_start||'未填写')+' 至 '+(u.period_end||'未填写'), '估算总分：'+r.total+(r.include_planned?'（包含计划达成后的预估）':'（按已录入数据）'), '最终认定以学院审核为准。', '', '分数构成', ...r.steps.map(s=>s.label+'：'+s.value), '', '成果与计分情况', ...r.ledger.map(it=>it.name+'：'+it.score+' 分；'+(it.reason||'已参与汇总，仍受分类封顶影响')), '', '准备材料'];
 for (const it of u.items) {
  const rule=p.item_rules.find(x=>x.id===it.rule_id);
  lines.push(it.name+'（'+statusLabel(it.state)+'）', '证明：'+(it.evidence||'未填写'), ...(rule?.requirements||[]).map(x=>'  - '+x));
 }
 lines.push('', '提醒', ...r.notices.map(n=>n.message));
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/plain;charset=utf-8'}));a.download='综测估算与材料清单.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}

async function startScore(navigate = true) {
 if (!P()) { page = 'home'; render(); return; }
 await saveProfile(true);
 // Real uploads should never be appended to the bundled fictional example.
 if (!U() || (!navigate && guidanceIsSample(U()))) {
  const u = await api('/api/profiles', 'POST', {policy_id: policyId, name: '我的测评'});
  profileId = u.id; resetCalculation();page = 'score';
  await load();
 }
 if (navigate) { page = 'score'; render(); window.scrollTo(0, 0); }
}
function recordImportDialog() {
 if (!U()) throw Error('请先上传本次测评细则');
 const ruleDocuments = new Set((S.policies || []).flatMap(p => p.document_ids || []));
 const documents = [...S.documents].sort((a,b) => Number(ruleDocuments.has(a.id)) - Number(ruleDocuments.has(b.id)));
 openDialog(dialogTitle('添加成绩单或证明')+`<p class="muted">选择文件后自动提取，接下来只需核对成绩、名称等信息。</p><label class="upload-zone">从电脑选择材料<input type="file" id="record-upload" multiple accept=".pdf,.docx,.pptx,.xlsx,.txt,.csv,.png,.jpg,.jpeg,.webp"><small style="display:block">支持成绩单、证书、实践证明；可一次选择多份。</small></label><p id="record-upload-status" role="status"></p><details><summary>选择之前上传的材料（${documents.length}）</summary><div class="file-list scroll">${documents.map(d=>`<label class="file-row"><input type="checkbox" data-record-doc="${esc(d.id)}"><span>${esc(d.name)}${ruleDocuments.has(d.id)?' · 细则文件':''}</span></label>`).join('')}</div><div class="dialog-actions">${btn('读取选中的材料','start-records','','primary')}</div></details>`);
}
async function uploadRecords(files) {
 if (!files.length || !U()) return;
 const id = U().id, input = $('#record-upload'), ids = [];
 input.disabled = true;
 try {
  for (const file of files) {
   const status = $('#record-upload-status'); if (status) status.textContent = '正在上传：' + file.name;
   const body = new FormData(); body.append('file', file);
   const doc = await api('/api/documents','POST',body); ids.push(doc.id);
  }
  await load(false);
  const job = await api('/api/profiles/'+id+'/import-records','POST',{document_ids:ids});
  if ($('#record-upload')) $('#dialog').close();
  await track(job);
 } catch (error) {
  await load(false);
  if ($('#record-upload')) {
   recordImportDialog();
   for (const el of $$('[data-record-doc]')) el.checked = ids.includes(el.dataset.recordDoc);
   $('#record-upload-status').textContent = '未完成：'+error.message+'。已上传文件保留在下方，可选择后重试。';
  }
  throw error;
 } finally { input.disabled = false; input.value = ''; }
}
async function uploadRules(files) {
 if (!files.length) return;
 const input = $('#quick-rules-upload'), ids = []; input.disabled = true;
 try {
  for (const file of files) {
   notify('正在导入细则：'+file.name);
   const body=new FormData();body.append('file',file);
   const doc=await api('/api/documents','POST',body);ids.push(doc.id);uploadSelected.add(doc.id);
  }
  await load(false);
  await track(await api('/api/policies/generate','POST',{document_ids:ids}));
 } catch (error) { await load(); throw error; }
 finally { input.disabled=false;input.value=''; }
}
