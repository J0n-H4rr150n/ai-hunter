import { BACKEND_URL, state, fmtDateTime, apiPost } from './config.js';
import { addToFeed, resetFeedScroll, scrollFeedToBottom } from './feed.js';
import { connectToSSE } from './sse.js';
import { refreshActiveTab } from './tabs.js';

export function updateMissionStatus(data) {
    console.log('Mission status update:', data);

    // Update control button visibility based on mission status
    if (data.type === 'mission_started' || data.type === 'playbook_started') {
        updateMissionControls({ status: 'running' });
    } else if (data.type === 'mission_complete' || data.type === 'mission_failed' || data.type === 'playbook_completed') {
        updateMissionControls({ status: 'completed' });
    }
}

// Status badge styling shared by the selector and the feed header.
const STATUS_STYLE = {
    running: 'accent', executing: 'accent', planning: 'warn', paused: 'warn',
    completed: 'good', stopped: '', aborted: 'warn', failed: 'bad',
};

// The header dot spins while something is running, mirroring Arena's bell.
const RUN_DOT = {
    running: 'running', executing: 'running', planning: 'running',
    paused: 'warn', completed: 'good', failed: 'bad', aborted: 'bad', stopped: '',
};

function hostOf(url) {
    try { return new URL(url).host; } catch { return url || 'unknown'; }
}

/** What to call a mission: its name if it has one, otherwise the target host. */
export function missionLabel(m) {
    return (m?.name || '').trim() || hostOf(m?.target_url);
}

// Rebuild the session picker. Called on boot and whenever a mission starts or ends,
// so a newly started mission shows up without a reload.
export async function loadMissionHistory(selectId = null) {
    try {
        const response = await fetch(`${BACKEND_URL}/api/missions`);
        if (!response.ok) return;

        const missions = await response.json();
        state.missions = missions;

        const selector = document.getElementById('mission-selector');
        const previous = selectId ?? selector.value;
        selector.innerHTML = '<option value="live">🔴 Live (follow newest)</option>';

        missions
            .slice()
            .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
            .forEach(mission => {
                const option = document.createElement('option');
                option.value = mission.id;
                option.textContent =
                    `#${mission.id} · ${missionLabel(mission)} · ${mission.status} · ${fmtDateTime(mission.created_at)}`;
                selector.appendChild(option);
            });

        // Keep the user's selection across a refresh.
        if (previous && [...selector.options].some(o => o.value === String(previous))) {
            selector.value = String(previous);
        }

        renderMissionList(missions);
    } catch (error) {
        console.error('Failed to load mission history:', error);
        const host = document.getElementById('mission-list');
        if (host) host.innerHTML = `<p class="empty">Could not load missions: ${error.message}</p>`;
    }
}

/**
 * The browsable list of sessions.
 *
 * The Missions tab had an empty "All missions" region: the markup existed but
 * nothing ever populated it, so the only way to reach a session was a dropdown
 * that is easy to miss on a phone.
 */
export function renderMissionList(missions) {
    const host = document.getElementById('mission-list');
    if (!host) return;

    if (!missions || !missions.length) {
        host.innerHTML = '<p class="empty">No missions yet. Use + to start one.</p>';
        return;
    }

    const ACCENT = {
        running: 'ok', executing: 'ok', planning: 'ok', paused: 'ok',
        completed: 'ok', failed: 'err', aborted: 'err', stopped: '',
    };

    const sorted = missions.slice().sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    host.innerHTML = sorted.map(m => `
        <div class="item clickable ${ACCENT[m.status] || ''}" data-mission="${m.id}">
            <div class="item-head">
                <strong>#${m.id} · ${escapeHtml(missionLabel(m))}</strong>
                <span class="item-time">${escapeHtml(fmtDateTime(m.created_at))}</span>
            </div>
            <div style="margin-top:.25rem">
                <span class="pill ${STATUS_STYLE[m.status] || ''}">${escapeHtml(m.status)}</span>
                ${m.name ? `<span class="pill">${escapeHtml(hostOf(m.target_url))}</span>` : ''}
                ${m.instructions ? `<span class="note">${escapeHtml(String(m.instructions).slice(0, 90))}…</span>` : ''}
            </div>
        </div>`).join('');

    host.querySelectorAll('[data-mission]').forEach(el => {
        el.addEventListener('click', async () => {
            await selectMission(Number(el.dataset.mission));
            // Jump to the feed: picking a session means wanting to see it.
            const { showTab } = await import('./tabs.js');
            showTab('feed');
        });
    });
}

