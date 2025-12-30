import { BACKEND_URL, state } from './config.js';
import { addToFeed } from './feed.js';

export function updateMissionStatus(data) {
    console.log('Mission status update:', data);
}

export async function loadMissionHistory() {
    try {
        const response = await fetch(`${BACKEND_URL}/api/missions`);
        if (!response.ok) return;

        const missions = await response.json();
        const selector = document.getElementById('mission-selector');

        missions.forEach(mission => {
            const option = document.createElement('option');
            option.value = mission.id;
            option.textContent = `Mission ${mission.id}: ${mission.target_url.substring(0, 30)}... (${mission.status})`;
            selector.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load mission history:', error);
    }
}

export function initMissionSelector() {
    document.getElementById('mission-selector').addEventListener('change', async (e) => {
        if (e.target.value === 'live') {
            state.currentMissionId = null;
            document.getElementById('feed-content').innerHTML = '';
            return;
        }

        const missionId = parseInt(e.target.value);
        await loadHistoricMission(missionId);
    });
}

async function loadHistoricMission(missionId) {
    try {
        console.log('Loading historic mission:', missionId);
        addToFeed({
            message: `📜 Viewing historic mission ${missionId}`,
            timestamp: new Date().toISOString()
        });
    } catch (error) {
        console.error('Failed to load historic mission:', error);
    }
}

// Start new mission
export function initNewMissionButton() {
    // Modal controls
    document.getElementById('open-mission-modal').addEventListener('click', () => {
        document.getElementById('mission-modal').classList.remove('hidden');
    });

    document.getElementById('close-mission-modal').addEventListener('click', () => {
        document.getElementById('mission-modal').classList.add('hidden');
    });

    document.getElementById('mission-modal').addEventListener('click', (e) => {
        if (e.target.id === 'mission-modal') {
            document.getElementById('mission-modal').classList.add('hidden');
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.getElementById('mission-modal').classList.add('hidden');
        }
    });

    document.getElementById('start-mission-btn').addEventListener('click', async () => {
        const targetUrl = document.getElementById('target-url').value;
        const instructions = document.getElementById('instructions').value;

        if (!targetUrl) {
            alert('Please enter a target URL');
            return;
        }

        document.getElementById('mission-modal').classList.add('hidden');
        const savedUrl = targetUrl;
        const savedInstructions = instructions;
        document.getElementById('target-url').value = '';
        document.getElementById('instructions').value = '';

        try {
            const response = await fetch(`${BACKEND_URL}/api/missions/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target_url: savedUrl,
                    instructions: savedInstructions || null
                })
            });

            const data = await response.json();
            state.currentMissionId = data.mission_id;
        } catch (error) {
            console.error('Failed to start mission:', error);
            addToFeed({
                message: '❌ Failed to start mission. Is the backend running?',
                timestamp: new Date().toISOString()
            });
        }
    });
}
