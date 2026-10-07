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

// Global state
export let state = {
    currentMissionId: null,
    currentPlan: null,
    currentPlanStatus: null, // 'approved', 'edited', 'rejected'
    currentPlaybook: null, // Current playbook name
    eventSource: null,
    sidebarCollapsed: false,
    userHasScrolled: false,
    scrollTimeout: null,
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