function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Update the "which session am I looking at" header above the feed.
export function setFeedSession(mission) {
    const label = document.getElementById('feed-session');
    const badge = document.getElementById('feed-session-status');
    if (!label || !badge) return;

    const dot = document.getElementById('run-dot');

    if (!mission) {
        label.textContent = 'Live — newest mission';
        badge.textContent = 'live';
        badge.className = 'pill';
        if (dot) dot.className = '';
        return;
    }

    label.textContent = `#${mission.id} · ${missionLabel(mission)}`;
    label.title = `${mission.target_url} · started ${fmtDateTime(mission.created_at)}`
        + '\nClick to rename';
    label.dataset.missionId = String(mission.id);
    label.style.cursor = 'pointer';
    badge.textContent = mission.status;
    badge.className = `pill ${STATUS_STYLE[mission.status] || ''}`;
    if (dot) dot.className = RUN_DOT[mission.status] || '';
}

/**
 * Re-read the mission and update the session badge and the picker label.
 * Called on terminal/status events so a finished run stops reading as "running".
 */
/**
 * Set the active session from anywhere.
 *
 * Several SSE handlers used to assign state.currentMissionId directly, which left
 * the breadcrumb, the status pill and the other tabs out of sync — the header
 * could read "#17" while Findings still said "select a mission".
 */
export async function setCurrentMission(missionId, { reload = false } = {}) {
    if (!missionId) return;
    const changed = state.currentMissionId !== missionId;
    state.currentMissionId = missionId;

    if (changed || reload) {
        await refreshSessionHeader(missionId, { force: true });
        refreshActiveTab();
    }
}

export async function refreshSessionHeader(missionId, { force = false } = {}) {
    if (!missionId) return;
    if (!force && missionId !== state.currentMissionId) return;
    try {
        const mission = await (await fetch(`${BACKEND_URL}/api/missions/${missionId}`)).json();
        setFeedSession(mission);
        await loadMissionHistory(missionId);
    } catch (error) {
        console.warn('Could not refresh session header:', error);
    }
}

/**
 * Rename the active mission from the breadcrumb.
 *
 * Twenty runs against the same host are indistinguishable by URL alone, so the
 * label is editable in place rather than only at creation time.
 */
export function initMissionRename() {
    const label = document.getElementById('feed-session');
    label?.addEventListener('click', async () => {
        const missionId = Number(label.dataset.missionId);
        if (!missionId) return;

        const mission = state.missions.find(m => m.id === missionId);
        const current = (mission?.name || '').trim();
        const next = window.prompt('Name this mission (blank to clear):', current);
        if (next === null) return;

        try {
            await apiPost(`/api/missions/${missionId}/rename`, { name: next });
            await loadMissionHistory(missionId);
            await refreshSessionHeader(missionId, { force: true });
        } catch (error) {
            addToFeed({
                message: `❌ Could not rename: ${error.message}`,
                timestamp: new Date().toISOString(), type: 'error'
            });
        }
    });
}

export function initMissionSelector() {
    document.getElementById('mission-selector').addEventListener('change', async (e) => {
        if (e.target.value === 'live') {
            await selectLive();
            return;
        }
        await selectMission(parseInt(e.target.value));
    });
}

// Follow whatever mission is newest, rather than a specific session.
export async function selectLive() {
    state.currentMissionId = null;
    document.getElementById('feed-content').innerHTML = '';
    resetFeedScroll();
    setFeedSession(null);
    updateMissionControls(null);
    connectToSSE();            // global stream
}

/**
 * Switch the feed to one mission's session.
 *
 * The feed is rebuilt from the stored activity log, then the live stream is
 * re-pointed at that mission, so the view only ever contains events for the
 * selected session - live and historical missions render identically.
 */
