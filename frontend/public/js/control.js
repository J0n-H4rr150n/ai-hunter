import { BACKEND_URL, state } from './config.js';
import { addToFeed } from './feed.js';

// Initialize mission control buttons and chat
export function initMissionControl() {
    const pauseBtn = document.getElementById('pause-btn');
    const resumeBtn = document.getElementById('resume-btn');
    const stopBtn = document.getElementById('stop-btn');
    const sendBtn = document.getElementById('send-message-btn');
    const messageInput = document.getElementById('user-message-input');
    const statusText = document.getElementById('mission-control-status'); // May not exist

    // Pause mission
    pauseBtn.addEventListener('click', async () => {
        if (!state.currentMissionId) return;

        try {
            await fetch(`${BACKEND_URL}/api/missions/${state.currentMissionId}/pause`, {
                method: 'POST'
            });

            pauseBtn.disabled = true;
            if (statusText) statusText.textContent = 'Pausing...';

            addToFeed({
                message: '⏸️ Pause requested - agent will pause after current task completes',
                timestamp: new Date().toISOString()
            });
        } catch (error) {
            console.error('Failed to pause mission:', error);
        }
    });

    // Resume mission
    resumeBtn.addEventListener('click', async () => {
        if (!state.currentMissionId) return;

        try {
            await fetch(`${BACKEND_URL}/api/missions/${state.currentMissionId}/resume`, {
                method: 'POST'
            });

            resumeBtn.classList.add('hidden');
            pauseBtn.classList.remove('hidden');
            if (statusText) statusText.textContent = 'Running';

            addToFeed({
                message: '▶️ Mission resumed',
                timestamp: new Date().toISOString()
            });
        } catch (error) {
            console.error('Failed to resume mission:', error);
        }
    });

    // Stop mission
    stopBtn.addEventListener('click', async () => {
        if (!state.currentMissionId) return;

        if (!confirm('⚠️ FORCE STOP: This will immediately terminate all running tasks. Are you sure?')) {
            return;
        }

        try {
            await fetch(`${BACKEND_URL}/api/missions/${state.currentMissionId}/stop`, {
                method: 'POST'
            });

            disableControls();
            if (statusText) statusText.textContent = 'Stopped';

            addToFeed({
                message: '⏹️ Mission force-stopped by user (all tasks terminated)',
                timestamp: new Date().toISOString()
            });

            state.currentMissionId = null;
        } catch (error) {
            console.error('Failed to stop mission:', error);
        }
    });

    // Send message to agent
    const sendMessage = async () => {
        const message = messageInput.value.trim();
        if (!message || !state.currentMissionId) return;

        try {
            await fetch(`${BACKEND_URL}/api/missions/${state.currentMissionId}/message`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });

            addToFeed({
                message: `💬 You: ${message}`,
                timestamp: new Date().toISOString()
            });

            addToFeed({
                message: '⏸️ Agent will pause after current task to read your message',
                timestamp: new Date().toISOString()
            });

            messageInput.value = '';
        } catch (error) {
            console.error('Failed to send message:', error);
        }
    };

    sendBtn.addEventListener('click', sendMessage);

    messageInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });
}

// Enable controls when mission starts
export function enableControls() {
    document.getElementById('pause-btn').disabled = false;
    document.getElementById('stop-btn').disabled = false;
    document.getElementById('user-message-input').disabled = false;
    document.getElementById('send-message-btn').disabled = false;
    const statusText = document.getElementById('mission-control-status');
    if (statusText) statusText.textContent = 'Running';
}

// Disable controls when no mission
export function disableControls() {
    document.getElementById('pause-btn').disabled = true;
    document.getElementById('pause-btn').classList.remove('hidden');
    document.getElementById('resume-btn').disabled = true;
    document.getElementById('resume-btn').classList.add('hidden');
    document.getElementById('stop-btn').disabled = true;
    document.getElementById('user-message-input').disabled = true;
    document.getElementById('send-message-btn').disabled = true;
    const statusText = document.getElementById('mission-control-status');
    if (statusText) statusText.textContent = 'No mission';
}

// Update status from SSE events
export function updateControlStatus(status) {
    const statusText = document.getElementById('mission-control-status');
    const pauseBtn = document.getElementById('pause-btn');
    const resumeBtn = document.getElementById('resume-btn');

    switch (status) {
        case 'running':
            if (statusText) statusText.textContent = 'Running';
            pauseBtn.classList.remove('hidden');
            resumeBtn.classList.add('hidden');
            break;
        case 'paused':
            if (statusText) statusText.textContent = 'Paused';
            pauseBtn.classList.add('hidden');
            pauseBtn.disabled = false;
            resumeBtn.classList.remove('hidden');
            resumeBtn.disabled = false;
            break;
        case 'pausing':
            if (statusText) statusText.textContent = 'Pausing...';
            pauseBtn.disabled = true;
            break;
        case 'waiting_for_user':
            if (statusText) statusText.textContent = 'Waiting for you';
            pauseBtn.classList.add('hidden');
            resumeBtn.classList.add('hidden');
            break;
        case 'stopped':
        case 'complete':
            disableControls();
            if (statusText) statusText.textContent = status === 'complete' ? 'Complete' : 'Stopped';
            break;
    }
}
