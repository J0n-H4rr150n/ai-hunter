import { BACKEND_URL, state, logToBackend } from './config.js';
import { addToFeed } from './feed.js';

export function switchSidebarTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.sidebar-tab').forEach(tab => {
        tab.classList.remove('active');
        tab.classList.remove('border-blue-400', 'text-blue-300');
        tab.classList.add('text-gray-400');
    });

    const activeTab = document.getElementById(`tab-${tabName}`);
    activeTab.classList.add('active', 'border-blue-400', 'text-blue-300');
    activeTab.classList.remove('text-gray-400');

    // Switch content
    document.querySelectorAll('.sidebar-tab-content').forEach(content => {
        content.classList.add('hidden');
    });

    document.getElementById(`${tabName}-tab-content`).classList.remove('hidden');
}

export function addIdea(idea) {
    const container = document.getElementById('ideas-container');

    // Initialize if first idea
    if (container.textContent.includes('No ideas')) {
        container.innerHTML = '<div class="space-y-2"></div>';
    }

    const ideaElement = document.createElement('div');
    ideaElement.className = 'p-3 bg-gray-700 rounded-lg border-l-2 border-yellow-500 hover:bg-gray-600 transition';
    ideaElement.innerHTML = `
        <div class="flex items-start space-x-2">
            <span class="text-yellow-400 text-lg">💡</span>
            <div class="flex-1">
                <p class="text-xs text-gray-300">${idea.suggestion || idea.text || idea}</p>
                ${idea.rationale ? `<p class="text-xs text-gray-500 mt-1">${idea.rationale}</p>` : ''}
                <p class="text-xs text-gray-500 mt-1">${new Date().toLocaleTimeString()}</p>
            </div>
        </div>
    `;

    container.firstChild.appendChild(ideaElement);
}

export function togglePlanSidebar() {
    const sidebar = document.getElementById('plan-sidebar');
    const toggle = document.getElementById('sidebar-toggle');

    state.sidebarCollapsed = !state.sidebarCollapsed;

    if (state.sidebarCollapsed) {
        sidebar.classList.add('w-12');
        sidebar.classList.remove('w-80');
        document.getElementById('sidebar-content').classList.add('hidden');
        toggle.textContent = '▶';
    } else {
        sidebar.classList.remove('w-12');
        sidebar.classList.add('w-80');
        document.getElementById('sidebar-content').classList.remove('hidden');
        toggle.textContent = '◀';
    }
}

export function updatePlanSidebar(plan, status) {
    const container = document.getElementById('plan-status-container');

    let statusIcon = '⏳', statusColor = 'text-gray-400', statusText = 'Pending';

    if (status === 'approved') {
        statusIcon = '✅';
        statusColor = 'text-green-400';
        statusText = 'Approved';
    } else if (status === 'edited') {
        statusIcon = '🟠';
        statusColor = 'text-orange-400';
        statusText = 'Edited & Approved';
    } else if (status === 'rejected') {
        statusIcon = '❌';
        statusColor = 'text-red-400';
        statusText = 'Rejected';
    }

    let html = `
        <div class="mb-4 pb-4 border-b border-gray-700">
            <div class="flex items-center justify-between mb-2">
                <span class="text-xs font-semibold ${statusColor}">${statusIcon} ${statusText}</span>
                <span class="text-xs text-gray-500">${new Date().toLocaleTimeString()}</span>
            </div>
        </div>
    `;

    if (plan.rationale) {
        html += `
            <div class="mb-4">
                <p class="text-xs font-semibold text-gray-400 mb-1">💭 Rationale:</p>
                <p class="text-xs text-gray-300">${plan.rationale}</p>
            </div>
        `;
    }

    if (plan.steps && plan.steps.length > 0) {
        html += `<div class="mb-4">
                <p class="text-xs font-semibold text-gray-400 mb-2">📝 Steps:</p>
                <ol class="space-y-2">`;

        plan.steps.forEach((step, index) => {
            let stepText = '';
            if (typeof step === 'object') {
                const action = step.action || '';
                const target = step.target || step.element || '';
                const description = step.description || step.summary || '';
                stepText = `${action}${target ? ': ' + target : ''}${description ? ' - ' + description : ''}`;
            } else {
                stepText = step;
            }

            html += `
                <li class="text-xs text-gray-300 pl-4 border-l-2 border-gray-600 hover:border-blue-500 transition">
                    <span class="text-gray-500">${index + 1}.</span> ${stepText}
                </li>
            `;
        });

        html += `</ol></div>`;
    }

    if (plan.budgets) {
        html += `<div>
                <p class="text-xs font-semibold text-gray-400 mb-2">💰 Budgets:</p>
                <div class="flex flex-wrap gap-2">`;

        Object.entries(plan.budgets).forEach(([tool, count]) => {
            html += `<span class="text-xs bg-gray-700 px-2 py-1 rounded">${tool}: ${count}</span>`;
        });

        html += `</div></div>`;
    }

    container.innerHTML = html;
}

