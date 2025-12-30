// Main entry point - imports and initializes all modules
import { connectToSSE } from './sse.js';
import { initScrollDetection } from './feed.js';
import { loadMissionHistory, initMissionSelector, initNewMissionButton } from './missions.js';
import { initEvidenceModal } from './evidence.js';
import { loadSettings, initSettingsModal } from './settings.js';

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
