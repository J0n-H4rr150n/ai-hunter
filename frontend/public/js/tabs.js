// Tab navigation and the views that did not exist before: findings, tool calls,
// and evidence as a first-class screen rather than a modal.
//
// Each view loads lazily when opened and refreshes when the selected mission
// changes, so switching sessions does not leave another mission's data on screen.

import { BACKEND_URL, state, fmtTime, fmtDateTime } from './config.js';

const VIEWS = ['feed', 'findings', 'evidence', 'tools', 'llm', 'plan', 'missions'];

export function initTabs() {
    document.querySelectorAll('#tabs button').forEach(btn => {
        btn.addEventListener('click', () => showTab(btn.dataset.tab));
    });

    document.getElementById('crumb-home')?.addEventListener('click', () => showTab('missions'));

    const sheet = document.getElementById('sheet');
    sheet?.addEventListener('click', (e) => { if (e.target === sheet) closeSheet(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeSheet(); });
}

export function showTab(name) {
    if (!VIEWS.includes(name)) return;
    state.activeTab = name;

    VIEWS.forEach(v => {
        document.getElementById(`view-${v}`)?.classList.toggle('on', v === name);
        document.querySelector(`#tabs button[data-tab="${v}"]`)?.classList.toggle('on', v === name);
    });

    // Load on demand; the feed is already live.
    if (name === 'findings') loadFindings();
    if (name === 'evidence') loadEvidence();
    if (name === 'tools') loadToolCalls();
    if (name === 'llm') loadLlmTraces();
}

// Called when the session changes so stale data is not left behind.
export function refreshActiveTab() {
    ['findings', 'evidence', 'tools', 'llm'].forEach(v => {
        const el = document.getElementById(`${v}-list`) || document.getElementById('evidence-screenshots');
        if (el) el.dataset.loadedFor = '';
    });
    if (state.activeTab && state.activeTab !== 'feed') showTab(state.activeTab);
    updateTabCounts();
}

// ---------------------------------------------------------------- sheet

export function openSheet(title, bodyHtml) {
    const card = document.getElementById('sheet-card');
    card.innerHTML = `
        <div class="sheet-head">
            <h3>${escapeHtml(title)}</h3>
            <button class="icon-btn" id="sheet-close">✕</button>
        </div>
        ${bodyHtml}`;
    document.getElementById('sheet').classList.remove('hidden');
    document.getElementById('sheet-close').addEventListener('click', closeSheet);
    document.documentElement.style.overflow = 'hidden';
}

export function closeSheet() {
    document.getElementById('sheet')?.classList.add('hidden');
    document.documentElement.style.overflow = '';
}

// ---------------------------------------------------------------- findings

async function loadFindings() {
    const host = document.getElementById('findings-list');
    const missionId = state.currentMissionId;
    if (!host) return;

    if (!missionId) {
        host.innerHTML = '<p class="empty">Select a mission to see its findings.</p>';
        return;
    }
    if (host.dataset.loadedFor === String(missionId)) return;

    host.innerHTML = '<p class="empty">Loading…</p>';
    try {
        const res = await fetch(`${BACKEND_URL}/api/missions/${missionId}/artifacts`);
        const data = await res.json();
        const findings = data.findings || [];
        host.dataset.loadedFor = String(missionId);

        if (!findings.length) {
            host.innerHTML = '<p class="empty">No findings recorded yet.</p>';
            setCount('findings', 0);
            return;
        }

        setCount('findings', findings.length);
        host.innerHTML = findings.map((f, i) => `
            <div class="item clickable sev-${severityOf(f)}" data-finding="${i}">
                <div class="item-head">
                    <strong>${escapeHtml(f.type || 'finding')}</strong>
                    <span class="item-time">${escapeHtml(f.filename || '')}</span>
                </div>
                <span class="pill tag">${escapeHtml(f.type || 'general')}</span>
            </div>`).join('');

        host.querySelectorAll('[data-finding]').forEach(el => {
            el.addEventListener('click', async () => {
                const f = findings[Number(el.dataset.finding)];
                const detail = await (await fetch(`${BACKEND_URL}${f.url}`)).json();
                openSheet(f.type || 'Finding', `<pre>${escapeHtml(JSON.stringify(detail, null, 2))}</pre>`);
            });
        });
    } catch (e) {
        host.innerHTML = `<p class="empty">Could not load findings: ${escapeHtml(e.message)}</p>`;
    }
}

function severityOf(f) {
    const t = (f.type || '').toLowerCase();
    if (t.includes('vuln') || t.includes('flag') || t.includes('secret')) return 'critical';
    if (t.includes('xss') || t.includes('idor') || t.includes('error')) return 'high';
    if (t.includes('tech') || t.includes('fingerprint')) return 'info';
    return 'low';
}

// ---------------------------------------------------------------- evidence

async function loadEvidence() {
    const shots = document.getElementById('evidence-screenshots');
    const meta = document.getElementById('evidence-metadata');
    const missionId = state.currentMissionId;
    if (!shots) return;

    if (!missionId) {
        shots.innerHTML = '<p class="empty">Select a mission to see its evidence.</p>';
        return;
    }
    if (shots.dataset.loadedFor === String(missionId)) return;

    shots.innerHTML = '<p class="empty">Loading…</p>';
    try {
        const data = await (await fetch(`${BACKEND_URL}/api/missions/${missionId}/artifacts`)).json();
        shots.dataset.loadedFor = String(missionId);

        const screenshots = data.screenshots || [];
        document.getElementById('screenshot-count').textContent = screenshots.length;
        document.getElementById('metadata-count').textContent = (data.metadata || []).length;
        document.getElementById('findings-count').textContent = (data.findings || []).length;

        shots.innerHTML = screenshots.length
            ? screenshots.map((s, i) => `
                <div class="shot" data-shot="${i}">
                    <img loading="lazy" src="${BACKEND_URL}${s.url}" alt="${escapeHtml(s.action || '')}">
                    <div class="cap">${escapeHtml(s.action || s.filename)}</div>
                </div>`).join('')
            : '<p class="empty">No screenshots captured yet.</p>';

        shots.querySelectorAll('[data-shot]').forEach(el => {
            el.addEventListener('click', () => {
                const s = screenshots[Number(el.dataset.shot)];
                openSheet(s.action || s.filename,
                    `<img src="${BACKEND_URL}${s.url}" alt=""><p class="k">${escapeHtml(s.filename)}</p>`);
            });
        });

        if (meta) {
            meta.innerHTML = (data.metadata || []).length
                ? data.metadata.map(m => `<div class="item mono">${escapeHtml(m.filename)}</div>`).join('')
                : '<p class="empty">No metadata files.</p>';
        }
    } catch (e) {
        shots.innerHTML = `<p class="empty">Could not load evidence: ${escapeHtml(e.message)}</p>`;
    }
}

// ---------------------------------------------------------------- tool calls

async function loadToolCalls() {
    const host = document.getElementById('tools-list');
    const missionId = state.currentMissionId;
    if (!host) return;

    if (!missionId) {
        host.innerHTML = '<p class="empty">Select a mission to see its tool calls.</p>';
        return;
    }
    if (host.dataset.loadedFor === String(missionId)) return;

    host.innerHTML = '<p class="empty">Loading…</p>';
    try {
        const calls = await (await fetch(`${BACKEND_URL}/api/missions/${missionId}/tools`)).json();
        host.dataset.loadedFor = String(missionId);
        setCount('tools', calls.length);

        if (!calls.length) {
            host.innerHTML = '<p class="empty">No tool calls recorded for this mission.</p>';
            return;
        }

        host.innerHTML = calls.map((c, i) => `
            <div class="item clickable ${c.status === 'failed' ? 'err' : c.status === 'success' ? 'ok' : ''}"
                 data-call="${i}">
                <div class="item-head">
                    <strong class="mono">${escapeHtml(c.tool_name)}</strong>
                    <span class="item-time">${c.duration_ms != null ? c.duration_ms + ' ms' : '…'}</span>
                </div>
                <span class="pill ${c.status === 'success' ? 'good' : c.status === 'failed' ? 'bad' : 'warn'}">
                    ${escapeHtml(c.status)}</span>
                <span class="item-time">${fmtTime(c.started_at)}</span>
                ${c.error_message ? `<div class="k" style="color:var(--bad)">${escapeHtml(c.error_message)}</div>` : ''}
            </div>`).join('');

        host.querySelectorAll('[data-call]').forEach(el => {
            el.addEventListener('click', () => {
                const c = calls[Number(el.dataset.call)];
                openSheet(`${c.tool_name} · ${c.status}`, `
                    <p class="k">Started ${escapeHtml(fmtDateTime(c.started_at))}
                       ${c.duration_ms != null ? `· ${c.duration_ms} ms` : ''}</p>
                    ${c.error_message ? `<p style="color:var(--bad)">${escapeHtml(c.error_message)}</p>` : ''}
                    <h2 class="sect">Inputs</h2>
                    <pre>${escapeHtml(JSON.stringify(c.inputs, null, 2))}</pre>
                    <h2 class="sect">Outputs</h2>
                    <pre>${escapeHtml(JSON.stringify(c.outputs, null, 2))}</pre>`);
            });
        });
    } catch (e) {
        host.innerHTML = `<p class="empty">Could not load tool calls: ${escapeHtml(e.message)}</p>`;
    }
}


// ---------------------------------------------------------------- llm traces

async function loadLlmTraces() {
    const host = document.getElementById('llm-list');
    const missionId = state.currentMissionId;
    if (!host) return;

    if (!missionId) {
        host.innerHTML = '<p class="empty">Select a mission to see its model calls.</p>';
        return;
    }
    if (host.dataset.loadedFor === String(missionId)) return;

    host.innerHTML = '<p class="empty">Loading…</p>';
    try {
        const traces = await (await fetch(`${BACKEND_URL}/api/missions/${missionId}/llm`)).json();
        host.dataset.loadedFor = String(missionId);
        setCount('llm', traces.length);

        if (!traces.length) {
            host.innerHTML = '<p class="empty">No model calls recorded for this mission.</p>';
            return;
        }

        const totalIn = traces.reduce((a, t) => a + (t.input_tokens || 0), 0);
        const totalOut = traces.reduce((a, t) => a + (t.output_tokens || 0), 0);
        const totalMs = traces.reduce((a, t) => a + (t.elapsed_time_ms || 0), 0);

        host.innerHTML = `
            <div class="item">
                <div class="k">Totals</div>
                <span class="pill accent">${traces.length} calls</span>
                <span class="pill">${totalIn.toLocaleString()} in</span>
                <span class="pill">${totalOut.toLocaleString()} out</span>
                <span class="pill">${(totalMs / 1000).toFixed(1)}s</span>
            </div>` + traces.map((t, i) => `
            <div class="item clickable ${t.status === 'failed' ? 'err' : 'ok'}" data-trace="${i}">
                <div class="item-head">
                    <strong>${escapeHtml(t.agent_name || 'model')}</strong>
                    <span class="item-time">${t.elapsed_time_ms != null ? (t.elapsed_time_ms / 1000).toFixed(1) + 's' : '…'}</span>
                </div>
                <span class="pill ${t.status === 'failed' ? 'bad' : 'good'}">${escapeHtml(t.status || '')}</span>
                <span class="pill">${t.input_tokens ?? '?'} in / ${t.output_tokens ?? '?'} out</span>
                ${t.tokens_per_second ? `<span class="pill">${t.tokens_per_second.toFixed(1)} tok/s</span>` : ''}
                <span class="item-time">${fmtTime(t.timestamp_start)}</span>
                ${t.error_message ? `<div class="k" style="color:var(--bad)">${escapeHtml(t.error_message)}</div>` : ''}
            </div>`).join('');

        host.querySelectorAll('[data-trace]').forEach(el => {
            el.addEventListener('click', () => {
                const t = traces[Number(el.dataset.trace)];
                openSheet(`${t.agent_name || 'model'} · ${t.llm_model || ''}`, `
                    <p class="k">${escapeHtml(fmtDateTime(t.timestamp_start))}
                       ${t.elapsed_time_ms != null ? `· ${(t.elapsed_time_ms / 1000).toFixed(1)}s` : ''}
                       ${t.finish_reason ? `· finish: ${escapeHtml(t.finish_reason)}` : ''}</p>
                    ${t.error_message ? `<p style="color:var(--bad)">${escapeHtml(t.error_message)}</p>` : ''}
                    ${t.system_prompt ? `<h2 class="sect">System prompt</h2>
                        <pre>${escapeHtml(t.system_prompt)}</pre>` : ''}
                    <h2 class="sect">Prompt</h2>
                    <pre>${escapeHtml(t.user_prompt)}</pre>
                    <h2 class="sect">Response</h2>
                    <pre>${escapeHtml(t.llm_response || '(none)')}</pre>`);
            });
        });
    } catch (e) {
        host.innerHTML = `<p class="empty">Could not load model calls: ${escapeHtml(e.message)}</p>`;
    }
}

// ---------------------------------------------------------------- helpers

function setCount(tab, n) {
    const el = document.getElementById(`tab-count-${tab}`);
    if (!el) return;
    el.textContent = n > 99 ? '99+' : String(n);
    el.hidden = !n;
}

export async function updateTabCounts() {
    const missionId = state.currentMissionId;
    if (!missionId) {
        setCount('findings', 0);
        setCount('tools', 0);
        setCount('llm', 0);
        return;
    }
    try {
        const [artifacts, tools, traces] = await Promise.all([
            fetch(`${BACKEND_URL}/api/missions/${missionId}/artifacts`).then(r => r.json()),
            fetch(`${BACKEND_URL}/api/missions/${missionId}/tools`).then(r => r.json()),
            fetch(`${BACKEND_URL}/api/missions/${missionId}/llm`).then(r => r.json()),
        ]);
        setCount('findings', (artifacts.findings || []).length);
        setCount('tools', (tools || []).length);
        setCount('llm', (traces || []).length);
    } catch { /* counts are cosmetic */ }
}

export function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
