// Main entry point - imports and initializes all modules
import { connectToSSE } from './sse.js';
import { initScrollDetection } from './feed.js';
import { loadMissionHistory, initMissionSelector, initNewMissionButton, updatePlaybookProgress, initMissionRename } from './missions.js';
import { initEvidenceModal } from './evidence.js';
import { loadSettings, initSettingsModal } from './settings.js';
import { switchSidebarTab, restoreSidebarState } from './plan.js';
import { pausePlaybook, resumePlaybook, createCheckpoint, showCheckpoints, restoreCheckpoint, initCheckpointModal } from './checkpoints.js';
import { initMissionControl } from './control.js';  // Match the export name from control.js
import { initTabs, showTab } from './tabs.js';

// Export for use in SSE handler and inline onclick handlers
window.updatePlaybookProgress = updatePlaybookProgress;
window.switchSidebarTab = switchSidebarTab;
window.pausePlaybook = pausePlaybook;
window.resumePlaybook = resumePlaybook;
window.createCheckpoint = createCheckpoint;
window.showCheckpoints = showCheckpoints;
window.restoreCheckpoint = restoreCheckpoint;
window.showTab = showTab;

document.addEventListener('DOMContentLoaded', () => {
    // Initialize all modules
    connectToSSE();
    initScrollDetection();
    loadSettings();
    loadMissionHistory();
    initMissionSelector();
    initMissionRename();
    initNewMissionButton();
    initEvidenceModal();
    initSettingsModal();
    initCheckpointModal();
    initMissionControl();  // NEW: Initialize pause/stop/send controls
    initTabs();

    // Restore sidebar state from localStorage
    restoreSidebarState();

    console.log('✅ AI Hunter UI initialized');
});
