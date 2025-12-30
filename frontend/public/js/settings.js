import { BACKEND_URL, state } from './config.js';
import { addToFeed } from './feed.js';

export async function loadSettings() {
    try {
        const response = await fetch(`${BACKEND_URL}/api/settings`);
        if (response.ok) {
            state.currentSettings = await response.json();
            applySettingsToUI();
        }
    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

function applySettingsToUI() {
    document.getElementById('hitl-enabled').checked = state.currentSettings.hitl_enabled;
    document.getElementById('hitl-options').classList.toggle('hidden', !state.currentSettings.hitl_enabled);

    document.querySelectorAll('.auto-approve-tool').forEach(checkbox => {
        checkbox.checked = state.currentSettings.auto_approve_tools.includes(checkbox.value);
    });
}

export function initSettingsModal() {
    document.getElementById('open-settings-modal').addEventListener('click', () => {
        document.getElementById('settings-modal').classList.remove('hidden');
        applySettingsToUI();
    });

    document.getElementById('close-settings-modal').addEventListener('click', () => {
        document.getElementById('settings-modal').classList.add('hidden');
    });

    document.getElementById('hitl-enabled').addEventListener('change', (e) => {
        document.getElementById('hitl-options').classList.toggle('hidden', !e.target.checked);
    });

    document.getElementById('save-settings-btn').addEventListener('click', async () => {
        const hitlEnabled = document.getElementById('hitl-enabled').checked;
        const autoApproveTools = Array.from(document.querySelectorAll('.auto-approve-tool:checked'))
            .map(cb => cb.value);

        state.currentSettings = {
            hitl_enabled: hitlEnabled,
            auto_approve_tools: autoApproveTools
        };

        try {
            const response = await fetch(`${BACKEND_URL}/api/settings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(state.currentSettings)
            });

            if (response.ok) {
                document.getElementById('settings-modal').classList.add('hidden');
                addToFeed({
                    message: '✅ Settings saved successfully',
                    timestamp: new Date().toISOString()
                });
            }
        } catch (error) {
            console.error('Failed to save settings:', error);
            alert('Failed to save settings');
        }
    });
}
