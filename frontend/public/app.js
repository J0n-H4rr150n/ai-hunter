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
        logToBackend('INFO', 'Received plan_generated event');
        console.log('🎯 Received plan_generated event:', event);
        const data = JSON.parse(event.data);
        logToBackend('DEBUG', 'Parsed plan data', { missionId: data.mission_id, hasRationale: !!data.plan?.rationale });
        console.log('📋 Parsed plan data:', data);
        currentPlan = data.plan;
        currentMissionId = data.mission_id;
        console.log('Calling showPlanApproval with:', { plan: data.plan, missionId: data.mission_id });
        showPlanApproval(data.plan, data.mission_id);
    });

    eventSource.addEventListener('tool_approval_request', (event) => {
        const data = JSON.parse(event.data);
        console.log('🛠️ Tool approval request:', data);
        showToolApproval(data);
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

// Modal controls
document.getElementById('open-mission-modal').addEventListener('click', () => {
    document.getElementById('mission-modal').classList.remove('hidden');
});

document.getElementById('close-mission-modal').addEventListener('click', () => {
    document.getElementById('mission-modal').classList.add('hidden');
});

// Close modal when clicking outside
document.getElementById('mission-modal').addEventListener('click', (e) => {
    if (e.target.id === 'mission-modal') {
        document.getElementById('mission-modal').classList.add('hidden');
    }
});

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.getElementById('mission-modal').classList.add('hidden');
    }
});

