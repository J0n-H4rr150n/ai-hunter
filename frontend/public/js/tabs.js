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

    document.getElementById('detail-close')?.addEventListener('click', closePanel);
    initPanelResize();
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        closeSheet();
        closePanel();
    });

    // Crossing the breakpoint with something open would leave it in the wrong
    // container, so close rather than try to migrate it mid-resize.
    window.matchMedia(DESKTOP).addEventListener('change', () => {
        closeSheet();
        closePanel();
    });
}

export function showTab(name) {
    if (!VIEWS.includes(name)) return;
    if (name !== state.activeTab) closePanel();   // a record from another view is not relevant here
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


// ---------------------------------------------------------------- detail view
//
// One way of presenting a record, used by findings, tool calls, model calls and
// evidence: readable key/value pairs first, the raw JSON underneath for copying.
// Consistency matters more than per-view cleverness here.

const SCALAR = v => v === null || ['string', 'number', 'boolean'].includes(typeof v);

/** Flatten nested objects into dotted paths so everything is one scannable list. */
function flatten(value, prefix = '', out = {}, depth = 0) {
    if (value === null || value === undefined) {
        out[prefix || 'value'] = '';
        return out;
    }
    if (SCALAR(value)) {
        out[prefix || 'value'] = value;
        return out;
    }
    if (Array.isArray(value)) {
        if (!value.length) { out[prefix] = '[]'; return out; }
        if (value.every(SCALAR)) { out[prefix] = value.join(', '); return out; }
        if (depth >= 2) { out[prefix] = `${value.length} items`; return out; }
        value.forEach((v, i) => flatten(v, `${prefix}[${i}]`, out, depth + 1));
        return out;
    }
    const entries = Object.entries(value);
    if (!entries.length) { out[prefix] = '{}'; return out; }
    if (depth >= 3) { out[prefix] = `${entries.length} fields`; return out; }
    entries.forEach(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k, out, depth + 1));
    return out;
}

const VALUE_LIMIT = 400;

export function renderKV(obj, { skip = [] } = {}) {
    const flat = flatten(obj);
    const rows = Object.entries(flat)
        .filter(([k]) => !skip.some(s => k === s || k.startsWith(`${s}.`)))
        .filter(([, v]) => v !== '' && v !== undefined);

    if (!rows.length) return '<p class="k">No fields.</p>';

    return `<dl class="kv">${rows.map(([k, v]) => {
        const text = String(v);
        const long = text.length > VALUE_LIMIT;
        return `<dt>${escapeHtml(k)}</dt><dd class="${long ? 'long' : ''}">${escapeHtml(
            long ? text.slice(0, VALUE_LIMIT) + ' …' : text)}</dd>`;
    }).join('')}</dl>`;
}

/** Raw JSON with a copy button — kept so values can be lifted verbatim. */
export function rawBlock(obj, id) {
    const json = JSON.stringify(obj, null, 2);
    return `
        <div class="raw">
            <div class="raw-head">
                <span class="k">Raw JSON</span>
                <button class="btn ghost inline" data-copy="${id}">Copy</button>
            </div>
            <pre id="raw-${id}">${escapeHtml(json)}</pre>
        </div>`;
}

// Wide enough for a list and a details column side by side.
const DESKTOP = '(min-width: 1024px)';
export const isDesktop = () => window.matchMedia(DESKTOP).matches;

/**
 * Open a record.
 *
 * On a desktop this fills the side panel, which stays open so the next record
 * replaces it — clicking through a list never involves dismissing a dialog. On a
 * narrow screen it falls back to the full-screen sheet.
 */
export function openDetail(title, obj, { skip = [], extra = '', source = null } = {}) {
    const id = Math.random().toString(36).slice(2, 9);
    const body = `
        ${extra}
        <h2 class="sect">Details</h2>
        ${renderKV(obj, { skip })}
        ${rawBlock(obj, id)}
    `;

    markSelected(source);

    if (isDesktop()) {
        openPanel(title, body);
    } else {
        openSheet(title, body);
    }

    const button = document.querySelector(`[data-copy="${id}"]`);
    button?.addEventListener('click', async () => {
        const text = document.getElementById(`raw-${id}`).textContent;
        try {
            await navigator.clipboard.writeText(text);
            button.textContent = 'Copied';
        } catch {
            // clipboard API needs a secure context and permission; fall back.
            const ta = document.createElement('textarea');
            ta.value = text; document.body.appendChild(ta); ta.select();
            document.execCommand('copy'); ta.remove();
            button.textContent = 'Copied';
        }
        setTimeout(() => { button.textContent = 'Copy'; }, 1500);
    });
}



// ---------------------------------------------------------------- resizing

const PANEL_WIDTH_KEY = 'detailPanelWidth';
const PANEL_MIN_PX = 280;
const DEFAULT_PANEL_WIDTH = 416;        // 26rem

function panelMaxPx() {
    // Leave the list usable no matter how far the handle is dragged.
    return Math.max(PANEL_MIN_PX, Math.round(window.innerWidth * 0.75));
}

