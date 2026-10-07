import { BACKEND_URL, state, apiPost } from './config.js';
import { addToFeed } from './feed.js';

// Show replan prompt when iteration completes
export function showReplanPrompt(data) {
    const feedContent = document.getElementById('feed-content');
    const promptEntry = document.createElement('div');
    promptEntry.id = `replan-prompt-${data.mission_id}`;
    promptEntry.className = 'p-4 bg-blue-900 bg-opacity-30 rounded-lg border-2 border-blue-500';

    promptEntry.innerHTML = `
        <h3 class="text-lg font-semibold text-blue-300 mb-3">
            🔄 Continue with Iteration ${data.next_iteration || (data.iteration_number + 1)}?
        </h3>
        
        <div class="mb-3 bg-gray-800 p-3 rounded">
            <p class="text-sm font-semibold text-gray-300 mb-2">📊 Findings Summary:</p>
            <p class="text-xs text-gray-400 whitespace-pre-wrap">${data.summary}</p>
        </div>
        
        <div class="flex space-x-2">
            <button onclick="approveReplan(${data.mission_id})" 
                class="flex-1 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold py-2 px-4 rounded transition">
                ✅ Continue Hunting
            </button>
            <button onclick="stopMission(${data.mission_id})" 
                class="flex-1 bg-red-600 hover:bg-red-700 text-white text-sm font-semibold py-2 px-4 rounded transition">
                ⏹️ Stop Mission
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