export async function selectMission(missionId) {
    try {
        state.currentMissionId = missionId;

        const feedContent = document.getElementById('feed-content');
        feedContent.innerHTML = '';
        resetFeedScroll();

        const mission = await (await fetch(`${BACKEND_URL}/api/missions/${missionId}`)).json();
        setFeedSession(mission);

        // Sync the dropdown when selection came from elsewhere (e.g. a new mission).
        const selector = document.getElementById('mission-selector');
        if (selector && selector.value !== String(missionId)) selector.value = String(missionId);

        const events = await (await fetch(`${BACKEND_URL}/api/missions/${missionId}/activity`)).json();
        let lastLogId = 0;
        events.forEach(event => {
            if (event._log_id) lastLogId = Math.max(lastLogId, event._log_id);
            // Pass the whole event, not a hand-picked subset: dropping the other
            // fields is what made iteration_completed render as a bare type name
            // with the summary it was carrying nowhere in sight, and left the
            // entry with nothing to expand into.
            addToFeed(event);
        });

        if (!events.length) {
            addToFeed({
                message: `📜 Mission #${missionId} has no recorded activity yet.`,
                timestamp: new Date().toISOString(),
                type: 'info'
            });
        }

        // Resume the live stream after what we just replayed, so nothing is
        // duplicated and nothing published mid-switch is missed.
        connectToSSE(missionId, lastLogId);

        const active = ['planning', 'running', 'executing', 'paused'].includes(mission.status);
        updateMissionControls(active ? missionId : null);

        // Findings/evidence/tools belong to the selected session, not the last one.
        refreshActiveTab();

        try {
            const iterations = await (await fetch(`${BACKEND_URL}/api/missions/${missionId}/iterations`)).json();
            if (iterations && iterations.length) updateIterationsDisplay(iterations);
        } catch (err) {
            console.warn('No iterations for this mission:', err);
        }
    } catch (error) {
        console.error('Failed to select mission:', error);
        addToFeed({
            message: `❌ Could not load mission ${missionId}: ${error.message}`,
            timestamp: new Date().toISOString(),
            type: 'error'
        });
    }
}


// Helper function to update mission control button visibility
function updateMissionControls(missionState) {
    const pauseBtn = document.getElementById('pause-btn');
    const resumeBtn = document.getElementById('resume-btn');
    const stopBtn = document.getElementById('stop-btn');

    if (!pauseBtn || !resumeBtn || !stopBtn) return;

    // Only show controls if there's an active (running) mission
    if (missionState && missionState.status === 'running') {
        pauseBtn.classList.remove('hidden');
        stopBtn.classList.remove('hidden');
        resumeBtn.classList.add('hidden');
    } else {
        // Hide all buttons when no mission or mission not running
        pauseBtn.classList.add('hidden');
        resumeBtn.classList.add('hidden');
        stopBtn.classList.add('hidden');
    }
}

function updateIterationsDisplay(iterations) {
    // TODO: Update Plan tab to show historical iterations
    console.log('Historical iterations:', iterations);
}

function updateEvidenceDisplay(evidence) {
    // TODO: Update Evidence tab to show historical findings
    console.log('Historical evidence:', evidence);
}