function applyPanelWidth(px) {
    const panel = document.getElementById('detail-panel');
    if (!panel) return;
    const clamped = Math.min(Math.max(px, PANEL_MIN_PX), panelMaxPx());
    panel.style.setProperty('--panel-w', `${clamped}px`);
    return clamped;
}

function initPanelResize() {
    const panel = document.getElementById('detail-panel');
    const handle = document.getElementById('detail-resize');
    if (!panel || !handle) return;

    const stored = Number(localStorage.getItem(PANEL_WIDTH_KEY));
    applyPanelWidth(Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_PANEL_WIDTH);

    let startX = 0;
    let startWidth = 0;

    const onMove = (e) => {
        // Dragging left widens the panel, so the delta is inverted.
        applyPanelWidth(startWidth + (startX - e.clientX));
    };

    const onUp = () => {
        panel.classList.remove('resizing');
        document.body.classList.remove('resizing');
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        const width = parseFloat(getComputedStyle(panel).getPropertyValue('--panel-w'));
        if (width) localStorage.setItem(PANEL_WIDTH_KEY, String(Math.round(width)));
    };

    handle.addEventListener('pointerdown', (e) => {
        if (!isDesktop()) return;
        e.preventDefault();
        startX = e.clientX;
        startWidth = panel.getBoundingClientRect().width;
        panel.classList.add('resizing');
        document.body.classList.add('resizing');
        // pointer events cover mouse, pen and touch with one path
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp, { once: true });
    });

    handle.addEventListener('dblclick', () => {
        applyPanelWidth(DEFAULT_PANEL_WIDTH);
        localStorage.setItem(PANEL_WIDTH_KEY, String(DEFAULT_PANEL_WIDTH));
    });

    // Keyboard: the handle is focusable, so it should be operable without a mouse.
    handle.addEventListener('keydown', (e) => {
        const step = e.shiftKey ? 64 : 16;
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        const current = panel.getBoundingClientRect().width;
        const next = applyPanelWidth(current + (e.key === 'ArrowLeft' ? step : -step));
        localStorage.setItem(PANEL_WIDTH_KEY, String(Math.round(next)));
    });

    // A stored width can exceed the viewport after the window shrinks.
    window.addEventListener('resize', () => {
        applyPanelWidth(panel.getBoundingClientRect().width || DEFAULT_PANEL_WIDTH);
    });
}

// ---------------------------------------------------------------- side panel

export function openPanel(title, bodyHtml) {
    const panel = document.getElementById('detail-panel');
    if (!panel) return;
    document.getElementById('detail-title').textContent = title;
    document.getElementById('detail-body').innerHTML = bodyHtml;
    panel.classList.add('open');
    document.body.classList.add('has-panel');
}

export function closePanel() {
    document.getElementById('detail-panel')?.classList.remove('open');
    document.body.classList.remove('has-panel');
    markSelected(null);
}

/** Highlight whichever row the panel is describing. */
function markSelected(el) {
    document.querySelectorAll('.item.selected, .shot.selected')
        .forEach(n => n.classList.remove('selected'));
    el?.classList.add('selected');
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
        const findings = await (await fetch(`${BACKEND_URL}/api/missions/${missionId}/findings`)).json();
        host.dataset.loadedFor = String(missionId);
        setCount('findings', findings.length);

        if (!findings.length) {
            host.innerHTML = '<p class="empty">No findings recorded yet.</p>';
            return;
        }

        // Group by type so a run of fingerprints reads as one section.
        const byType = {};
        findings.forEach(f => (byType[f.type || 'general'] ||= []).push(f));

        host.innerHTML = Object.entries(byType).map(([type, items]) => `
            <h2 class="sect" style="margin-top:.6rem">${escapeHtml(type)} · ${items.length}</h2>
            ${items.map((f, i) => renderFinding(f, `${type}:${i}`)).join('')}
        `).join('');

        host.querySelectorAll('[data-finding]').forEach(el => {
            el.addEventListener('click', () => {
                const [type, idx] = el.dataset.finding.split(':');
                const f = byType[type][Number(idx)];
                openDetail(`${f.type} · ${f.source || ''}`, f,
                    { skip: ['content_hash'], source: el });
            });
        });
    } catch (e) {
        host.innerHTML = `<p class="empty">Could not load findings: ${escapeHtml(e.message)}</p>`;
    }
}

// Severity drives the colour accent down the left edge of each card.
function severityOf(f) {
    const t = (f.type || '').toLowerCase();
    const c = f.content || {};
    if (c.flag || c.secret || t.includes('flag') || t.includes('secret') || t.includes('credential')) return 'critical';
    if (t.includes('vuln') || t.includes('idor') || t.includes('injection') || t.includes('xss')) return 'high';
    if (t.includes('error') || t.includes('disclosure') || t.includes('exposure')) return 'medium';
    if (t.includes('tech') || t.includes('fingerprint') || t.includes('discovery')) return 'info';
    return 'low';
}

/**
 * One finding as a scannable card.
 *
 * The list used to show only the type and the filename, so every finding looked
 * identical and the actual content required opening each one. Summarise the
 * content inline; the sheet is there for the raw JSON when it is needed.
 */
