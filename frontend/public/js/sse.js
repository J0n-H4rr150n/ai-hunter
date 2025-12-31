import { BACKEND_URL, state, logToBackend } from './config.js';
import { addToFeed } from './feed.js';
import { showPlanApproval } from './plan.js';
import { showToolApproval } from './tools.js';
import { updateMissionStatus } from './missions.js';
import { enableControls, updateControlStatus } from './control.js';
import { showReplanPrompt } from './replan.js';

export function connectToSSE() {
    if (state.eventSource) {
        state.eventSource.close();
    }

    state.eventSource = new EventSource(`${BACKEND_URL}/api/events`);

    state.eventSource.onopen = () => {
        console.log('✅ Connected to backend (SSE)');
        updateStatus('connected', 'Connected');
    };

    state.eventSource.onerror = (error) => {
        console.error('❌ SSE connection error:', error);
        updateStatus('disconnected', 'Disconnected');
    };

    // Plan generated event
    state.eventSource.addEventListener('plan_generated', (event) => {
        logToBackend('INFO', 'Received plan_generated event');
        const data = JSON.parse(event.data);
        state.currentPlan = data.plan;
        state.currentMissionId = data.mission_id;
        showPlanApproval(data.plan, data.mission_id);
    });

    // Tool approval request
    state.eventSource.addEventListener('tool_approval_request', (event) => {
        const data = JSON.parse(event.data);
        console.log('🛠️ Tool approval request:', data);
        showToolApproval(data);
    });

    // Mission status
    state.eventSource.addEventListener('mission_status', (event) => {
        const data = JSON.parse(event.data);
        updateMissionStatus(data);
        if (data.status) {
            updateControlStatus(data.status);
        }
    });

    // Mission log with screenshots
    state.eventSource.addEventListener('mission_log', (event) => {
        const data = JSON.parse(event.data);

        if (data.mission_id && !state.currentMissionId) {
            state.currentMissionId = data.mission_id;
        }

        addToFeed({
            message: data.message,
            timestamp: data.timestamp,
            screenshot: data.screenshot
        });
    });

    // Mission started
    state.eventSource.addEventListener('mission_started', async (event) => {
        const data = JSON.parse(event.data);

        if (data.mission_id) {
            state.currentMissionId = data.mission_id;
            enableControls();
            updateControlStatus('running');

            // Load iterations for this mission
            const { loadIterations } = await import('./plan.js');
            loadIterations(data.mission_id);
        }

        addToFeed({
            message: data.message || `🚀 Mission ${data.mission_id} started`,
            timestamp: data.timestamp || new Date().toISOString()
        });
    });

    // Iteration started
    state.eventSource.addEventListener('iteration_started', async (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `🔄 Starting Iteration ${data.iteration_number}`,
            timestamp: data.timestamp
        });

        // Reload iterations to update sidebar
        if (state.currentMissionId) {
            const { loadIterations } = await import('./plan.js');
            loadIterations(state.currentMissionId);
        }
    });

    // Iteration completed
    state.eventSource.addEventListener('iteration_completed', async (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `✅ Iteration ${data.iteration_number} complete`,
            timestamp: data.timestamp
        });

        // Show replan prompt if summary provided
        if (data.summary) {
            showReplanPrompt(data);
        }

        // Reload iterations
        if (state.currentMissionId) {
            const { loadIterations } = await import('./plan.js');
            loadIterations(state.currentMissionId);
        }
    });

    // Agent thought
    state.eventSource.addEventListener('agent_thought', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `💭 ${data.thought}`,
            timestamp: data.timestamp
        });
    });

    // Agent action
    state.eventSource.addEventListener('agent_action', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `⚡ ${data.action}`,
            timestamp: data.timestamp
        });
    });

    // Mission complete
    state.eventSource.addEventListener('mission_complete', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `✅ ${data.message || data.summary || 'Mission complete'}`,
            timestamp: data.timestamp || new Date().toISOString()
        });
    });

    // Mission failed
    state.eventSource.addEventListener('mission_failed', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: `❌ Mission failed: ${data.error || 'Unknown error'}`,
            timestamp: data.timestamp || new Date().toISOString()
        });
    });

    // Agent idea/suggestion
    state.eventSource.addEventListener('agent_idea', async (event) => {
        const data = JSON.parse(event.data);
        const { addIdea } = await import('./plan.js');
        addIdea(data.idea || data);
        addToFeed({
            message: `💡 Idea: ${data.idea?.suggestion || data.suggestion || 'New suggestion added'}`,
            timestamp: data.timestamp || new Date().toISOString()
        });
    });

    // Playbook progress updates
    state.eventSource.addEventListener('playbook_progress', (event) => {
        const data = JSON.parse(event.data);
        console.log('📋 Playbook progress:', data);
        if (window.updatePlaybookProgress) {
            window.updatePlaybookProgress(data);
        }

        // Also add to feed for key milestones
        if (data.runbook_completed) {
            addToFeed({
                message: `✅ Completed runbook: ${data.runbook_completed}`,
                timestamp: data.timestamp || new Date().toISOString()
            });
        } else if (data.runbook_started) {
            addToFeed({
                message: `🔄 Started runbook: ${data.runbook_started}`,
                timestamp: data.timestamp || new Date().toISOString()
            });
        }
    });

    // Playbook started
    state.eventSource.addEventListener('playbook_started', (event) => {
        const data = JSON.parse(event.data);
        state.currentPlaybook = data.playbook_name;
        addToFeed({
            message: `🎯 Started playbook: ${data.playbook_name}`,
            timestamp: data.timestamp || new Date().toISOString()
        });
        if (window.updatePlaybookProgress) {
            window.updatePlaybookProgress(data);
        }
    });

    // Playbook completed
    state.eventSource.addEventListener('playbook_completed', (event) => {
        const data = JSON.parse(event.data);
        state.currentPlaybook = null;
        addToFeed({
            message: `🏁 Completed playbook: ${data.playbook_name}`,
            timestamp: data.timestamp || new Date().toISOString()
        });
        if (window.updatePlaybookProgress) {
            window.updatePlaybookProgress(null); // Clear progress
        }
    });

    // Playbook paused
    state.eventSource.addEventListener('playbook_paused', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: '⏸️  Playbook paused',
            timestamp: data.timestamp || new Date().toISOString()
        });
    });

    // Playbook resumed
    state.eventSource.addEventListener('playbook_resumed', (event) => {
        const data = JSON.parse(event.data);
        addToFeed({
            message: '▶️  Playbook resumed',
            timestamp: data.timestamp || new Date().toISOString()
        });
    });

    // Iteration plan generated
    state.eventSource.addEventListener('iteration_plan', async (event) => {
        const data = JSON.parse(event.data);
        console.log('📋 Iteration plan received:', data);

        // Display in Plan tab
        const { displayIterationPlan } = await import('./plan.js');
        displayIterationPlan(data.iteration_number, data.plan);

        addToFeed({
            message: `📋 Plan generated for Iteration ${data.iteration_number}`,
            timestamp: data.timestamp || new Date().toISOString()
        });
    });

    // Iteration status update
    state.eventSource.addEventListener('iteration_status', async (event) => {
        const data = JSON.parse(event.data);
        const { updateIterationStatus } = await import('./plan.js');
        updateIterationStatus(data.iteration_number, data.status);
    });
}

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
