'use strict';

// Loaded before app.js. Its shared UI helpers are used only when a review opens.
let recordReviewState = null;
const recordReviewDrafts = new Map();
const recordReviewQueue = new Map();
let recordReviewOpening = false;
const reviewObject = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const reviewArray = value => Array.isArray(value) ? value : [];
const reviewText = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value);

function reviewQueueButton() {
    let button = document.querySelector('#record-review-inbox');
    const waiting = [...recordReviewQueue.values()].filter(entry => entry.state !== 'open');
    if (!button && waiting.length) {
        button = document.createElement('button');
        button.id = 'record-review-inbox';
        button.className = 'primary';
        button.dataset.reviewQueueOpen = 'true';
        button.style.cssText = 'position:fixed;top:84px;right:16px;z-index:60;max-width:calc(100vw - 32px);box-shadow:var(--shadow)';
        document.body.append(button);
    }
    if (button) {
        button.hidden = waiting.length === 0;
        button.textContent = `${waiting.length} 份材料待核对`;
        button.setAttribute('aria-label', `打开待核对的材料提取结果，共 ${waiting.length} 份`);
    }
}

async function reviewOpenNext() {
    if (recordReviewOpening || document.querySelector('#dialog')?.open) return;
    const entry = [...recordReviewQueue.values()].find(item => item.state === 'queued');
    if (!entry) { reviewQueueButton(); return; }
    recordReviewOpening = true;
    entry.state = 'open';
    entry.openToken = (entry.openToken || 0) + 1;
    try {
        // No network await is needed here, so another dialog cannot open between
        // checking its state and displaying this already downloaded proposal.
        await openProposal(entry.proposal);
    } catch (error) {
        entry.state = 'paused';
        notify(error.message);
    } finally {
        recordReviewOpening = false;
        reviewQueueButton();
    }
}

async function queueProposalReview(proposal) {
    if (!proposal?.id || proposal.applied) return;
    if (!recordReviewQueue.has(proposal.id)) recordReviewQueue.set(proposal.id, {proposal, state: 'queued'});
    if (document.querySelector('#dialog')?.open) {
        reviewQueueButton();
        notify('材料已提取完成，当前窗口关闭后可继续核对。');
        return;
    }
    await reviewOpenNext();
}

function reviewSourceLinks(ids, citations = []) {
    return [...new Set(ids)].map(id => {
        const doc = S.documents?.find(d => d.id === id);
        if (!doc) return '';
        const cite = citations.find(c => c.document_id === id);
        const page = Number.isInteger(cite?.unit) && cite.unit > 0 ? cite.unit : null;
        const url = doc.source_url && /^https?:\/\//i.test(doc.source_url)
            ? doc.source_url : `/api/documents/${encodeURIComponent(id)}/file${page && doc.kind === '.pdf' ? '#page=' + page : ''}`;
        return `<a class="citation" href="${esc(url)}" target="_blank" rel="noopener" title="${esc(cite?.quote || '')}">${esc(doc.name)}${page ? ' · 第 ' + page + ' 页/段' : ''} ↗</a>`;
    }).join('');
}

function reviewControl(schema, value, attrs) {
    // Missing facts stay blank; a policy default is not evidence extracted from a document.
    const f = {...schema, default: undefined};
    if (f.type === 'boolean') {
        return `<label class="field"><span>${esc(f.label || f.id)}</span><select ${attrs} data-review-boolean="true"><option value="" ${typeof value !== 'boolean' ? 'selected' : ''}>尚未确定</option><option value="true" ${value === true ? 'selected' : ''}>是</option><option value="false" ${value === false ? 'selected' : ''}>否</option></select>${f.help ? `<small>${esc(f.help)}</small>` : ''}</label>`;
    }
    if (f.type === 'select' && value != null && value !== '' && !reviewArray(f.options).some(o => (typeof o === 'object' ? o.value : o) === value)) {
        f.options = [{value, label: `待修正：${reviewText(value)}`}, ...reviewArray(f.options)];
    }
    return field(f, value ?? '', attrs);
}