function renderFinding(f, key) {
    const c = f.content || {};
    const sev = severityOf(f);
    const when = f.timestamp ? fmtTime(f.timestamp) : '';

    const title = c.url || c.endpoint || c.location || f.source || f.type;
    const details = summariseContent(f.type, c);
    const tags = (f.tags || []).filter(t => t !== 'recon').slice(0, 4);

    return `
        <div class="item clickable sev-${sev}" data-finding="${escapeHtml(key)}">
            <div class="item-head">
                <strong class="mono" style="word-break:break-all">${escapeHtml(String(title))}</strong>
                <span class="item-time">${escapeHtml(when)}</span>
            </div>
            ${details ? `<div style="margin-top:.25rem">${details}</div>` : ''}
            <div style="margin-top:.3rem">
                ${tags.map(t => `<span class="pill tag">${escapeHtml(t)}</span>`).join('')}
                ${f._unattributed ? '<span class="pill warn">earlier run</span>' : ''}
            </div>
        </div>`;
}

// Per-type summaries: show the thing that was actually found.
function summariseContent(type, c) {
    if (c.technologies && typeof c.technologies === 'object') {
        return Object.entries(c.technologies)
            .map(([k, v]) => `<span class="pill accent">${escapeHtml(k)}: ${escapeHtml(String(v))}</span>`)
            .join('');
    }
    if (Array.isArray(c.interactive_elements)) {
        const els = c.interactive_elements;
        const kinds = {};
        els.forEach(e => (kinds[e.tagName || '?'] = (kinds[e.tagName || '?'] || 0) + 1));
        const labels = els.map(e => (e.text || '').trim()).filter(Boolean).slice(0, 3);
        return [
            `<span class="pill accent">${els.length} interactive element${els.length === 1 ? '' : 's'}</span>`,
            ...Object.entries(kinds).slice(0, 4).map(([tag, n]) =>
                `<span class="pill">${escapeHtml(tag)} ×${n}</span>`),
            labels.length
                ? `<div class="k" style="margin-top:.25rem">${escapeHtml(labels.join(' · '))}</div>`
                : '',
        ].join('');
    }
    if (c.title || c.status_code) {
        return [
            c.title ? `<span class="pill">${escapeHtml(String(c.title))}</span>` : '',
            c.status_code ? `<span class="pill ${String(c.status_code).startsWith('2') ? 'good' : 'warn'}">HTTP ${escapeHtml(String(c.status_code))}</span>` : '',
        ].join('');
    }
    if (c.evidence || c.secret || c.flag) {
        const v = c.flag || c.secret || c.evidence;
        return `<div class="mono" style="color:var(--bad);word-break:break-all">${escapeHtml(String(v).slice(0, 300))}</div>`;
    }
    if (c.payload || c.parameter) {
        return [
            c.parameter ? `<span class="pill">param: ${escapeHtml(String(c.parameter))}</span>` : '',
            c.payload ? `<code>${escapeHtml(String(c.payload).slice(0, 120))}</code>` : '',
        ].join(' ');
    }
    // Anything else: show the first few scalar fields rather than nothing.
    const scalars = Object.entries(c)
        .filter(([k, v]) => k !== 'url' && (typeof v === 'string' || typeof v === 'number'))
        .slice(0, 3);
    return scalars.map(([k, v]) =>
        `<span class="pill">${escapeHtml(k)}: ${escapeHtml(String(v).slice(0, 80))}</span>`).join('');
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
                openDetail(s.action || s.filename, s, {
                    source: el,
                    extra: `<img src="${BACKEND_URL}${s.url}" alt="">`,
                });
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
                openDetail(`${c.tool_name} · ${c.status}`, c, {
                    source: el,
                    skip: ['inputs', 'outputs'],
                    extra: `
                        <p class="k">${escapeHtml(fmtDateTime(c.started_at))}
                           ${c.duration_ms != null ? `· ${c.duration_ms} ms` : ''}</p>
                        ${c.error_message ? `<p style="color:var(--bad)">${escapeHtml(c.error_message)}</p>` : ''}
                        <h2 class="sect">Inputs</h2>${renderKV(c.inputs)}
                        <h2 class="sect">Outputs</h2>${renderKV(c.outputs)}`,
                });
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
                openDetail(`${t.agent_name || 'model'} · ${t.llm_model || ''}`, t, {
                    source: el,
                    skip: ['system_prompt', 'user_prompt', 'llm_response'],
                    extra: `
                        ${t.error_message ? `<p style="color:var(--bad)">${escapeHtml(t.error_message)}</p>` : ''}
                        ${t.system_prompt ? `<h2 class="sect">System prompt</h2>
                            <pre>${escapeHtml(t.system_prompt)}</pre>` : ''}
                        <h2 class="sect">Prompt</h2><pre>${escapeHtml(t.user_prompt)}</pre>
                        <h2 class="sect">Response</h2>
                        <pre>${escapeHtml(t.llm_response || '(none)')}</pre>`,
                });
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