// New iteration-based sidebar functions
export function updateIterationsSidebar(iterations, currentIterationNum) {
    const container = document.getElementById('plan-status-container');

    if (!iterations || iterations.length === 0) {
        container.innerHTML = '<p class="text-sm text-gray-400 text-center py-8">No iterations yet</p>';
        return;
    }

    let html = '';

    iterations.forEach(iteration => {
        const isActive = iteration.iteration_number === currentIterationNum;
        const isCompleted = iteration.status === 'completed';
        const isFailed = iteration.status === 'failed';
        const isInProgress = iteration.status === 'in_progress';

        // Status icon and color
        let statusIcon = '⏳', statusColor = 'text-gray-400', statusText = 'Pending';
        if (isCompleted) {
            statusIcon = '✅';
            statusColor = 'text-green-400';
            statusText = 'Completed';
        }
        if (isFailed) {
            statusIcon = '❌';
            statusColor = 'text-red-400';
            statusText = 'Failed';
        }
        if (isInProgress) {
            statusIcon = '▶️';
            statusColor = 'text-blue-400';
            statusText = 'In Progress';
        }

        html += `
            <details ${isActive ? 'open' : ''} class="mb-3 bg-gray-700 rounded-lg border ${isActive ? 'border-blue-500' : 'border-gray-600'}">
                <summary class="cursor-pointer p-3 font-semibold text-sm hover:bg-gray-650 flex items-center justify-between">
                    <span>
                        <span class="${statusColor}">${statusIcon}</span>
                        <span class="ml-2">Iteration ${iteration.iteration_number}</span>
                    </span>
                    <span class="text-xs ${statusColor}">${statusText}</span>
                </summary>
                
                <div class="p-3 border-t border-gray-600 space-y-3">
                    ${iteration.plan?.rationale ? `
                        <div>
                            <p class="text-xs font-semibold text-gray-400 mb-1">💭 Goal:</p>
                            <p class="text-xs text-gray-300">${iteration.plan.rationale}</p>
                        </div>
                    ` : ''}
                    
                    ${iteration.plan?.steps && iteration.plan.steps.length > 0 ? `
                        <div>
                            <p class="text-xs font-semibold text-gray-400 mb-2">📝 Steps (${iteration.plan.steps.length}):</p>
                            <ol class="space-y-1 text-xs text-gray-300">
                                ${iteration.plan.steps.slice(0, 5).map((step, idx) => {
            const stepText = typeof step === 'object'
                ? `${step.action || ''}${step.target ? ': ' + step.target : ''}`
                : step;
            return `<li class="pl-4 border-l-2 border-gray-600">
                                        <span class="text-gray-500">${idx + 1}.</span> ${stepText}
                                    </li>`;
        }).join('')}
                                ${iteration.plan.steps.length > 5 ? `
                                    <li class="text-gray-500 text-xs pl-4">... and ${iteration.plan.steps.length - 5} more steps</li>
                                ` : ''}
                            </oli>
                        </div>
                    ` : ''}
                    
                    ${iteration.plan?.budgets ? `
                        <div>
                            <p class="text-xs font-semibold text-gray-400 mb-2">💰 Budgets:</p>
                            <div class="flex flex-wrap gap-1">
                                ${Object.entries(iteration.plan.budgets).map(([tool, count]) =>
            `<span class="text-xs bg-gray-800 px-2 py-1 rounded">${tool}: ${count}</span>`
        ).join('')}
                            </div>
                        </div>
                    ` : ''}
                    
                    ${iteration.findings_summary && isCompleted ? `
                        <div class="bg-gray-800 p-2 rounded border border-yellow-600">
                            <p class="text-xs font-semibold text-yellow-400 mb-1">📊 Summary:</p>
                            <p class="text-xs text-gray-300 whitespace-pre-wrap">${iteration.findings_summary}</p>
                        </div>
                    ` : ''}
                </div>
            </details>
        `;
    });

    container.innerHTML = html;
}