// Start a new mission
document.getElementById('start-mission-btn').addEventListener('click', async () => {
    const targetUrl = document.getElementById('target-url').value;
    const instructions = document.getElementById('instructions').value;

    if (!targetUrl) {
        alert('Please enter a target URL');
        return;
    }

    console.log('🚀 Starting mission:', { targetUrl, instructions });

    // Close modal and clear form immediately
    document.getElementById('mission-modal').classList.add('hidden');
    const savedUrl = targetUrl;
    const savedInstructions = instructions;
    document.getElementById('target-url').value = '';
    document.getElementById('instructions').value = '';

    try {
        const response = await fetch(`${BACKEND_URL}/api/missions/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_url: savedUrl,
                instructions: savedInstructions || null
            })
        });

        const data = await response.json();
        console.log('📬 Mission start response:', data);
        currentMissionId = data.mission_id;
        // Backend will send mission_started event via SSE, no need to duplicate here

    } catch (error) {
        console.error('Failed to start mission:', error);
        addToFeed({
            message: '❌ Failed to start mission. Is the backend running?',
            timestamp: new Date().toISOString()
        });
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
            <ol class="text-sm text-gray-400 list-decimal list-inside space-y-1">
                ${plan.steps.map(step => {
                    if (typeof step === 'object') {
                        const action = step.action || '';
                        const target = step.target || step.element || '';
                        const description = step.description || step.summary || '';
                        return `<li class="ml-2">${action}${target ? ': ' + target : ''}${description ? ' - ' + description : ''}</li>`;
                    }
                    return `<li class="ml-2">${step}</li>`;
                }).join('')}
            </ol>
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
    // Append to end and auto-scroll
    feedContent.appendChild(planEntry);
    feedContent.scrollTop = feedContent.scrollHeight;
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

// Show tool approval request
function showToolApproval(data) {
    const { mission_id, tool_name, tool_inputs, context } = data;
    const feedContent = document.getElementById('feed-content');
    
    const toolEntry = document.createElement('div');
    const entryId = `tool-approval-${mission_id}-${Date.now()}`;
    toolEntry.id = entryId;
    toolEntry.className = 'p-4 bg-orange-900 bg-opacity-30 rounded-lg border-2 border-orange-500';
    
    // Format tool inputs for display
    const inputsHTML = Object.entries(tool_inputs).map(([key, value]) => {
        const displayValue = typeof value === 'string' && value.length > 100 
            ? value.substring(0, 100) + '...' 
            : JSON.stringify(value);
        return `<div class="flex"><span class="font-semibold text-gray-400 mr-2">${key}:</span><span class="text-gray-300">${displayValue}</span></div>`;
    }).join('');
    
    toolEntry.innerHTML = `
        <h3 class="text-lg font-semibold text-orange-300 mb-3">🛠️ Tool Approval Required</h3>
        
        <div class="mb-3">
            <p class="text-sm font-semibold text-gray-300 mb-1">Tool: <span class="text-orange-200">${tool_name}</span></p>
        </div>
        
        <div class="mb-3">
            <p class="text-sm font-semibold text-gray-300 mb-1">Inputs:</p>
            <div class="text-xs text-gray-400 bg-gray-900 p-2 rounded space-y-1">
                ${inputsHTML}
            </div>
        </div>
        
        ${context ? `
        <div class="mb-3">
            <p class="text-sm font-semibold text-gray-300 mb-1">Context:</p>
            <div class="text-xs text-gray-400 bg-gray-900 p-2 rounded overflow-auto max-h-32">
                <pre class="text-xs">${JSON.stringify(context, null, 2)}</pre>
            </div>
        </div>
        ` : ''}
        
        <div class="mb-3">
            <label class="block text-sm font-semibold text-gray-300 mb-1">Feedback (optional):</label>
            <textarea id="feedback-${entryId}" 
                      class="w-full px-2 py-1 bg-gray-800 border border-gray-600 rounded text-sm"
                      placeholder="Why are you approving/rejecting this?"
                      rows="2"></textarea>
        </div>
        
        <div class="flex space-x-2 mt-4">
            <button onclick="approveToolCall(${mission_id}, '${tool_name}', '${entryId}')" 
                class="flex-1 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold py-2 px-4 rounded transition">
                ✅ Approve
            </button>
            <button onclick="rejectToolCall(${mission_id}, '${tool_name}', '${entryId}')" 
                class="flex-1 bg-red-600 hover:bg-red-700 text-white text-sm font-semibold py-2 px-4 rounded transition">
                ❌ Reject
            </button>
        </div>
    `;
    
    // Store original data on the element for later use
    toolEntry.dataset.toolInputs = JSON.stringify(tool_inputs);
    toolEntry.dataset.context = JSON.stringify(context);
    
    feedContent.appendChild(toolEntry);
    feedContent.scrollTop = feedContent.scrollHeight;
}

// Approve tool call
window.approveToolCall = async function(missionId, toolName, entryId) {
    const toolEntry = document.getElementById(entryId);
    const feedback = document.getElementById(`feedback-${entryId}`)?.value || '';
    const toolInputs = JSON.parse(toolEntry.dataset.toolInputs);
    const context = JSON.parse(toolEntry.dataset.context);
    
    try {
        await fetch(`${BACKEND_URL}/api/tools/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mission_id: parseInt(missionId),
                tool_name: toolName,
                tool_inputs: toolInputs,
                context: context,
                approved: true,
                feedback: feedback
            })
        });
        
        // Remove approval request from feed
        if (toolEntry) toolEntry.remove();
        
        addToFeed({
            message: `✅ Approved tool: ${toolName}`,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to approve tool:', error);
    }
};

