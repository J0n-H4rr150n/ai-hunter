import { BACKEND_URL, state, apiPost } from './config.js';
import { addToFeed } from './feed.js';
import { renderMarkdown } from './md.js';

// Show replan prompt when iteration completes
export function showReplanPrompt(data) {
    const feedContent = document.getElementById('feed-content');
    const promptEntry = document.createElement('div');
    promptEntry.id = `replan-prompt-${data.mission_id}`;
    promptEntry.className = 'item';
    promptEntry.style.borderColor = 'var(--accent)';

    // The summary is Markdown written by the model; render it rather than dumping
    // the raw text with literal asterisks.
    promptEntry.innerHTML = `
        <div class="item-head">
            <strong>🔄 Continue with iteration ${data.next_iteration || (data.iteration_number + 1)}?</strong>
        </div>

        <h2 class="sect" style="margin-top:.6rem">Findings summary</h2>
        <div class="md">${renderMarkdown(data.summary)}</div>

        <div class="row" style="margin-top:.7rem">
            <button onclick="approveReplan(${data.mission_id})" class="btn good inline">
                ✅ Continue hunting
            </button>
            <button onclick="stopMission(${data.mission_id})" class="btn danger inline">
                ⏹️ Stop mission
            </button>
        </div>
    `;

    feedContent.appendChild(promptEntry);
    feedContent.scrollTop = feedContent.scrollHeight;
}

// Approve replanning - create next iteration
window.approveReplan = async function (missionId) {
    const button = document.querySelector(`#replan-prompt-${missionId} button`);
    if (button) { button.disabled = true; button.textContent = '⏳ Planning...'; }

    try {
        const result = await apiPost(`/api/missions/${missionId}/replan`);
        document.getElementById(`replan-prompt-${missionId}`)?.remove();
        addToFeed({
            message: `🔄 Continuing — iteration ${result?.iteration_number ?? 'next'} planned from findings...`,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to replan:', error);
        if (button) { button.disabled = false; button.textContent = '✅ Continue Hunting'; }
        addToFeed({
            message: `❌ Could not continue: ${error.message}`,
            timestamp: new Date().toISOString(),
            type: 'error'
        });
    }
};

// Stop mission
window.stopMission = async function (missionId) {
    try {
        await apiPost(`/api/missions/${missionId}/stop`);
        document.getElementById(`replan-prompt-${missionId}`)?.remove();
        addToFeed({
            message: '⏹️ Mission stopped by user',
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to stop mission:', error);
        addToFeed({
            message: `❌ Could not stop mission: ${error.message}`,
            timestamp: new Date().toISOString(),
            type: 'error'
        });
    }
};
