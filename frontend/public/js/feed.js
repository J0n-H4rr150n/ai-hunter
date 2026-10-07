import { state, BACKEND_URL, fmtTime } from './config.js';

export function addToFeed(data) {
    const feedContent = document.getElementById('feed-content');
    const timestamp = fmtTime(data.timestamp);

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

    // Keep only last 50 entries
    while (feedContent.children.length > 50) {
        feedContent.removeChild(feedContent.firstChild);
    }

    // Stick to the bottom while the user is following along. If they have scrolled
    // up to read something, leave the viewport alone and count what they are
    // missing instead of yanking them back down.
    if (state.followFeed) {
        scrollFeedToBottom();
    } else {
        state.newEntryCount = (state.newEntryCount || 0) + 1;
        renderJumpPill();
    }
}

// How close to the bottom still counts as "following".
const FOLLOW_THRESHOLD_PX = 60;

function isNearBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_THRESHOLD_PX;
}

export function scrollFeedToBottom() {
    const feedContent = document.getElementById('feed-content');
    if (!feedContent) return;
    feedContent.scrollTop = feedContent.scrollHeight;
    state.followFeed = true;
    state.newEntryCount = 0;
    renderJumpPill();
}

function renderJumpPill() {
    const pill = document.getElementById('feed-jump');
    const label = document.getElementById('feed-jump-label');
    if (!pill || !label) return;

    if (state.followFeed) {
        pill.classList.add('hidden');
        pill.classList.remove('flex');
        return;
    }

    const n = state.newEntryCount || 0;
    label.textContent = n > 0
        ? `${n} new ${n === 1 ? 'entry' : 'entries'}`
        : 'Jump to latest';
    pill.classList.remove('hidden');
    pill.classList.add('flex');
}

// Called when the feed is rebuilt (switching mission sessions).
export function resetFeedScroll() {
    state.followFeed = true;
    state.newEntryCount = 0;
    renderJumpPill();
}

// Smart scroll detection
export function initScrollDetection() {
    const feedContent = document.getElementById('feed-content');
    const pill = document.getElementById('feed-jump');
    if (!feedContent) return;

    // Undebounced: the previous 100ms timer meant a scroll back to the bottom did
    // not re-attach until after the next event had already been counted as missed.
    feedContent.addEventListener('scroll', () => {
        const following = isNearBottom(feedContent);
        if (following === state.followFeed) return;

        state.followFeed = following;
        if (following) state.newEntryCount = 0;
        renderJumpPill();
    }, { passive: true });

    if (pill) {
        pill.addEventListener('click', () => scrollFeedToBottom());
    }

    // Content can reflow after images (screenshots) load; stay pinned if following.
    feedContent.addEventListener('load', (e) => {
        if (state.followFeed && e.target.tagName === 'IMG') scrollFeedToBottom();
    }, true);

    resetFeedScroll();
}
