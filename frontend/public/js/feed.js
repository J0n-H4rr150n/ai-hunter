import { state, BACKEND_URL, fmtTime } from './config.js';

export function addToFeed(data) {
    const feedContent = document.getElementById('feed-content');
    const timestamp = fmtTime(data.timestamp);

    // Accent the left edge by kind, so errors and successes are scannable.
    const KIND = { error: 'err', mission_failed: 'err', success: 'ok', mission_complete: 'ok' };
    const entry = document.createElement('div');
    entry.className = `item ${KIND[data.type] || ''}`.trim();

    let screenshotHTML = '';
    if (data.screenshot) {
        const imgSrc = data.screenshot.url
            ? `${BACKEND_URL}${data.screenshot.url}`
            : `data:image/png;base64,${data.screenshot.data}`;

        screenshotHTML = `
            <div style="margin:.4rem 0">
                <img src="${imgSrc}" alt="Screenshot" loading="lazy"
                     style="max-width:100%;border-radius:8px;border:1px solid var(--line);cursor:pointer"
                     onclick="window.open(this.src)"
                     onerror="this.replaceWith(Object.assign(document.createElement('p'),{className:'k',textContent:'[screenshot failed to load]'}))"
                     title="${data.screenshot.path || ''}">
                <p class="k">${data.screenshot.path || ''}</p>
            </div>`;
    }

    entry.innerHTML = `
        <div class="item-head">
            <div style="flex:1;min-width:0">${data.message ?? ''}</div>
            <span class="item-time">${timestamp}</span>
        </div>
        ${screenshotHTML}`;

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
        pill.classList.remove('show');
        return;
    }

    const n = state.newEntryCount || 0;
    label.textContent = n > 0
        ? `${n} new ${n === 1 ? 'entry' : 'entries'}`
        : 'Jump to latest';
    pill.classList.add('show');
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
