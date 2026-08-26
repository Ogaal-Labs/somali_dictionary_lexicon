/* ==========================================================================
   Qaamuuska-NLP — client
   --------------------------------------------------------------------------
   The lexicon stays on the server. Every view here is assembled from capped
   JSON responses served by api.php.

   The search field is mounted once in index.html and is never re-rendered.
   Typing updates #content and rewrites the URL in place, so the input keeps
   focus and the caret, and the page does not jump.
   ========================================================================== */

(function () {
    'use strict';

    const API = 'api.php';

    const heroHead = document.getElementById('hero-head');
    const content  = document.getElementById('content');
    const input    = document.getElementById('q');
    const status   = document.querySelector('[data-status]');
    const hint     = document.querySelector('[data-hint]');
    const clearBtn = document.querySelector('[data-clear]');

    /** Cached api.php?action=stats payload. */
    let stats = null;

    /** Increments on every search; stale responses are discarded. */
    let searchToken = 0;

    /** Where "Back" from an entry should return to. */
    let lastListing = '#/';

    const SUPERSCRIPT = ['', '¹', '²', '³', '⁴'];
    const DEBOUNCE_MS = 170;

    /* ----------------------------------------------------------------------
       Utilities
       ---------------------------------------------------------------------- */

    function esc(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function num(n) {
        return Number(n || 0).toLocaleString('en-US');
    }

    /** Mirror of the server's normalize(), for client-side highlighting. */
    function normalize(s) {
        return String(s || '')
            .replace(/[’‘ʼʾʻ`´′]/g, "'")
            .toLowerCase()
            .normalize('NFD')
            .replace(/[̀-ͯ]/g, '')
            .replace(/[¹²³⁴]/g, '')
            .trim();
    }

    async function api(action, params) {
        const url = new URL(API, window.location.href);
        url.searchParams.set('action', action);
        Object.entries(params || {}).forEach(([k, v]) => {
            if (v !== undefined && v !== null && v !== '') {
                url.searchParams.set(k, v);
            }
        });
        const res = await fetch(url, { headers: { Accept: 'application/json' } });
        const body = await res.json().catch(() => ({ error: 'Malformed response from the server.' }));
        if (!res.ok) {
            throw new Error(body.error || ('Request failed (' + res.status + ')'));
        }
        return body;
    }

    function headwordHTML(entry) {
        const sup = entry.homonym_index
            ? '<sup>' + (SUPERSCRIPT[entry.homonym_index] || entry.homonym_index) + '</sup>'
            : '';
        return esc(entry.headword) + sup;
    }

    /**
     * Highlight the matched span inside a gloss.
     *
     * Runs over the normalized form and maps the offsets back, so a match on
     * "aa'" also highlights a gloss that spells it "aa’". When the match sits
     * past the two lines the card shows, the gloss is windowed around it so the
     * reason the record matched stays visible.
     */
    function highlight(text, query) {
        const q = normalize(query);
        if (!q || q.length < 2) {
            return esc(text);
        }

        const haystack = normalize(text);
        const at = haystack.indexOf(q);
        if (at < 0) {
            return esc(text);
        }

        // Normalization is 1:1 per character here, so offsets carry over.
        let start = 0;
        let lead = '';
        if (at > 90) {
            start = text.lastIndexOf(' ', at - 60) + 1;
            lead = '… ';
        }

        return lead +
            esc(text.slice(start, at)) +
            '<em>' + esc(text.slice(at, at + q.length)) + '</em>' +
            esc(text.slice(at + q.length));
    }

    /* ----------------------------------------------------------------------
       Shared fragments
       ---------------------------------------------------------------------- */

    function metaBits(entry) {
        const bits = [];
        if (entry.pos_label) { bits.push(esc(entry.pos_label.toLowerCase())); }
        if (entry.gender_label) { bits.push(esc(entry.gender_label)); }
        if (entry.pos_code) { bits.push(esc(entry.pos_code)); }
        if (entry.domain_label) { bits.push(esc(entry.domain_label)); }
        return bits.map((b) => '<span>' + b + '</span>').join('');
    }

    function resultHTML(entry, query) {
        const redirectOnly = entry.redirect_to && entry.def_count === 0;
        const body = redirectOnly
            ? '<span class="result__redirect">eeg <b>' + esc(entry.redirect_to) + '</b></span>'
            : '<span class="result__gloss">' + highlight(entry.preview || '—', query) + '</span>';

        return '' +
            '<li class="results__item">' +
              '<a class="result" href="#/entry/' + entry.id + '">' +
                '<span class="result__headword">' + headwordHTML(entry) + '</span>' +
                '<span class="result__body">' +
                  '<span class="result__meta">' + metaBits(entry) + '</span>' +
                  body +
                '</span>' +
              '</a>' +
            '</li>';
    }

    /**
     * Render a page of results, marking where headword matches give way to
     * records that only matched inside a definition.
     */
    function resultsListHTML(results, query) {
        let html = '<ul class="results">';
        let sawHeadword = false;
        let dividerDone = false;

        results.forEach(function (r) {
            const isGlossOnly = r.rank >= 3;
            if (isGlossOnly && sawHeadword && !dividerDone) {
                html += '<li class="results__divider"><span>Matched in a definition</span></li>';
                dividerDone = true;
            }
            if (!isGlossOnly) {
                sawHeadword = true;
            }
            html += resultHTML(r, query);
        });

        return html + '</ul>';
    }

    function pagerHTML(total, offset, limit) {
        if (total <= limit) {
            return '';
        }
        const from = offset + 1;
        const to = Math.min(offset + limit, total);
        return '' +
            '<div class="pager">' +
              '<button type="button" data-page="prev"' + (offset <= 0 ? ' disabled' : '') + '>Previous</button>' +
              '<span>' + num(from) + '–' + num(to) + ' of ' + num(total) + '</span>' +
              '<button type="button" data-page="next"' + (to >= total ? ' disabled' : '') + '>Next</button>' +
            '</div>';
    }

    function footHTML() {
        const built = stats && stats.built ? stats.built.slice(0, 10) : '';
        const loaded = stats ? num(stats.loaded.records) + ' records served' : '';
        return '' +
            '<footer class="foot shell">' +
              '<span>Qaamuuska-NLP &middot; structured reconstruction of <i>Qaamuuska Af-Soomaaliga</i> ' +
                '(Puglielli &amp; Mansuur, 2012)</span>' +
              '<span>' + esc(loaded) + (built ? ' · index built ' + esc(built) : '') + '</span>' +
            '</footer>';
    }

    /* ----------------------------------------------------------------------
       The search field
       ---------------------------------------------------------------------- */

    let typeTimer = null;

    /** Show the "/" hint only on an empty field, and "Clear" only on a full one. */
    function updateAffordances() {
        const filled = input.value.trim() !== '';
        hint.hidden = filled;
        clearBtn.hidden = !filled;
    }

    function setStatus(text, busy) {
        status.textContent = text || '';
        status.dataset.busy = busy ? 'true' : 'false';
    }

    /**
     * Apply a query typed into the field.
     *
     * The URL is rewritten with history.replaceState/pushState, neither of
     * which fires hashchange, so nothing re-routes and the input is left
     * untouched. The first keystroke of a search pushes one entry, so a single
     * Back returns to wherever the user came from; the rest replace it.
     */
    function applyQuery(q) {
        const target = q ? '#/q/' + encodeURIComponent(q) : '#/';
        const wasSearching = window.location.hash.startsWith('#/q/');

        if (window.location.hash !== target) {
            if (wasSearching) {
                window.history.replaceState(null, '', target);
            } else {
                window.history.pushState(null, '', target);
            }
        }

        lastListing = target;

        if (q) {
            renderSearch(q);
        } else {
            renderHome();
        }
    }

    input.addEventListener('input', function () {
        updateAffordances();
        window.clearTimeout(typeTimer);
        const value = input.value.trim();
        if (value) {
            setStatus('Searching…', true);
        }
        typeTimer = window.setTimeout(function () {
            applyQuery(value);
        }, DEBOUNCE_MS);
    });

    input.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            event.preventDefault();
            input.value = '';
            updateAffordances();
            window.clearTimeout(typeTimer);
            applyQuery('');
            return;
        }
        if (event.key === 'Enter') {
            event.preventDefault();
            window.clearTimeout(typeTimer);
            const first = content.querySelector('.results .result');
            if (first) {
                first.click();
            } else {
                applyQuery(input.value.trim());
            }
            return;
        }
        if (event.key === 'ArrowDown') {
            const first = content.querySelector('.results .result');
            if (first) {
                event.preventDefault();
                first.focus();
            }
        }
    });

    clearBtn.addEventListener('click', function () {
        input.value = '';
        updateAffordances();
        window.clearTimeout(typeTimer);
        applyQuery('');
        input.focus();
    });

    function focusSearch(toEnd) {
        if (document.activeElement !== input) {
            input.focus();
        }
        if (toEnd) {
            const end = input.value.length;
            input.setSelectionRange(end, end);
        }
    }

    /* ----------------------------------------------------------------------
       Views — each renders into #content only
       ---------------------------------------------------------------------- */

    function setView(name) {
        document.body.dataset.view = name;
    }

    function renderHome() {
        setView('home');
        setStatus('');
        content.innerHTML = document.getElementById('tpl-home').innerHTML + footHTML();

        if (!stats) {
            return;
        }

        const values = [
            [num(stats.totals.records), 'records'],
            [num(stats.totals.nouns), 'nouns'],
            [num(stats.totals.verbs), 'verbs'],
            [num(stats.totals.definitions), 'definitions'],
        ];
        content.querySelector('[data-stats]').innerHTML = values.map(function (pair) {
            return '<li class="stats__item">' +
                   '<span class="stats__value">' + pair[0] + '</span>' +
                   '<span class="stats__label">' + pair[1] + '</span></li>';
        }).join('');

        const top = stats.domains.filter(function (d) { return d.count > 0; }).slice(0, 2);
        const links = [
            { href: '#/browse/pos/noun', text: 'Nouns' },
            { href: '#/browse/pos/verb', text: 'Verbs' },
        ].concat(top.map(function (d) {
            return { href: '#/browse/domain/' + encodeURIComponent(d.code), text: d.label };
        })).concat([
            { href: '#/domains', text: 'All ' + stats.domains.length + ' domains' },
        ]);

        content.querySelector('[data-browse]').innerHTML =
            '<span class="browse__label">Browse</span>' +
            links.map(function (l, i) {
                return (i ? '<span class="browse__sep">·</span>' : '') +
                       '<a class="browse__link" href="' + l.href + '">' + esc(l.text) + '</a>';
            }).join('');

        content.querySelector('[data-note]').innerHTML = stats.mode === 'sample'
            ? '<p>Prototype · sample records only.</p>' +
              '<p>Glosses are representative placeholders, not text from Qaamuuska Af-Soomaaliga.</p>'
            : '<p>Research build · full lexicon, served query by query.</p>' +
              '<p>Redistribution of the complete extracted dataset is pending permission from the rightsholders.</p>';
    }

    /**
     * Results for a query.
     *
     * The previous list stays on screen while the new one loads, so the page
     * does not flash empty between keystrokes.
     */
    async function renderSearch(query, offset) {
        setView('search');
        const token = ++searchToken;
        const start = offset || 0;

        content.dataset.loading = 'true';

        let data;
        try {
            data = await api('search', { q: query, limit: 25, offset: start });
        } catch (error) {
            if (token === searchToken) {
                renderError(error);
            }
            return;
        }

        if (token !== searchToken) {
            return; // a later keystroke already won
        }

        content.dataset.loading = 'false';

        if (data.total === 0) {
            setStatus('No matches');
            content.innerHTML =
                '<div class="page shell"><div class="state">' +
                '<h2 class="state__title">Nothing matches “' + esc(query) + '”</h2>' +
                '<p class="state__text">No headword or definition contains this. Both apostrophe ' +
                'spellings are folded together, so <code>aa\'</code> and <code>aa’</code> search alike.</p>' +
                '</div></div>' + footHTML();
            return;
        }

        const headwordHits = data.results.filter(function (r) { return r.rank < 3; }).length;
        setStatus(
            num(data.total) + (data.total === 1 ? ' match' : ' matches') +
            (headwordHits ? ' · ' + num(headwordHits) + ' in headwords on this page' : '')
        );

        content.innerHTML =
            '<div class="page shell">' +
            resultsListHTML(data.results, query) +
            pagerHTML(data.total, data.offset, data.limit) +
            '</div>' + footHTML();

        bindPager(function (next) {
            renderSearch(query, next);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }, data.offset, data.limit, data.total);
    }

    async function renderEntry(id) {
        setView('page');
        setStatus('');
        content.innerHTML = '<div class="page shell"><div class="state">' +
            '<p class="state__text">Loading…</p></div></div>';

        let data;
        try {
            data = await api('entry', { id: id });
        } catch (error) {
            return renderError(error);
        }
        const e = data.entry;

        const chips = [];
        if (e.pos_label) { chips.push('<span class="chip chip--solid">' + esc(e.pos_label) + '</span>'); }
        if (e.gender_label) { chips.push('<span class="chip">' + esc(e.gender_label) + '</span>'); }
        if (e.verb_class) { chips.push('<span class="chip">Class ' + ['', 'I', 'II', 'III', 'IV'][e.verb_class] + '</span>'); }
        if (e.transitivity_label) { chips.push('<span class="chip">' + esc(e.transitivity_label) + '</span>'); }
        if (e.is_khabar_only) { chips.push('<span class="chip">predicative only</span>'); }
        if (e.domain_label) { chips.push('<span class="chip">' + esc(e.domain_label) + '</span>'); }
        if (e.pos_code) { chips.push('<span class="chip chip--code">' + esc(e.pos_code) + '</span>'); }

        let html = '<div class="page shell">' +
            '<a class="backlink" href="' + esc(lastListing) + '">&larr; Back</a>' +
            '<article class="entry">' +
            '<h1 class="entry__headword">' + headwordHTML(e) + '</h1>' +
            '<div class="entry__grammar">' + chips.join('') + '</div>';

        if (e.definitions.length) {
            html += '<section class="section"><h2 class="section__heading">' +
                    (e.definitions.length === 1 ? 'Definition' : 'Definitions') + '</h2><ol class="senses">';
            e.definitions.forEach(function (d, i) {
                const prefix = d.gloss_prefix
                    ? '<span class="sense__prefix">' + esc(d.gloss_prefix) + ':</span> '
                    : '';
                const domain = d.domain_label
                    ? '<span class="sense__domain">' + esc(d.domain_label) + '</span>'
                    : '';
                html += '<li class="sense">' +
                        '<span class="sense__number">' + (d.sense_number || i + 1) + '.</span>' +
                        '<span class="sense__text">' + prefix + esc(d.gloss || '') + domain + '</span>' +
                        '</li>';
            });
            html += '</ol></section>';
        }

        if (e.redirect_to) {
            const t = e.redirect_target;
            html += '<section class="section"><h2 class="section__heading">Cross-reference</h2>';
            if (t) {
                html += '<a class="crossref" href="#/entry/' + t.id + '">' +
                        '<span class="crossref__label">eeg &mdash; see</span>' +
                        '<span class="crossref__word">' + headwordHTML(t) + '</span>' +
                        (t.preview ? '<span class="crossref__gloss">' + esc(t.preview) + '</span>' : '') +
                        '</a>';
            } else {
                html += '<div class="crossref">' +
                        '<span class="crossref__label">eeg &mdash; see (unresolved)</span>' +
                        '<span class="crossref__word">' + esc(e.redirect_to) + '</span>' +
                        '<span class="crossref__gloss">This reference is one of the 957 that did not ' +
                        'resolve to an extracted target.</span></div>';
            }
            html += '</section>';
        }

        if (e.synonyms.length) {
            html += '<section class="section"><h2 class="section__heading">Synonym references</h2><ul class="wordlist">';
            e.synonyms.forEach(function (s) {
                const label = esc(s.headword) +
                    (s.homonym_index ? '<sup>' + (SUPERSCRIPT[s.homonym_index] || s.homonym_index) + '</sup>' : '');
                html += s.target_id
                    ? '<li><a href="#/entry/' + s.target_id + '">' + label + '</a></li>'
                    : '<li><span title="not resolved to an extracted record">' + label + '</span></li>';
            });
            html += '</ul></section>';
        }

        if (e.referenced_by.length) {
            html += '<section class="section"><h2 class="section__heading">Referenced by</h2><ul class="wordlist">';
            e.referenced_by.forEach(function (r) {
                html += '<li><a href="#/entry/' + r.id + '">' + headwordHTML(r) + '</a></li>';
            });
            html += '</ul></section>';
        }

        const facts = [];
        if (e.verb_class_label) { facts.push(['Conjugation class', esc(e.verb_class_label)]); }
        if (e.conjugation_raw) { facts.push(['Conjugation', '<code>' + esc(e.conjugation_raw) + '</code>']); }
        if (e.plural_suffix) {
            facts.push(['Plural', '<code>' + esc(e.plural_suffix) + '</code>' +
                (e.plural_gender_label ? ' · ' + esc(e.plural_gender_label) : '')]);
        } else if (e.noun_plural_raw) {
            facts.push(['Plural', '<code>' + esc(e.noun_plural_raw) + '</code>']);
        }
        if (e.pos_code) { facts.push(['Source POS code', '<code>' + esc(e.pos_code) + '</code>']); }
        if (e.source_page) { facts.push(['Source page', 'p. ' + e.source_page]); }
        facts.push(['Record ID', '<code>' + e.id + '</code>']);

        html += '<section class="section"><h2 class="section__heading">Record</h2><dl class="facts">' +
                facts.map(function (f) { return '<dt>' + f[0] + '</dt><dd>' + f[1] + '</dd>'; }).join('') +
                '</dl>';

        if (e.raw_body) {
            html += '<details class="source" style="margin-top:34px">' +
                    '<summary>Source text, as extracted</summary>' +
                    '<div class="source__body">' + esc(e.raw_body) + '</div>' +
                    '</details>';
        }

        html += '</section></article></div>';

        content.innerHTML = html + footHTML();
        document.title = e.headword + ' — Qaamuuska-NLP';
    }

    async function renderBrowse(kind, value, offset) {
        setView('page');
        setStatus('');
        content.innerHTML = '<div class="page shell"><div class="state">' +
            '<p class="state__text">Loading…</p></div></div>';

        const params = { limit: 25, offset: offset || 0 };
        params[kind] = value;

        let data;
        try {
            data = await api('browse', params);
        } catch (error) {
            return renderError(error);
        }

        const eyebrow = kind === 'pos' ? 'Part of speech'
            : kind === 'domain' ? 'Subject domain'
            : 'Alphabetical';

        content.innerHTML =
            '<div class="page shell">' +
            '<p class="page__eyebrow">' + eyebrow + '</p>' +
            '<h1 class="page__title">' + esc(data.title) + '</h1>' +
            '<p class="page__count">' + num(data.total) + ' records</p>' +
            resultsListHTML(data.results, '') +
            pagerHTML(data.total, data.offset, data.limit) +
            '</div>' + footHTML();

        bindPager(function (next) {
            renderBrowse(kind, value, next);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }, data.offset, data.limit, data.total);

        document.title = data.title + ' — Qaamuuska-NLP';
    }

    function renderDomains() {
        setView('page');
        setStatus('');

        content.innerHTML =
            '<div class="page shell">' +
            '<p class="page__eyebrow">Subject domains</p>' +
            '<h1 class="page__title">All ' + stats.domains.length + ' domains</h1>' +
            '<p class="page__count">' +
                num(stats.domains.reduce(function (a, d) { return a + d.count; }, 0)) +
                ' domain-labelled records &middot; the source dictionary’s own abbreviations, expanded</p>' +
            '<div class="index-grid">' +
            stats.domains.map(function (d) {
                return '<a class="index-card" href="#/browse/domain/' + encodeURIComponent(d.code) + '">' +
                       '<span><span class="index-card__name">' + esc(d.label) + '</span>' +
                       '<span class="index-card__code">' + esc(d.code) + '</span></span>' +
                       '<span class="index-card__count">' + num(d.count) + '</span></a>';
            }).join('') +
            '</div>' +
            '<h2 class="section__heading" style="margin-top:56px">Parts of speech</h2>' +
            '<div class="index-grid" style="margin-top:0">' +
            stats.pos.map(function (p) {
                return '<a class="index-card" href="#/browse/pos/' + encodeURIComponent(p.code) + '">' +
                       '<span><span class="index-card__name">' + esc(p.label) + '</span></span>' +
                       '<span class="index-card__count">' + num(p.count) + '</span></a>';
            }).join('') +
            '</div>' +
            '<h2 class="section__heading" style="margin-top:56px">By initial</h2>' +
            '<div class="letters">' +
            stats.letters.map(function (l) {
                return '<a href="#/browse/letter/' + encodeURIComponent(l.letter) + '" title="' +
                       num(l.count) + ' records">' + esc(l.letter) + '</a>';
            }).join('') +
            '</div></div>' + footHTML();

        document.title = 'Browse — Qaamuuska-NLP';
    }

    function renderError(error) {
        const missing = /not built/i.test(error.message);
        setView('page');
        setStatus('');
        content.dataset.loading = 'false';
        content.innerHTML =
            '<div class="page shell"><div class="state">' +
            '<h1 class="state__title">' +
                (missing ? 'The index has not been built yet' : 'Something went wrong') + '</h1>' +
            '<p class="state__text">' + esc(error.message) + '</p>' +
            (missing
                ? '<p class="state__text">Run <code>php api.php build</code> in the project folder, ' +
                  'then reload this page.</p>'
                : '') +
            '</div></div>' + footHTML();
    }

    function bindPager(reload, offset, limit, total) {
        content.querySelectorAll('[data-page]').forEach(function (button) {
            button.addEventListener('click', function () {
                const next = button.dataset.page === 'next'
                    ? Math.min(offset + limit, Math.max(0, total - 1))
                    : Math.max(0, offset - limit);
                reload(next);
            });
        });
    }

    /* ----------------------------------------------------------------------
       Routing

       route() runs on real navigation only: first load, link clicks, and
       Back/Forward. Typing never calls it, because replaceState/pushState do
       not fire hashchange.
       ---------------------------------------------------------------------- */

    function route() {
        const hash = window.location.hash || '#/';

        if (!hash.startsWith('#/entry/')) {
            lastListing = hash;
        }

        document.title = 'Qaamuuska-NLP — Structured Somali Lexical Explorer';

        let m;
        if ((m = hash.match(/^#\/q\/(.*)$/))) {
            const query = decodeURIComponent(m[1]);
            // Back/Forward or a pasted link: bring the field in line with the URL.
            if (input.value !== query) {
                input.value = query;
                updateAffordances();
            }
            renderSearch(query);
            return;
        }

        // Leaving a search: empty the field so it matches what is on screen.
        if (input.value !== '') {
            input.value = '';
            updateAffordances();
        }

        if (hash === '#/' || hash === '') {
            renderHome();
        } else if (hash === '#/domains') {
            renderDomains();
        } else if ((m = hash.match(/^#\/entry\/(\d+)$/))) {
            renderEntry(Number(m[1]));
        } else if ((m = hash.match(/^#\/browse\/(pos|domain|letter)\/(.+)$/))) {
            renderBrowse(m[1], decodeURIComponent(m[2]));
        } else {
            window.location.hash = '#/';
            return;
        }

        window.scrollTo(0, 0);
    }

    /* ----------------------------------------------------------------------
       Global keyboard
       ---------------------------------------------------------------------- */

    document.addEventListener('keydown', function (event) {
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);

        if (event.key === '/' && !typing) {
            event.preventDefault();
            focusSearch(true);
            return;
        }

        if (typing) {
            return;
        }

        const links = Array.from(content.querySelectorAll('.results .result'));
        if (!links.length) {
            return;
        }
        const at = links.indexOf(document.activeElement);
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            links[Math.min(at + 1, links.length - 1)].focus();
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            if (at <= 0) {
                focusSearch(true);
            } else {
                links[at - 1].focus();
            }
        }
    });

    /* ----------------------------------------------------------------------
       Boot
       ---------------------------------------------------------------------- */

    window.addEventListener('hashchange', route);
    window.addEventListener('popstate', function () {
        // Back/Forward across pushState entries that share the same hash form.
        route();
    });

    (async function start() {
        updateAffordances();
        try {
            stats = await api('stats');
        } catch (error) {
            renderError(error);
            return;
        }
        route();
    }());
}());