// Start new mission
export function initNewMissionButton() {
    // Load available playbooks when modal opens
    document.getElementById('open-mission-modal').addEventListener('click', async () => {
        document.getElementById('mission-modal').classList.remove('hidden');
        await loadAvailablePlaybooks();
    });

    // Playbook selector change handler
    document.getElementById('playbook-selector').addEventListener('change', async (e) => {
        const playbookName = e.target.value;
        if (playbookName) {
            await showPlaybookInfo(playbookName);
        } else {
            document.getElementById('playbook-info').classList.add('hidden');
        }
    });

    // Modal controls
    document.getElementById('close-mission-modal').addEventListener('click', () => {
        document.getElementById('mission-modal').classList.add('hidden');
    });

    document.getElementById('mission-modal').addEventListener('click', (e) => {
        if (e.target.id === 'mission-modal') {
            document.getElementById('mission-modal').classList.add('hidden');
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.getElementById('mission-modal').classList.add('hidden');
        }
    });

    document.getElementById('start-mission-btn').addEventListener('click', async () => {
        const targetUrl = document.getElementById('target-url').value;
        const instructions = document.getElementById('instructions').value;
        const playbook = document.getElementById('playbook-selector').value;

        if (!targetUrl) {
            alert('Please enter a target URL');
            return;
        }

        document.getElementById('mission-modal').classList.add('hidden');
        const savedUrl = targetUrl;
        const savedInstructions = instructions;
        const savedPlaybook = playbook;
        document.getElementById('target-url').value = '';
        document.getElementById('instructions').value = '';
        document.getElementById('playbook-selector').value = '';
        document.getElementById('playbook-info').classList.add('hidden');

        try {
            const endpoint = playbook ? '/api/missions/start-playbook' : '/api/missions/start';
            const payload = {
                target_url: savedUrl,
                instructions: savedInstructions || null,
                name: (document.getElementById('mission-name')?.value || '').trim() || null,
            };

            if (playbook) {
                payload.playbook_name = savedPlaybook;
            }

            const response = await fetch(`${BACKEND_URL}${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            state.currentMissionId = data.mission_id;

            // Make the new run a selectable session and show only its events.
            await loadMissionHistory(data.mission_id);
            await selectMission(data.mission_id);

            // Show controls for new running mission
            updateMissionControls({ status: 'running' });

            if (playbook) {
                state.currentPlaybook = savedPlaybook;
                addToFeed({
                    message: `🎯 Starting playbook: ${savedPlaybook}`,
                    timestamp: new Date().toISOString()
                });
            }
        } catch (error) {
            console.error('Failed to start mission:', error);
            addToFeed({
                message: '❌ Failed to start mission. Is the backend running?',
                timestamp: new Date().toISOString()
            });
        }
    });
}

// Load available playbooks from backend
async function loadAvailablePlaybooks() {
    try {
        const response = await fetch(`${BACKEND_URL}/api/playbooks`);
        if (!response.ok) return;

        const playbooks = await response.json();
        const selector = document.getElementById('playbook-selector');

        // Clear existing options except first (Tactical Mode)
        while (selector.options.length > 1) {
            selector.remove(1);
        }

        // Add playbooks
        playbooks.forEach(playbook => {
            const option = document.createElement('option');
            option.value = playbook.id;  // Use id (filename stem) as value

            const emoji = playbook.category === 'ctf' ? '🏴' :
                playbook.category === 'test' ? '🧪' : '📋';

            option.textContent = `${emoji} ${playbook.name}`;  // Use name from metadata
            selector.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load playbooks:', error);
    }
}

// Show playbook information
async function showPlaybookInfo(playbookName) {
    try {
        const response = await fetch(`${BACKEND_URL}/api/playbooks/${playbookName}`);
        if (!response.ok) return;

        const playbook = await response.json();
        const info = playbook.metadata;

        document.getElementById('playbook-description').textContent =
            info.description || 'No description available';

        document.getElementById('playbook-category').textContent =
            `📂 ${info.category || 'N/A'}`;

        document.getElementById('playbook-difficulty').textContent =
            `⭐ ${info.difficulty || 'N/A'}`;

        document.getElementById('playbook-duration').textContent =
            `⏱️  ${info.estimated_duration || 'N/A'}`;

        document.getElementById('playbook-info').classList.remove('hidden');
    } catch (error) {
        console.error('Failed to load playbook info:', error);
    }
}

// Update playbook progress in sidebar
export function updatePlaybookProgress(data) {
    const container = document.getElementById('playbook-progress-container');
    const controls = document.getElementById('playbook-controls');

    if (!data || !data.playbook_name) {
        container.innerHTML = '<div class="text-sm text-gray-400 text-center py-8">No playbook running</div>';
        controls.classList.add('hidden');
        return;
    }

    // Show controls when playbook is running
    controls.classList.remove('hidden');

    const html = `
        <div class="space-y-3">
            <div class="border-b border-gray-700 pb-2">
                <h3 class="text-sm font-semibold text-blue-300">${data.playbook_name}</h3>
                <p class="text-xs text-gray-400">${data.goal || ''}</p>
            </div>

            <div class="space-y-2">
                <div class="flex justify-between text-xs">
                    <span class="text-gray-400">Progress</span>
                    <span class="text-blue-300">${data.current_stage || 0}/${data.total_stages || 0} runbooks</span>
                </div>
                
                <div class="w-full bg-gray-700 rounded-full h-2">
                    <div class="bg-blue-500 h-2 rounded-full transition-all duration-500" 
                         style="width: ${(data.current_stage / data.total_stages * 100) || 0}%"></div>
                </div>
            </div>

            ${data.current_runbook ? `
                <div class="bg-gray-700 p-3 rounded border border-gray-600">
                    <div class="text-xs font-semibold text-blue-300 mb-1">
                        🔄 Current: ${data.current_runbook}
                    </div>
                    ${data.current_step ? `
                        <div class="text-xs text-gray-400">
                            Step ${data.current_step.id}: ${data.current_step.name}
                        </div>
                    ` : ''}
                </div>
            ` : ''}

            ${data.completed_runbooks && data.completed_runbooks.length > 0 ? `
                <details class="text-xs">
                    <summary class="text-gray-400 cursor-pointer">
                        ✅ Completed (${data.completed_runbooks.length})
                    </summary>
                    <ul class="mt-2 space-y-1 pl-4">
                        ${data.completed_runbooks.map(rb => `
                            <li class="text-gray-500">• ${rb}</li>
                        `).join('')}
                    </ul>
                </details>
            ` : ''}

            ${data.findings_count !== undefined ? `
                <div class="flex justify-between text-xs pt-2 border-t border-gray-700">
                    <span class="text-gray-400">Findings</span>
                    <span class="text-green-400">${data.findings_count}</span>
                </div>
            ` : ''}
        </div>
    `;

    container.innerHTML = html;
}
