import { state, BACKEND_URL } from './config.js';

export function addToFeed(data) {
    const feedContent = document.getElementById('feed-content');
    const timestamp = new Date(data.timestamp).toLocaleTimeString();

    const entry = document.createElement('div');
    entry.className = 'p-3 bg-gray-700 rounded-lg border-l-4 border-blue-500';

    let screenshotHTML = '';
    if (data.screenshot) {
        const imgSrc = data.screenshot.url
            ? `${BACKEND_URL}${data.screenshot.url}`
            : `data:image/png;base64,${data.screenshot.data}`;

        screenshotHTML = `
            <div class="mt-2 mb-2">
                <img src="${imgSrc}" 
                     alt="Screenshot" 
                     class="max-w-full h-auto rounded border border-gray-600 cursor-pointer hover:border-blue-400 transition"
                     onclick="window.open(this.src)"
                     onerror="console.error('Failed to load screenshot:', this.src); this.src=''; this.alt='[Screenshot failed to load]';"
                     title="Click to view full size - ${data.screenshot.path}">
                <p class="text-xs text-gray-500 mt-1">${data.screenshot.path}</p>
            </div>
        `;
    }

    entry.innerHTML = `
        <div class="flex justify-between items-start">
            <div class="flex-1">
                <p class="text-sm text-gray-300">${data.message}</p>
                ${screenshotHTML}
            </div>
            <span class="text-xs text-gray-500 ml-2">${timestamp}</span>
        </div>
    `;

    feedContent.appendChild(entry);

    // Smart auto-scroll - only if user hasn't manually scrolled
    if (!state.userHasScrolled) {
        feedContent.scrollTop = feedContent.scrollHeight;
    }

    // Keep only last 50 entries
    while (feedContent.children.length > 50) {
        feedContent.removeChild(feedContent.firstChild);
    }
}

// Smart scroll detection
export function initScrollDetection() {
    const feedContent = document.getElementById('feed-content');
    if (feedContent) {
        feedContent.addEventListener('scroll', () => {
            clearTimeout(state.scrollTimeout);

            state.scrollTimeout = setTimeout(() => {
                const isAtBottom = feedContent.scrollHeight - feedContent.scrollTop - feedContent.clientHeight < 50;
                state.userHasScrolled = !isAtBottom;
            }, 100);
        });
    }
}
