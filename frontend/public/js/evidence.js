import { BACKEND_URL, state } from './config.js';

export function initEvidenceModal() {
    document.getElementById('open-evidence-modal').addEventListener('click', async () => {
        document.getElementById('evidence-modal').classList.remove('hidden');
        await loadEvidence();
    });

    document.getElementById('close-evidence-modal').addEventListener('click', () => {
        document.getElementById('evidence-modal').classList.add('hidden');
    });
}

async function loadEvidence() {
    if (!state.currentMissionId) {
        document.getElementById('evidence-screenshots').innerHTML = '<p class="text-gray-400">No active mission</p>';
        document.getElementById('evidence-metadata').innerHTML = '<p class="text-gray-400">No active mission</p>';
        document.getElementById('evidence-findings').innerHTML = '<p class="text-gray-400">No active mission</p>';
        return;
    }

    try {
        const response = await fetch(`${BACKEND_URL}/api/missions/${state.currentMissionId}/artifacts`);
        if (!response.ok) throw new Error('Failed to load artifacts');

        const artifacts = await response.json();

        // Screenshots
        const screenshotsContainer = document.getElementById('evidence-screenshots');
        document.getElementById('screenshot-count').textContent = artifacts.screenshots.length;

        if (artifacts.screenshots.length === 0) {
            screenshotsContainer.innerHTML = '<p class="text-gray-400 col-span-full">No screenshots captured yet</p>';
        } else {
            screenshotsContainer.innerHTML = artifacts.screenshots.map(ss => `
                <div class="bg-gray-700 rounded-lg overflow-hidden hover:ring-2 hover:ring-blue-400 transition cursor-pointer"
                     onclick="window.open('${BACKEND_URL}${ss.url}', '_blank')">
                    <img src="${BACKEND_URL}${ss.url}" 
                         alt="${ss.action}" 
                         class="w-full h-32 object-cover"
                         onerror="this.src=''; this.alt='Failed to load'">
                    <div class="p-2">
                        <p class="text-xs text-gray-300 font-semibold truncate">${ss.action}</p>
                        <p class="text-xs text-gray-500">${ss.timestamp}</p>
                        ${ss.has_metadata ? '<p class="text-xs text-blue-400">📄 Has metadata</p>' : ''}
                    </div>
                </div>
            `).join('');
        }

        // Metadata
        const metadataContainer = document.getElementById('evidence-metadata');
        document.getElementById('metadata-count').textContent = artifacts.metadata.length;

        if (artifacts.metadata.length === 0) {
            metadataContainer.innerHTML = '<p class="text-gray-400">No metadata files</p>';
        } else {
            metadataContainer.innerHTML = artifacts.metadata.map(meta => `
                <div class="bg-gray-700 rounded p-3 hover:bg-gray-600 transition cursor-pointer flex justify-between items-center"
                     onclick="viewJSON('${BACKEND_URL}${meta.url}', '${meta.filename}')">
                    <span class="text-sm text-gray-300">📄 ${meta.filename}</span>
                    <span class="text-xs text-blue-400">View JSON</span>
                </div>
            `).join('');
        }

        // Findings
        const findingsContainer = document.getElementById('evidence-findings');
        document.getElementById('findings-count').textContent = artifacts.findings.length;

        if (artifacts.findings.length === 0) {
            findingsContainer.innerHTML = '<p class="text-gray-400">No findings saved</p>';
        } else {
            const byType = {};
            artifacts.findings.forEach(f => {
                if (!byType[f.type]) byType[f.type] = [];
                byType[f.type].push(f);
            });

            findingsContainer.innerHTML = Object.entries(byType).map(([type, findings]) => `
                <details open class="bg-gray-700 rounded p-3">
                    <summary class="cursor-pointer font-semibold text-gray-300 mb-2">
                        🔍 ${type} (${findings.length})
                    </summary>
                    <div class="space-y-1 pl-4">
                        ${findings.map(f => `
                            <div class="text-sm text-gray-400 hover:text-blue-400 cursor-pointer"
                                 onclick="viewJSON('${BACKEND_URL}${f.url}', '${f.filename}')">
                                📄 ${f.filename}
                            </div>
                        `).join('')}
                    </div>
                </details>
            `).join('');
        }

    } catch (error) {
        console.error('Failed to load evidence:', error);
        document.getElementById('evidence-screenshots').innerHTML = '<p class="text-red-400">Failed to load evidence</p>';
    }
}

window.viewJSON = function (url, filename) {
    fetch(url)
        .then(res => res.json())
        .then(data => {
            const jsonWindow = window.open('', '_blank');
            jsonWindow.document.write(`
                <!DOCTYPE html>
                <html>
                <head>
                    <title>${filename}</title>
                    <style>
                        body { 
                            background: #1a202c; 
                            color: #e2e8f0; 
                            font-family: monospace; 
                            padding: 20px; 
                        }
                        pre { 
                            background: #2d3748; 
                            padding: 20px; 
                            border-radius: 8px; 
                            overflow-x: auto; 
                        }
                    </style>
                </head>
                <body>
                    <h2>📄 ${filename}</h2>
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                </body>
                </html>
            `);
        })
        .catch(err => {
            console.error('Failed to load JSON:', err);
            alert('Failed to load JSON file');
        });
};
