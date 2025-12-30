// Backend connection
const BACKEND_URL = window.location.hostname === 'localhost'
    ? 'http://localhost:33003'
    : `http://${window.location.hostname}:33003`;

let currentMissionId = null;
let currentPlan = null;
let eventSource = null;

// Logging utility
function logToBackend(level, message, data = null) {
    // Log to console
    const consoleMsg = data ? `${message} ${JSON.stringify(data)}` : message;
    switch(level) {
        case 'DEBUG': console.log(`🔍 ${consoleMsg}`); break;
        case 'INFO': console.info(`ℹ️ ${consoleMsg}`); break;
        case 'WARN': console.warn(`⚠️ ${consoleMsg}`); break;
        case 'ERROR': console.error(`❌ ${consoleMsg}`); break;
        default: console.log(consoleMsg);
    }
    
    // Send to backend
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

// Connect to SSE
function connectToSSE() {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource(`${BACKEND_URL}/api/events`);

    eventSource.onopen = () => {
        console.log('✅ Connected to backend (SSE)');
        updateStatus('connected', 'Connected');
    };

    eventSource.onerror = (error) => {
        console.error('❌ SSE connection error:', error);
        updateStatus('disconnected', 'Disconnected');
        // EventSource automatically reconnects
    };

    // Listen for different event types
    eventSource.addEventListener('mission_started', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: data.message,
            timestamp: data.timestamp
        });
    });

    eventSource.addEventListener('mission_log', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: data.message,
            timestamp: data.timestamp
        });
    });

    eventSource.addEventListener('plan_generated', (event) => {
        const data = JSON.parse(event.data);
        currentPlan = data.plan;
        currentMissionId = data.mission_id;
        showPlanInFeed(data.plan, data.mission_id);
    });

    eventSource.addEventListener('mission_status', (event) => {
        const data = JSON.parse(event.data);
        updateMissionStatus(data);
    });

    eventSource.addEventListener('agent_thought', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `💭 ${data.thought}`,
            timestamp: data.timestamp
        });
    });

    eventSource.addEventListener('agent_action', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `⚡ ${data.action}`,
            timestamp: data.timestamp
        });
    });

    eventSource.addEventListener('mission_complete', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `✅ ${data.message || 'Mission complete'}`,
            timestamp: data.timestamp || new Date().toISOString()
        });
        handleMissionComplete(data);
    });

    eventSource.addEventListener('mission_failed', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `❌ Mission failed: ${data.error || 'Unknown error'}`,
            timestamp: data.timestamp || new Date().toISOString()
        });
    });
}

// Update connection status
function updateStatus(status, text) {
    const dot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');

    if (status === 'connected') {
        dot.className = 'w-3 h-3 bg-green-500 rounded-full animate-pulse';
    } else {
        dot.className = 'w-3 h-3 bg-gray-500 rounded-full';
    }

    statusText.textContent = text;
}