function reviewReadControl(el) {
    if (el.dataset.reviewBoolean) return el.value === '' ? null : el.value === 'true';
    if (el.type === 'number' && el.value === '') return null;
    return readControl(el);
}

function reviewKeep(checked, label) {
    return `<label class="field boolean"><input type="checkbox" data-review-keep ${checked ? 'checked' : ''}><span>${esc(label)}</span></label>`;
}

function reviewItemFields(item) {
    const rule = recordReviewState.policy.item_rules.find(r => r.id === item.rule_id);
    if (!rule) return '<p class="notice">请选择这项成果所属类别，或取消勾选本项。</p>';
    return `<div class="field-grid">${reviewArray(rule.fields).map(f => reviewControl(f, item.values[f.id], `data-review-value="${esc(f.id)}"`)).join('')}</div>${reviewArray(rule.requirements).length ? `<details><summary>此类成果的材料要求</summary>${list(rule.requirements)}${reviewSourceLinks(reviewArray(rule.citations).map(c => c.document_id), reviewArray(rule.citations))}</details>` : ''}`;
}

function reviewItemCard(item, index) {
    const rules = recordReviewState.policy.item_rules;
    const known = rules.some(r => r.id === item.rule_id);
    return `<section class="rule-row" data-review-item="${index}">
        <div class="rule-heading">${reviewKeep(item.include, `加入成果 ${index + 1}`)}<span class="tag warn">加入后待确认计分条件</span></div>
        <div class="field-grid" data-review-fields>
            ${reviewControl({id: 'name', label: '成果名称', type: 'text'}, item.name, 'data-review-meta="name"')}
            <label class="field"><span>成果类别</span><select data-review-rule><option value="" ${!known ? 'selected' : ''}>${known ? '请选择类别' : '尚未匹配，请选择类别'}</option>${rules.map(r => `<option value="${esc(r.id)}" ${r.id === item.rule_id ? 'selected' : ''}>${esc(r.label || r.id)}</option>`).join('')}</select></label>
            ${reviewControl({id: 'date', label: '证明落款日期', type: 'date'}, item.date, 'data-review-meta="date"')}
            ${reviewControl({id: 'conflict_key', label: '同一项目名称（用于避免重复计分）', type: 'text'}, item.conflict_key, 'data-review-meta="conflict_key"')}
        </div>
        <div data-review-item-fields>${reviewItemFields(item)}</div>
        <label class="field"><span>材料依据 / 待确认事项</span><textarea data-review-meta="evidence">${esc(item.evidence)}</textarea></label>
        <div class="citations">${reviewSourceLinks(reviewArray(item.citations).map(c => c.document_id), reviewArray(item.citations))}</div>
    </section>`;
}

function reviewCapture() {
    const root = document.querySelector('#record-review');
    if (!root || !recordReviewState) return;
    for (const card of root.querySelectorAll('[data-review-input]')) {
        const entry = recordReviewState.inputs[Number(card.dataset.reviewInput)];
        entry.include = card.querySelector('[data-review-keep]').checked;
        entry.value = reviewReadControl(card.querySelector('[data-review-base]'));
    }
    for (const card of root.querySelectorAll('[data-review-row]')) {
        const entry = recordReviewState.rows[Number(card.dataset.reviewRow)];
        entry.include = card.querySelector('[data-review-keep]').checked;
        for (const el of card.querySelectorAll('[data-review-column]')) entry.values[el.dataset.reviewColumn] = reviewReadControl(el);
    }
    for (const card of root.querySelectorAll('[data-review-item]')) {
        const item = recordReviewState.items[Number(card.dataset.reviewItem)];
        item.include = card.querySelector('[data-review-keep]').checked;
        for (const el of card.querySelectorAll('[data-review-meta]')) item[el.dataset.reviewMeta] = reviewReadControl(el);
        // Capture values before a category change replaces its controls.
        for (const el of card.querySelectorAll('[data-review-value]')) item.values[el.dataset.reviewValue] = reviewReadControl(el);
    }
}