// Load iterations for current mission
export async function loadIterations(missionId) {
    if (!missionId) return;

    try {
        const response = await fetch(`${BACKEND_URL}/api/missions/${missionId}/iterations`);
        if (!response.ok) return;

        const iterations = await response.json();

        // Find current iteration (last in_progress or pending)
        const currentIteration = iterations.find(i => i.status === 'in_progress')
            || iterations[iterations.length - 1];

        updateIterationsSidebar(iterations, currentIteration?.iteration_number || 1);
    } catch (error) {
        console.error('Failed to load iterations:', error);
    }
}

export function showPlanApproval(plan, missionId) {
    logToBackend('INFO', 'Showing plan approval UI', { missionId });
    state.currentPlan = plan;
    state.currentMissionId = missionId;

    const feedContent = document.getElementById('feed-content');
    const planEntry = document.createElement('div');
    planEntry.id = `plan-approval-${missionId}`;
    planEntry.className = 'p-4 bg-yellow-900 bg-opacity-30 rounded-lg border-2 border-yellow-500';

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

    feedContent.appendChild(planEntry);
    feedContent.scrollTop = feedContent.scrollHeight;
}

window.approvePlanInline = async function (missionId) {
    try {
        await fetch(`${BACKEND_URL}/api/missions/${missionId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan: state.currentPlan })
        });

        state.currentPlanStatus = state.currentPlanStatus === 'edited' ? 'edited' : 'approved';
        updatePlanSidebar(state.currentPlan, state.currentPlanStatus);

        document.getElementById(`plan-approval-${missionId}`)?.remove();

        addToFeed({
            message: '✅ Plan approved - Execution starting...',
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to approve plan:', error);
    }
};

window.rejectPlanInline = async function (missionId) {
    try {
        await fetch(`${BACKEND_URL}/api/missions/${missionId}/reject`, {
            method: 'POST'
        });

        state.currentPlanStatus = 'rejected';
        updatePlanSidebar(state.currentPlan, 'rejected');

        document.getElementById(`plan-approval-${missionId}`)?.remove();

        addToFeed({
            message: '❌ Plan rejected - Mission aborted',
            timestamp: new Date().toISOString()
        });

        state.currentMissionId = null;
    } catch (error) {
        console.error('Failed to reject plan:', error);
    }
};

window.editPlanInline = function (missionId) {
    const newRationale = prompt('Edit Rationale:', state.currentPlan.rationale);
    if (newRationale !== null) {
        state.currentPlan.rationale = newRationale;
        state.currentPlanStatus = 'edited';
    }

    document.getElementById(`plan-approval-${missionId}`)?.remove();
    showPlanApproval(state.currentPlan, missionId);
};

// Export for window globals
window.togglePlanSidebar = togglePlanSidebar;
window.switchSidebarTab = switchSidebarTab;
