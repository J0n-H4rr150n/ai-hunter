import { state, BACKEND_URL, fmtTime } from './config.js';
import { openDetail } from './tabs.js';
import { renderMarkdown, escapeHtml } from './md.js';

// Every rendered entry keeps the event that produced it, so a line in the feed
// can be opened to see what was actually behind it. Previously only the one-line
// message survived rendering and the rest of the payload was discarded.
const entryEvents = new WeakMap();

// Fields that are just envelope; their absence is what makes an event "expandable".
const ENVELOPE = new Set(['type', 'mission_id', 'message', 'timestamp', '_log_id']);

function hasDetail(data) {
    // A key present but null (replay passes screenshot: null) is not detail.
    return Object.entries(data || {}).some(
        ([k, v]) => !ENVELOPE.has(k) && v !== null && v !== undefined && v !== '');
}

/**
 * Render a feed message.
 *
 * Three cases, because they genuinely differ:
 *  - the agent emits deliberate HTML for some entries (the <details> tech-stack
 *    block), which must pass through intact;
 *  - model-written text is Markdown and multi-line, and was previously collapsed
 *    into one run-on line;
 *  - everything else is plain text.
 *
 * Only the first case is inserted as markup, and only when it is recognisably
 * one of ours. The rest is escaped — these strings are written by a model that
 * has just read an attacker-controlled page.
 */
const OURS = /^\s*<(details|div|span|p|b|table)\b/i;

function renderMessage(message) {
    const text = String(message ?? '');
    if (OURS.test(text)) return text;
    if (text.includes('\n') || /\*\*|^[-*]\s|^\d+\.\s/m.test(text)) {
        return `<div class="md">${renderMarkdown(text)}</div>`;
    }
    return escapeHtml(text);
}

// Structured events carry their content in a named field rather than in
// `message`, so they rendered as a bare type name — "iteration_completed" with
// the summary it was carrying nowhere in sight.
const CONTENT_FIELD = ['summary', 'error', 'rationale', 'name', 'status'];

function headline(data) {
    // The stored message for a structured event is just its type name — that is
    // the fallback the event bus writes when an event has no prose of its own —
    // so treat it as absent and prefer the field that holds the real content.
    const message = data.message && data.message !== data.type ? data.message : null;
    if (message) return message;

    for (const key of CONTENT_FIELD) {
        if (data[key]) return `**${data.type}**\n\n${data[key]}`;
    }
    return data.type || '';
}

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

    const expandable = hasDetail(data);
    entry.innerHTML = `
        <div class="item-head">
            <div style="flex:1;min-width:0">${renderMessage(headline(data))}</div>
            <span class="item-time">${timestamp}</span>
        </div>
        ${screenshotHTML}
        ${expandable ? '<button type="button" class="pill accent feed-more">details</button>' : ''}`;

    entry.classList.add('clickable');
    entryEvents.set(entry, data);

    const expand = () => {
        const event = entryEvents.get(entry);
        if (!event) return;
        openDetail(event.type || 'event', event, {
            source: entry,
            skip: ['screenshot'],
            extra: event.screenshot?.url
                ? `<img src="${BACKEND_URL}${event.screenshot.url}" alt="">`
                : '',
        });
    };

    // The pill always expands, whatever else the card contains. An entry built
    // around a screenshot is mostly image, and clicking the image opens the image
    // — without an explicit control those entries could not be expanded at all.
    entry.querySelector('.feed-more')?.addEventListener('click', (e) => {
        e.stopPropagation();
        expand();
    });

    // Clicking the card is a convenience, so leave the interactive parts alone:
    // links, the screenshot, and the disclosure toggle do their own job.
    entry.addEventListener('click', (e) => {
        if (e.target.closest('a, img, button, summary, input, select, textarea')) return;
        expand();
    });

    feedContent.appendChild(entry);

    // Keep only last 50 entries
    while (feedContent.children.length > 50) {
        feedContent.removeChild(feedContent.firstChild);
    }

    // Stick to the bottom while the user is following along. If they have scrolled
    // up to read something, leave the viewport alone and count what they are
    // missing instead of yanking them back down.
    if (state.followFeed) {
        requestAnimationFrame(scrollFeedToBottom);
    } else {
        state.newEntryCount = (state.newEntryCount || 0) + 1;
        renderJumpPill();
    }
}

// How close to the bottom still counts as "following".
const FOLLOW_THRESHOLD_PX = 80;

// The DOCUMENT scrolls, not the feed element. The tabbed layout removed the inner
// scroll container, so targeting #feed-content silently did nothing: its scrollTop
// is always 0 and scrollHeight equals clientHeight.
function scroller() {
    return document.scrollingElement || document.documentElement;
}

function isNearBottom() {
    const el = scroller();
    return el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_THRESHOLD_PX;
}

export function scrollFeedToBottom() {
    const el = scroller();
    el.scrollTop = el.scrollHeight;
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

    // Undebounced: the previous 100ms timer meant a scroll back to the bottom did
    // not re-attach until after the next event had already been counted as missed.
    window.addEventListener('scroll', () => {
        const following = isNearBottom();
        if (following === state.followFeed) return;

        state.followFeed = following;
        if (following) state.newEntryCount = 0;
        renderJumpPill();
    }, { passive: true });

    if (pill) {
        pill.addEventListener('click', () => scrollFeedToBottom());
    }

    // Screenshots change the page height after they decode; stay pinned if following.
    feedContent?.addEventListener('load', (e) => {
        if (state.followFeed && e.target.tagName === 'IMG') scrollFeedToBottom();
    }, true);

    resetFeedScroll();
}
