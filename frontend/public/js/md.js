/**
 * Minimal, safe Markdown renderer.
 *
 * The model writes summaries and plans in Markdown, which was being dropped into
 * the DOM verbatim — so headings and **bold** showed as literal asterisks.
 *
 * Everything is HTML-escaped *before* any Markdown is applied. That ordering
 * matters here more than in a normal app: this text is written by a model that has
 * just read an attacker-controlled page, and a finding may quote markup straight
 * from the target. Escaping first means such content can never become live HTML.
 */

export function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Only http(s) links become anchors; javascript: and data: stay as plain text.
function safeHref(url) {
    return /^https?:\/\//i.test(url) ? url : null;
}

function inline(text) {
    return text
        // `code` first, so its contents are not further transformed
        .replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
        .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
            const href = safeHref(url);
            return href
                ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`
                : `${label} (${url})`;
        });
}

export function renderMarkdown(src) {
    if (!src) return '';
    const lines = escapeHtml(String(src).replace(/\r\n?/g, '\n')).split('\n');

    const out = [];
    let listType = null;      // 'ul' | 'ol' | null
    let inFence = false;
    let fence = [];
    let para = [];

    const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null; } };
    const closePara = () => {
        if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; }
    };

    for (const line of lines) {
        // Fenced code blocks pass through untouched (already escaped).
        if (/^\s*```/.test(line)) {
            if (inFence) { out.push(`<pre><code>${fence.join('\n')}</code></pre>`); fence = []; }
            else { closePara(); closeList(); }
            inFence = !inFence;
            continue;
        }
        if (inFence) { fence.push(line); continue; }

        if (!line.trim()) { closePara(); closeList(); continue; }

        const heading = line.match(/^(#{1,6})\s+(.*)$/);
        if (heading) {
            closePara(); closeList();
            const level = Math.min(heading[1].length + 2, 6);   // #  -> h3, keeps page hierarchy
            out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
            continue;
        }

        // Models commonly write section titles as a wholly-bold line rather than
        // with #. Treat those as headings, otherwise the title runs into the
        // paragraph beneath it.
        const boldLine = line.match(/^\s*\*\*(.+?)\*\*[:：]?\s*$/);
        if (boldLine) {
            closePara(); closeList();
            out.push(`<h4>${inline(boldLine[1])}</h4>`);
            continue;
        }

        const ul = line.match(/^\s*[-*+]\s+(.*)$/);
        const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
        if (ul || ol) {
            closePara();
            const want = ul ? 'ul' : 'ol';
            if (listType !== want) { closeList(); out.push(`<${want}>`); listType = want; }
            out.push(`<li>${inline((ul || ol)[1])}</li>`);
            continue;
        }

        if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
            closePara(); closeList(); out.push('<hr>');
            continue;
        }

        closeList();
        para.push(line.trim());
    }

    if (inFence && fence.length) out.push(`<pre><code>${fence.join('\n')}</code></pre>`);
    closePara();
    closeList();
    return out.join('\n');
}

/** Render Markdown into an element, as markup rather than text. */
export function setMarkdown(el, src) {
    if (!el) return;
    el.classList.add('md');
    el.innerHTML = renderMarkdown(src);
}