function reviewUpdateSelection() {
    const root = document.querySelector('#record-review');
    if (!root) return;
    for (const card of root.querySelectorAll('[data-review-input], [data-review-row], [data-review-item]')) {
        const selected = card.querySelector('[data-review-keep]').checked;
        for (const el of card.querySelectorAll('input:not([data-review-keep]), select, textarea')) el.disabled = !selected;
    }
    const n = root.querySelectorAll('[data-review-keep]:checked').length;
    const action = root.querySelector('[data-act="apply-proposal"]');
    if (action) {
        action.disabled = n === 0;
        action.textContent = n ? `加入选中的 ${n} 项` : '请选择要加入的内容';
    }
}

async function openProposal(idOrProposal) {
    reviewCapture();
    const proposal = typeof idOrProposal === 'string' ? await api('/api/proposals/' + encodeURIComponent(idOrProposal)) : idOrProposal;
    if (!proposal?.id || !proposal.proposal) throw Error('这份材料提取结果不完整，请重新提取');
    if (proposal.applied) throw Error('这份材料已经加入记录');
    const profile = S.profiles?.find(p => p.id === proposal.profile_id);
    const policy = S.policies?.find(p => p.id === profile?.policy_id);
    if (!profile || !policy) throw Error('找不到这份材料对应的测评记录，请刷新页面后重试');
    const old = recordReviewDrafts.get(proposal.id);
    if (old && old.policyVersion === (policy.version || 1)) {
        recordReviewState = old;
    } else {
        const data = reviewObject(proposal.proposal);
        const inputs = reviewObject(data.inputs), tables = reviewObject(data.tables);
        const warnings = [...reviewArray(data.questions), ...reviewArray(data.warnings)].map(reviewText);
        const unknownInputs = Object.keys(inputs).filter(key => !policy.inputs.some(f => f.id === key));
        const unknownTables = Object.keys(tables).filter(key => !policy.tables.some(t => t.id === key));
        if (unknownInputs.length) warnings.push('有无法对应当前细则的基础信息，未自动加入：' + unknownInputs.join('、'));
        if (unknownTables.length) warnings.push('有无法对应当前细则的记录表，未自动加入：' + unknownTables.join('、'));
        recordReviewState = {
            id: proposal.id, profile, policy, policyVersion: policy.version || 1,
            documentIds: reviewArray(proposal.document_ids), warnings,
            inputs: policy.inputs.filter(f => Object.prototype.hasOwnProperty.call(inputs, f.id)).map(f => ({schema: f, value: inputs[f.id], include: true})),
            rows: policy.tables.flatMap(t => reviewArray(tables[t.id]).map((row, index) => ({table: t, values: {...reviewObject(row)}, index, include: true}))),
            items: reviewArray(data.items).map(raw => {
                const item = reviewObject(raw);
                return {...item, name: reviewText(item.name), date: reviewText(item.date), evidence: reviewText(item.evidence), conflict_key: reviewText(item.conflict_key), rule_id: item.rule_id || '', values: {...reviewObject(item.values)}, include: true};
            }),
        };
        recordReviewDrafts.set(proposal.id, recordReviewState);
    }
    const state = recordReviewState;
    const count = state.inputs.length + state.rows.length + state.items.length;
    openDialog(dialogTitle('核对从材料中读到的信息') + `<div id="record-review" data-proposal-id="${esc(state.id)}">
        <p class="muted">加入「${esc(profile.name)}」。核对名称、成绩和材料事实即可；不想加入的内容取消勾选，缺失信息可稍后补充。</p>
        <div class="citations">${reviewSourceLinks(state.documentIds)}</div>
        ${state.documentIds.length ? '<small class="muted">原材料在新标签页打开，这里的修改会保留。</small>' : ''}
        ${state.warnings.length ? `<div class="notice"><b>材料中还需核对的信息</b>${list(state.warnings)}</div>` : ''}
        ${state.inputs.length ? `<section class="section-gap"><h3>基础信息</h3>${state.inputs.map((entry, index) => `<div class="rule-row" data-review-input="${index}">${reviewKeep(entry.include, '更新' + (entry.schema.label || entry.schema.id))}${reviewControl(entry.schema, entry.value, 'data-review-base')}${Object.prototype.hasOwnProperty.call(profile.inputs || {}, entry.schema.id) ? `<small class="muted">当前记录：${esc(typeof profile.inputs[entry.schema.id] === 'boolean' ? (profile.inputs[entry.schema.id] ? '是' : '否') : profile.inputs[entry.schema.id])}。勾选后用本次信息更新。</small>` : ''}</div>`).join('')}</section>` : ''}
        ${policy.tables.map(t => {
            const rows = state.rows.map((row, index) => ({row, index})).filter(({row}) => row.table.id === t.id);
            return rows.length ? `<section class="section-gap"><h3>${esc(t.label || '课程记录')} · ${rows.length} 条</h3><small class="muted">选中记录将追加到现有记录；已录入的课程请取消勾选。</small>${rows.map(({row, index}) => `<div class="rule-row" data-review-row="${index}">${reviewKeep(row.include, `加入第 ${row.index + 1} 条`)}<div class="field-grid">${reviewControl({id: '_label', label: '名称 / 备注', type: 'text'}, row.values._label || row.values.name || '', 'data-review-column="_label"')}${reviewArray(t.fields).map(f => reviewControl(f, row.values[f.id], `data-review-column="${esc(f.id)}"`)).join('')}</div></div>`).join('')}</section>` : '';
        }).join('')}
        ${state.items.length ? `<section class="section-gap"><h3>成果 · ${state.items.length} 项</h3><p class="muted">加入后保留为待确认成果，确认符合细则后才计入分数。</p>${state.items.map(reviewItemCard).join('')}</section>` : ''}
        ${!count ? '<p class="notice">这次没有提取到可加入的数据。可以换一份清晰材料，或在测评页手动补充。</p>' : ''}
        <div class="dialog-actions">${btn('加入选中的内容', 'apply-proposal', `data-id="${esc(state.id)}"`, 'primary')}</div>
    </div>`);
    reviewUpdateSelection();
}