// Start a new mission
document.getElementById('start-mission-btn').addEventListener('click', async () => {
    const targetUrl = document.getElementById('target-url').value;
    const instructions = document.getElementById('instructions').value;

    if (!targetUrl) {
        alert('Please enter a target URL');
        return;
    }

    console.log('🚀 Starting mission:', { targetUrl, instructions });

    try {
        const response = await fetch(`${BACKEND_URL}/api/missions/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_url: targetUrl,
                instructions: instructions || null
            })
        });

        const data = await response.json();
        console.log('📬 Mission start response:', data);
        currentMissionId = data.mission_id;

        addToFeed({
            message: `🚀 Mission started: ${targetUrl}`,
            timestamp: new Date().toISOString()
        });

    } catch (error) {
        console.error('Failed to start mission:', error);
        alert('Failed to start mission. Is the backend running?');
    }
});

// Show plan approval UI - inline in feed
function showPlanApproval(plan, missionId) {
    logToBackend('INFO', 'Showing plan approval UI', { missionId: missionId });
    console.log('🎨 showPlanApproval called with:', { plan, missionId });
    currentPlan = plan;
    currentMissionId = missionId;
    
    const feedContent = document.getElementById('feed-content');
    console.log('📦 feedContent element:', feedContent);
    
    const planEntry = document.createElement('div');
    planEntry.id = `plan-approval-${missionId}`;
    planEntry.className = 'p-4 bg-yellow-900 bg-opacity-30 rounded-lg border-2 border-yellow-500';
    console.log('✨ Created plan entry element');
    
    planEntry.innerHTML = `
        <h3 class="text-lg font-semibold text-yellow-300 mb-3">⏸️ Plan Approval Required</h3>
        
        ${plan.rationale ? `
        <div class="mb-3">
            <p class="text-sm font-semibold text-gray-300 mb-1">🧠 Rationale:</p>
            <p class="text-sm text-gray-400">${plan.rationale}</p>
        </div>
        ` : ''}
        
        ${plan.steps ? `
        <div class="mb-3">
            <p class="text-sm font-semibold text-gray-300 mb-1">📝 Steps:</p>
            <pre class="text-xs text-gray-400 bg-gray-900 p-2 rounded overflow-x-auto">${JSON.stringify(plan.steps, null, 2)}</pre>
        </div>
        ` : ''}
        
        ${plan.budgets ? `
        <div class="mb-3">
            <p class="text-sm font-semibold text-gray-300 mb-1">💰 Budgets:</p>
            <div class="text-xs text-gray-400">
                ${Object.entries(plan.budgets).map(([tool, count]) => 
                    `<span class="inline-block mr-3">• ${tool}: ${count}</span>`
                ).join('')}
            </div>
        </div>
        ` : ''}
        
        <div class="flex space-x-2 mt-4">
            <button onclick="approvePlanInline(${missionId})" 
                class="flex-1 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold py-2 px-4 rounded transition">
                ✅ Approve
            </button>
            <button onclick="editPlanInline(${missionId})" 
                class="flex-1 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2 px-4 rounded transition">
                ✏️ Edit
            </button>
            <button onclick="rejectPlanInline(${missionId})" 
                class="flex-1 bg-red-600 hover:bg-red-700 text-white text-sm font-semibold py-2 px-4 rounded transition">
                ❌ Reject
            </button>
        </div>
    `;
    
    console.log('📝 Plan HTML generated, inserting into feed...');
    feedContent.insertBefore(planEntry, feedContent.firstChild);
    logToBackend('INFO', 'Plan inserted into feed successfully', { missionId: missionId });
    console.log('✅ Plan inserted into feed successfully');
}

// Approve plan inline
window.approvePlanInline = async function(missionId) {
    try {
        await fetch(`${BACKEND_URL}/api/missions/${missionId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan: currentPlan })
        });
        
        // Remove plan approval from feed
        const planEntry = document.getElementById(`plan-approval-${missionId}`);
        if (planEntry) planEntry.remove();
        
        addToFeed({
            message: '✅ Plan approved - Execution starting...',
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to approve plan:', error);
    }
};

// Reject plan inline
window.rejectPlanInline = async function(missionId) {
    try {
        await fetch(`${BACKEND_URL}/api/missions/${missionId}/reject`, {
            method: 'POST'
        });
        
        // Remove plan approval from feed
        const planEntry = document.getElementById(`plan-approval-${missionId}`);
        if (planEntry) planEntry.remove();
        
        addToFeed({
            message: '❌ Plan rejected - Mission aborted',
            timestamp: new Date().toISOString()
        });
        
        currentMissionId = null;
    } catch (error) {
        console.error('Failed to reject plan:', error);
    }
};

// Edit plan inline
window.editPlanInline = function(missionId) {
    const newRationale = prompt('Edit Rationale:', currentPlan.rationale);
    if (newRationale !== null) {
        currentPlan.rationale = newRationale;
    }
    
    // Refresh display
    const planEntry = document.getElementById(`plan-approval-${missionId}`);
    if (planEntry) planEntry.remove();
    showPlanApproval(currentPlan, missionId);
};

// OLD MODAL VERSION (keeping functions for now but they won't be displayed)
function showPlanApprovalOLD(plan, missionId) {
    currentPlan = plan;
    currentMissionId = missionId;

    const planDisplay = document.getElementById('plan-display');
    planDisplay.innerHTML = `
        <div class="bg-gray-700 p-4 rounded-lg">
            <h3 class="font-semibold text-blue-300 mb-2">🧠 Rationale</h3>
            <p class="text-gray-300">${plan.rationale || 'No rationale provided'}</p>
        </div>
        
        <div class="bg-gray-700 p-4 rounded-lg">
            <h3 class="font-semibold text-green-300 mb-2">📝 Execution Steps</h3>
            <pre class="text-gray-300 whitespace-pre-wrap">${plan.steps || 'No steps provided'}</pre>
        </div>
        
        ${plan.budgets ? `
        <div class="bg-gray-700 p-4 rounded-lg">
            <h3 class="font-semibold text-purple-300 mb-2">💰 Resource Budgets</h3>
            <ul class="text-gray-300 space-y-1">
                ${Object.entries(plan.budgets).map(([tool, count]) =>
        `<li>• ${tool}: ${count}</li>`
    ).join('')}
            </ul>
        </div>
        ` : ''}
    `;

    document.getElementById('plan-approval').classList.remove('hidden');
    document.getElementById('mission-control').classList.add('opacity-50', 'pointer-events-none');
}

// Approve plan
document.getElementById('approve-btn').addEventListener('click', async () => {
    if (!currentMissionId) return;

    try {
        await fetch(`${BACKEND_URL}/api/missions/${currentMissionId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan: currentPlan })
        });

        hidePlanApproval();
        addToFeed({
            message: '✅ Plan approved - Execution starting...',
            timestamp: new Date().toISOString()
        });

    } catch (error) {
        console.error('Failed to approve plan:', error);
    }
});

// Reject plan
document.getElementById('reject-btn').addEventListener('click', async () => {
    if (!currentMissionId) return;

    try {
        await fetch(`${BACKEND_URL}/api/missions/${currentMissionId}/reject`, {
            method: 'POST'
        });

        hidePlanApproval();
        addToFeed({
            message: '❌ Plan rejected - Mission aborted',
            timestamp: new Date().toISOString()
        });

        currentMissionId = null;

    } catch (error) {
        console.error('Failed to reject plan:', error);
    }
});

// Edit plan (simple version)
document.getElementById('edit-btn').addEventListener('click', () => {
    const newRationale = prompt('Edit Rationale:', currentPlan.rationale);
    if (newRationale !== null) {
        currentPlan.rationale = newRationale;
    }

    const newSteps = prompt('Edit Steps:', currentPlan.steps);
    if (newSteps !== null) {
        currentPlan.steps = newSteps;
    }

    // Refresh display
    showPlanApproval(currentPlan, currentMissionId);
});

// Hide plan approval
function hidePlanApproval() {
    document.getElementById('plan-approval').classList.add('hidden');
    document.getElementById('mission-control').classList.remove('opacity-50', 'pointer-events-none');
}

// Update mission status
function updateMissionStatus(data) {
    const statusContent = document.getElementById('status-content');
    statusContent.innerHTML = `
        <div class="space-y-2">
            <p><span class="font-semibold">Status:</span> ${data.status}</p>
            <p><span class="font-semibold">Target:</span> ${data.target_url}</p>
            ${data.current_action ? `<p><span class="font-semibold">Current Action:</span> ${data.current_action}</p>` : ''}
        </div>
    `;
}

// Add message to live feed
function addToFeed(data) {
    const feedContent = document.getElementById('feed-content');
    const timestamp = new Date(data.timestamp).toLocaleTimeString();

    const entry = document.createElement('div');
    entry.className = 'p-3 bg-gray-700 rounded-lg border-l-4 border-blue-500';
    entry.innerHTML = `
        <div class="flex justify-between items-start">
            <p class="text-sm text-gray-300">${data.message}</p>
            <span class="text-xs text-gray-500">${timestamp}</span>
        </div>
    `;

    feedContent.insertBefore(entry, feedContent.firstChild);

    // Keep only last 50 entries
    while (feedContent.children.length > 50) {
        feedContent.removeChild(feedContent.lastChild);
    }
}

// Handle mission completion
function handleMissionComplete(data) {
    addToFeed({
        message: `✅ Mission complete: ${data.summary}`,
        timestamp: new Date().toISOString()
    });
    currentMissionId = null;
}

// Initialize SSE connection when page loads
document.addEventListener('DOMContentLoaded', () => {
    connectToSSE();
});
