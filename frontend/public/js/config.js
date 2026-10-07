// Backend connection.
//
// Single-port mode (serve.py) hosts the API on this same origin, so an empty base
// keeps every fetch relative — that is what makes HTTPS-over-Tailscale work from a
// phone without mixed-content errors. The split Docker setup serves the UI from
// :33004 with the API on :33003, so fall back to the explicit port there.
const SPLIT_PORT_UI = '33004';

export const BACKEND_URL = window.location.port === SPLIT_PORT_UI
    ? `${window.location.protocol}//${window.location.hostname}:33003`
    : '';

// --- Time display ---------------------------------------------------------
// Everything is shown in Eastern time regardless of the viewer's device, so a
// phone in another timezone still reads the same clock as the host. The backend
// sends timezone-aware UTC ("...+00:00"), which is what makes this convert
// correctly -- a bare ISO string with no offset would be read as device-local.
export const DISPLAY_TZ = 'America/New_York';

const TIME_OPTS = { timeZone: DISPLAY_TZ, hour: '2-digit', minute: '2-digit', second: '2-digit' };
const DATETIME_OPTS = {
    timeZone: DISPLAY_TZ, year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
};

function toDate(ts) {
    if (!ts) return new Date();
    const d = ts instanceof Date ? ts : new Date(ts);
    return isNaN(d.getTime()) ? new Date() : d;
}

// "02:25:10 PM EST"
export function fmtTime(ts) {
    return toDate(ts).toLocaleTimeString('en-US', TIME_OPTS) + ' ' + tzAbbrev(ts);
}

// "Oct 7, 2026, 02:25:10 PM EST"
export function fmtDateTime(ts) {
    return toDate(ts).toLocaleString('en-US', DATETIME_OPTS) + ' ' + tzAbbrev(ts);
}

// EST in winter, EDT in summer.
export function tzAbbrev(ts) {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: DISPLAY_TZ, timeZoneName: 'short' })
        .formatToParts(toDate(ts));
    const name = parts.find(p => p.type === 'timeZoneName');
    return name ? name.value : 'ET';
}

// --- API helper -----------------------------------------------------------
// Several handlers used `if (response.ok) { ... }` with no else, so a failed
// request produced no UI change at all and the button looked dead. This throws
// with the server's detail so callers can report it.
export async function apiPost(path, body = null) {
    const response = await fetch(`${BACKEND_URL}${path}`, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body: body ? JSON.stringify(body) : undefined,
    });

    let payload = null;
    try { payload = await response.json(); } catch { /* empty or non-JSON body */ }

    if (!response.ok) {
        const detail = (payload && (payload.detail || payload.error)) || `HTTP ${response.status}`;
        throw new Error(detail);
    }
    return payload;
}

// Global state
export let state = {
    currentMissionId: null,
    // Which mission the live stream is scoped to (null = follow all)
    streamMissionId: null,
    missions: [],
    currentPlan: null,
    currentPlanStatus: null, // 'approved', 'edited', 'rejected'
    currentPlaybook: null, // Current playbook name
    eventSource: null,
    sidebarCollapsed: false,
    // Feed is pinned to the bottom until the user scrolls away from it.
    followFeed: true,
    newEntryCount: 0,
    currentSettings: {
        hitl_enabled: false,
        auto_approve_tools: ['view_raw_source', 'view_dom', 'check_network']
    }
};

// Logging utility
export function logToBackend(level, message, data = null) {
    const consoleMsg = data ? `${message} ${JSON.stringify(data)}` : message;
    switch (level) {
        case 'DEBUG': console.log(`🔍 ${consoleMsg}`); break;
        case 'INFO': console.info(`ℹ️ ${consoleMsg}`); break;
        case 'WARN': console.warn(`⚠️ ${consoleMsg}`); break;
        case 'ERROR': console.error(`❌ ${consoleMsg}`); break;
        default: console.log(consoleMsg);
    }

    fetch(`${BACKEND_URL}/api/log/frontend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            level: level,
            message: message,
            timestamp: new Date().toISOString(),
            data: data
        })
    }).catch(err => console.error('Failed to send log to backend:', err));
}