// Reject tool call
window.rejectToolCall = async function(missionId, toolName, entryId) {
    const toolEntry = document.getElementById(entryId);
    const feedback = document.getElementById(`feedback-${entryId}`)?.value || '';
    const toolInputs = JSON.parse(toolEntry.dataset.toolInputs);
    const context = JSON.parse(toolEntry.dataset.context);
    
    try {
        await fetch(`${BACKEND_URL}/api/tools/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mission_id: parseInt(missionId),
                tool_name: toolName,
                tool_inputs: toolInputs,
                context: context,
                approved: false,
                feedback: feedback
            })
        });
        
        // Remove approval request from feed
        if (toolEntry) toolEntry.remove();
        
        addToFeed({
            message: `❌ Rejected tool: ${toolName}${feedback ? ' - ' + feedback : ''}`,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to reject tool:', error);
    }
};

// Update mission status (removed old modal code)
function updateMissionStatus(data) {
    // Mission status section removed from UI, just log it
    console.log('Mission status update:', data);
}

// Add message to live feed
function addToFeed(data) {
    const feedContent = document.getElementById('feed-content');
    const timestamp = new Date(data.timestamp).toLocaleTimeString();

    const entry = document.createElement('div');
    entry.className = 'p-3 bg-gray-700 rounded-lg border-l-4 border-blue-500';
    
    let screenshotHTML = '';
    if (data.screenshot) {
        screenshotHTML = `
            <div class="mt-2 mb-2">
                <img src="data:image/png;base64,${data.screenshot.data}" 
                     alt="Screenshot" 
                     class="max-w-full h-auto rounded border border-gray-600 cursor-pointer hover:border-blue-400 transition"
                     onclick="window.open(this.src)"
                     title="Click to view full size - ${data.screenshot.path}">
                <p class="text-xs text-gray-500 mt-1">${data.screenshot.path}</p>
            </div>
        `;
    }
    
    entry.innerHTML = `
        <div class="flex justify-between items-start">
            <div class="flex-1">
                <p class="text-sm text-gray-300">${data.message}</p>
                ${screenshotHTML}
            </div>
            <span class="text-xs text-gray-500 ml-2">${timestamp}</span>
        </div>
    `;

    // Append to end (oldest to newest)
    feedContent.appendChild(entry);

    // Auto-scroll to bottom
    feedContent.scrollTop = feedContent.scrollHeight;

    // Keep only last 50 entries
    while (feedContent.children.length > 50) {
        feedContent.removeChild(feedContent.firstChild);
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
    loadSettings();
});

// Settings Management
let currentSettings = {
    hitl_enabled: false,
    auto_approve_tools: ['view_raw_source', 'view_dom', 'check_network']
};

async function loadSettings() {
    try {
        const response = await fetch(`${BACKEND_URL}/api/settings`);
        if (response.ok) {
            currentSettings = await response.json();
            applySettingsToUI();
        }
    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

function applySettingsToUI() {
    document.getElementById('hitl-enabled').checked = currentSettings.hitl_enabled;
    document.getElementById('hitl-options').classList.toggle('hidden', !currentSettings.hitl_enabled);
    
    document.querySelectorAll('.auto-approve-tool').forEach(checkbox => {
        checkbox.checked = currentSettings.auto_approve_tools.includes(checkbox.value);
    });
}

// Settings modal handlers
document.getElementById('open-settings-modal').addEventListener('click', () => {
    document.getElementById('settings-modal').classList.remove('hidden');
    applySettingsToUI();
});

document.getElementById('close-settings-modal').addEventListener('click', () => {
    document.getElementById('settings-modal').classList.add('hidden');
});

document.getElementById('hitl-enabled').addEventListener('change', (e) => {
    document.getElementById('hitl-options').classList.toggle('hidden', !e.target.checked);
});

document.getElementById('save-settings-btn').addEventListener('click', async () => {
    const hitlEnabled = document.getElementById('hitl-enabled').checked;
    const autoApproveTools = Array.from(document.querySelectorAll('.auto-approve-tool:checked'))
        .map(cb => cb.value);
    
    currentSettings = {
        hitl_enabled: hitlEnabled,
        auto_approve_tools: autoApproveTools
    };
    
    try {
        const response = await fetch(`${BACKEND_URL}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(currentSettings)
        });
        
        if (response.ok) {
            document.getElementById('settings-modal').classList.add('hidden');
            addToFeed({
                message: '✅ Settings saved successfully',
                timestamp: new Date().toISOString()
            });
        }
    } catch (error) {
        console.error('Failed to save settings:', error);
        alert('Failed to save settings');
    }
});
