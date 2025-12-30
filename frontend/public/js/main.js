// Main entry point - imports and initializes all modules
import { connectToSSE } from './sse.js';
import { initScrollDetection } from './feed.js';
import { loadMissionHistory, initMissionSelector, initNewMissionButton, updatePlaybookProgress } from './missions.js';
import { initEvidenceModal } from './evidence.js';
import { loadSettings, initSettingsModal } from './settings.js';
import { switchSidebarTab } from './plan.js';

// Export for use in SSE handler and inline onclick handlers
window.updatePlaybookProgress = updatePlaybookProgress;
window.switchSidebarTab = switchSidebarTab;

document.addEventListener('DOMContentLoaded', () => {
    // Initialize all modules
    connectToSSE();
    initScrollDetection();
    loadSettings();
    loadMissionHistory();
    initMissionSelector();
    initNewMissionButton();
    initEvidenceModal();
    initSettingsModal();

    console.log('✅ AI Hunter UI initialized');
});
