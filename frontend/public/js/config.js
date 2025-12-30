// Backend connection
export const BACKEND_URL = window.location.hostname === 'localhost'
    ? 'http://localhost:33003'
    : `http://${window.location.hostname}:33003`;

// Global state
export let state = {
    currentMissionId: null,
    currentPlan: null,
    currentPlanStatus: null, // 'approved', 'edited', 'rejected'
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