function reviewValidate(schema, value, control) {
    if (control?.validity?.badInput) {
        control.focus();
        throw Error('请核对' + (schema.label || schema.id));
    }
    if (value == null || value === '') return;
    const type = schema.type || 'number';
    let error = '';
    if (type === 'number' && (!Number.isFinite(Number(value)) || (schema.min !== undefined && value < schema.min) || (schema.max !== undefined && value > schema.max))) error = '请核对' + (schema.label || schema.id) + '的数值范围';
    if (type === 'select' && !reviewArray(schema.options).some(o => String(typeof o === 'object' ? o.value : o) === String(value))) error = '请重新选择' + (schema.label || schema.id);
    if (error) {
        control?.focus();
        throw Error(error);
    }
}

function readProposalReview() {
    const root = document.querySelector('#record-review');
    if (!root || !recordReviewState || root.dataset.proposalId !== recordReviewState.id) throw Error('请先打开材料核对结果');
    reviewCapture();
    const state = recordReviewState;
    const currentPolicy = S.policies?.find(p => p.id === state.policy.id);
    if (!currentPolicy || (currentPolicy.version || 1) !== state.policyVersion) throw Error('细则已更新，请重新打开这份材料并核对类别');
    const result = {inputs: {}, tables: {}, items: []};
    state.inputs.forEach((entry, index) => {
        if (!entry.include) return;
        reviewValidate(entry.schema, entry.value, root.querySelector(`[data-review-input="${index}"] [data-review-base]`));
        // An absent extraction must not erase an existing student fact.
        if (entry.value != null && entry.value !== '') result.inputs[entry.schema.id] = entry.value;
    });
    state.rows.forEach((entry, index) => {
        if (!entry.include) return;
        const card = root.querySelector(`[data-review-row="${index}"]`);
        const values = {_label: entry.values._label || ''};
        for (const f of entry.table.fields) {
            const el = [...card.querySelectorAll('[data-review-column]')].find(c => c.dataset.reviewColumn === f.id);
            reviewValidate(f, entry.values[f.id], el);
            values[f.id] = entry.values[f.id] ?? null;
        }
        (result.tables[entry.table.id] ??= []).push(values);
    });
    state.items.forEach((item, index) => {
        if (!item.include) return;
        const card = root.querySelector(`[data-review-item="${index}"]`);
        const rule = state.policy.item_rules.find(r => r.id === item.rule_id);
        if (!rule) {
            card.querySelector('[data-review-rule]').focus();
            throw Error(`请为成果 ${index + 1} 选择类别，或取消勾选本项`);
        }
        if (!item.name.trim()) {
            card.querySelector('[data-review-meta="name"]').focus();
            throw Error(`请填写成果 ${index + 1} 的名称，或取消勾选本项`);
        }
        const values = {};
        for (const f of reviewArray(rule.fields)) {
            const el = [...card.querySelectorAll('[data-review-value]')].find(c => c.dataset.reviewValue === f.id);
            reviewValidate(f, item.values[f.id], el);
            values[f.id] = item.values[f.id] ?? null;
        }
        result.items.push({name: item.name.trim(), rule_id: rule.id, date: item.date || '', conflict_key: item.conflict_key || '', evidence: item.evidence || '', values, state: 'pending'});
    });
    if (!Object.keys(result.inputs).length && !Object.values(result.tables).some(rows => rows.length) && !result.items.length) throw Error('请选择至少一项有内容的信息');
    return result;
}

