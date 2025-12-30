import { BACKEND_URL, state } from './config.js';
import { addToFeed } from './feed.js';

export function showToolApproval(data) {
    const { mission_id, tool_name, tool_inputs, context } = data;
    const feedContent = document.getElementById('feed-content');

    const toolEntry = document.createElement('div');
    const entryId = `tool-approval-${mission_id}-${Date.now()}`;
    toolEntry.id = entryId;
    toolEntry.className = 'p-4 bg-orange-900 bg-opacity-30 rounded-lg border-2 border-orange-500';

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

    toolEntry.dataset.toolInputs = JSON.stringify(tool_inputs);
    toolEntry.dataset.context = JSON.stringify(context);

    feedContent.appendChild(toolEntry);
    feedContent.scrollTop = feedContent.scrollHeight;
}

window.approveToolCall = async function (missionId, toolName, entryId) {
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

        toolEntry?.remove();

        addToFeed({
            message: `✅ Approved tool: ${toolName}`,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to approve tool:', error);
    }
};

window.rejectToolCall = async function (missionId, toolName, entryId) {
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

        toolEntry?.remove();

        addToFeed({
            message: `❌ Rejected tool: ${toolName}${feedback ? ' - ' + feedback : ''}`,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to reject tool:', error);
    }
};
