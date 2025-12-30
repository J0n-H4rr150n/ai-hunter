// Checkpoint management for playbook missions
import { BACKEND_URL, state } from './config.js';
import { addToFeed } from './feed.js';

// Pause playbook execution
export async function pausePlaybook() {
    if (!state.currentMissionId) {
        alert('No active mission');
        return;
    }

    try {
        const response = await fetch(`${BACKEND_URL}/api/missions/${state.currentMissionId}/pause-playbook`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('Failed to pause playbook');
        }

        addToFeed({
            message: '⏸️  Playbook paused - will pause after current step',
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to pause playbook:', error);
        alert('Failed to pause playbook');
    }
}

// Resume playbook execution
export async function resumePlaybook() {
    if (!state.currentMissionId) {
        alert('No active mission');
        return;
    }

    try {
        const response = await fetch(`${BACKEND_URL}/api/missions/${state.currentMissionId}/resume-playbook`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('Failed to resume playbook');
        }

        addToFeed({
            message: '▶️  Playbook resumed',
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to resume playbook:', error);
        alert('Failed to resume playbook');
    }
}

// Create a checkpoint
export async function createCheckpoint() {
    if (!state.currentMissionId) {
        alert('No active mission');
        return;
    }

    try {
        const response = await fetch(`${BACKEND_URL}/api/missions/${state.currentMissionId}/checkpoint`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('Failed to create checkpoint');
        }

        const data = await response.json();
        
        addToFeed({
            message: `💾 Checkpoint saved: ${data.checkpoint_name}`,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to create checkpoint:', error);
        alert('Failed to create checkpoint');
    }
}

// Show checkpoints modal
export async function showCheckpoints() {
    if (!state.currentMissionId) {
        alert('No active mission');
        return;
    }

    document.getElementById('checkpoints-modal').classList.remove('hidden');
    await loadCheckpoints();
}

// Load checkpoints list
async function loadCheckpoints() {
    const container = document.getElementById('checkpoints-list');
    container.innerHTML = '<div class="text-sm text-gray-400 text-center py-4">Loading...</div>';

    try {
        const response = await fetch(`${BACKEND_URL}/api/missions/${state.currentMissionId}/checkpoints`);
        
        if (!response.ok) {
            throw new Error('Failed to load checkpoints');
        }

        const checkpoints = await response.json();
        
        if (!checkpoints || checkpoints.length === 0) {
            container.innerHTML = '<div class="text-sm text-gray-400 text-center py-8">No checkpoints available</div>';
            return;
        }

        // Sort by creation time (newest first)
        checkpoints.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

        const html = checkpoints.map(checkpoint => {
            const created = new Date(checkpoint.created_at);
            const metadata = checkpoint.metadata || {};
            const value = checkpoint.value || {};
            
            return `
                <div class="bg-gray-700 p-4 rounded-lg border border-gray-600 hover:border-blue-500 transition">
                    <div class="flex justify-between items-start mb-2">
                        <div>
                            <h4 class="text-sm font-semibold text-blue-300">${checkpoint.key}</h4>
                            <p class="text-xs text-gray-400 mt-1">
                                ${created.toLocaleString()}
                            </p>
                        </div>
                        <button onclick="restoreCheckpoint('${checkpoint.key}')"
                            class="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded transition">
                            🔄 Restore
                        </button>
                    </div>
                    
                    ${value.current_stage !== undefined ? `
                        <div class="text-xs text-gray-400 space-y-1 mt-2">
                            <div>📍 Stage: ${value.current_stage}</div>
                            ${value.current_runbook ? `<div>🔧 Runbook: ${value.current_runbook}</div>` : ''}
                            ${value.completed_runbooks ? `<div>✅ Completed: ${value.completed_runbooks.length}</div>` : ''}
                            ${value.finding_count !== undefined ? `<div>🔍 Findings: ${value.finding_count}</div>` : ''}
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');

        container.innerHTML = html;
    } catch (error) {
        console.error('Failed to load checkpoints:', error);
        container.innerHTML = '<div class="text-sm text-red-400 text-center py-8">Failed to load checkpoints</div>';
    }
}

// Restore from checkpoint
export async function restoreCheckpoint(checkpointName) {
    if (!state.currentMissionId) {
        alert('No active mission');
        return;
    }

    if (!confirm(`Restore checkpoint: ${checkpointName}?\n\nThis will revert the playbook to this saved state.`)) {
        return;
    }

    try {
        const response = await fetch(
            `${BACKEND_URL}/api/missions/${state.currentMissionId}/restore?checkpoint_name=${encodeURIComponent(checkpointName)}`,
            { method: 'POST' }
        );

        if (!response.ok) {
            throw new Error('Failed to restore checkpoint');
        }

        const data = await response.json();
        
        addToFeed({
            message: `🔄 Checkpoint restored: ${checkpointName}`,
            timestamp: new Date().toISOString()
        });

        // Close modal
        document.getElementById('checkpoints-modal').classList.add('hidden');
    } catch (error) {
        console.error('Failed to restore checkpoint:', error);
        alert('Failed to restore checkpoint: ' + error.message);
    }
}

// Initialize checkpoint modal controls
export function initCheckpointModal() {
    document.getElementById('close-checkpoints-modal').addEventListener('click', () => {
        document.getElementById('checkpoints-modal').classList.add('hidden');
    });

    document.getElementById('close-checkpoints-btn').addEventListener('click', () => {
        document.getElementById('checkpoints-modal').classList.add('hidden');
    });

    // Close on outside click
    document.getElementById('checkpoints-modal').addEventListener('click', (e) => {
        if (e.target.id === 'checkpoints-modal') {
            document.getElementById('checkpoints-modal').classList.add('hidden');
        }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.getElementById('checkpoints-modal').classList.add('hidden');
        }
    });
}