document.addEventListener('input', event => {
    if (event.target.closest('#record-review')) reviewCapture();
});
document.addEventListener('change', event => {
    const el = event.target;
    if (!el.closest('#record-review') || !recordReviewState) return;
    reviewCapture();
    if (el.matches('[data-review-rule]')) {
        const card = el.closest('[data-review-item]');
        const item = recordReviewState.items[Number(card.dataset.reviewItem)];
        // Keep a separate set of facts per category; do not carry an award level
        // into an unrelated rule with coincidentally matching field IDs.
        item.ruleValues ??= {};
        item.ruleValues[item.rule_id] = {...item.values};
        item.rule_id = el.value;
        item.values = {...(item.ruleValues[item.rule_id] || {})};
        card.querySelector('[data-review-item-fields]').innerHTML = reviewItemFields(item);
    }
    reviewUpdateSelection();
});

document.addEventListener('click', event => {
    if (!event.target.closest('[data-review-queue-open]')) return;
    if (document.querySelector('#dialog')?.open) {
        notify('请先完成或关闭当前窗口，材料核对结果已保留。');
        return;
    }
    const entry = [...recordReviewQueue.values()].find(item => item.state === 'paused')
        || [...recordReviewQueue.values()].find(item => item.state === 'queued');
    if (entry) entry.state = 'queued';
    reviewOpenNext().catch(error => notify(error.message));
});

document.addEventListener('close', event => {
    if (event.target.id !== 'dialog') return;
    reviewCapture();
    const closedId = event.target.querySelector('#record-review')?.dataset.proposalId;
    const entry = recordReviewQueue.get(closedId);
    const token = entry?.openToken;
    if (entry?.state === 'open') entry.state = 'paused';
    // Let the initiating save/close handler finish before opening another form.
    setTimeout(async () => {
        if (entry) {
            try {
                const stored = await api('/api/proposals/' + encodeURIComponent(closedId));
                if (stored.applied) {
                    recordReviewQueue.delete(closedId);
                    recordReviewDrafts.delete(closedId);
                } else if (entry.openToken === token) entry.state = 'paused';
            } catch (_) {
                // A temporary connection failure must retain the reopening entry.
            }
        }
        reviewQueueButton();
        await reviewOpenNext();
    }, 0);
}, true);
