# Qaamuuska-NLP — Structured Somali Lexical Explorer

A web front end over Qaamuuska-NLP, the 46,314-record structured reconstruction of
*Qaamuuska Af-Soomaaliga* (Puglielli & Mansuur, 2012).

The lexicon is never shipped to the browser. It is indexed into SQLite inside `private/`,
and `api.php` returns only capped, per-request slices of it as JSON.

## Running it

```bash
php api.php build            # index the full lexicon  (~1.5s)
php api.php build sample     # index the 500-entry sample
php -S localhost:8000 api.php
```

Then open <http://localhost:8000>. `api.php` acts as the dev server's router: it serves
`index.html` and `src/`, refuses anything under `private/`, and handles `?action=` requests.

Rebuild the index whenever a source JSON changes.

## Full vs sample

`api.php` has one switch at the top:

```php
const MODE = 'full';    // or 'sample'
```

| | `full` | `sample` |
|---|---|---|
| Records served | 46,314 | 500 |
| Source | `private/qaamuuska_full_v3.json` | `private/sample_500_entries.json` |
| Footer note | "Research build · full lexicon" | "Prototype · sample records only." |

**Use `sample` for any public deployment** until redistribution of the complete extracted
dataset is permitted. Flipping the constant is the only change needed — both databases can
sit side by side.

The masthead figures (46,314 / 34,726 / 11,445 / 32,801) describe the resource itself and
stay the same in both modes; they match the paper's Tables 1 and 2 exactly.

## Layout

```
index.html          the app shell
src/styles.css      design tokens and every view's layout
src/app.js          routing, search, rendering
api.php             CLI index builder + dev-server router + JSON API
private/            lexicon JSON, built SQLite, and an Apache deny rule
```

The **Research** tab in the masthead is a plain link to
`qaamuuska-nlp-somali-lexicon-preprint-2026.pdf`, opened in a new tab so the dictionary
keeps its state. There is no in-app research view; drop `target="_blank"` in `index.html`
if you would rather it replace the current tab.

## API

All endpoints are `GET api.php?action=…` and return JSON.

| Action | Parameters | Returns |
|---|---|---|
| `stats` | — | masthead figures, POS counts, 16 domains, A–Z index |
| `search` | `q`, `limit`≤50, `offset`≤5000 | ranked matches |
| `suggest` | `q` | up to 10 headword completions |
| `entry` | `id` | one full record with relations resolved both ways |
| `browse` | `pos` \| `domain` \| `letter`, `limit`, `offset` | paginated list |

### Keeping the lexicon in the server

- The JSON and SQLite files live in `private/`, which `api.php` refuses to serve and
  `private/.htaccess` denies under Apache. On nginx, add `location ^~ /private/ { deny all; }`.
- No endpoint dumps records in bulk: `limit` is capped at 50 and `offset` at 5,000.
- List responses omit `raw_body`; the unparsed source text is only returned for a single
  requested entry.

These bound how quickly the resource can be walked, but a public browse UI is inherently
enumerable — a determined scraper can still page through what the UI exposes. For a
genuinely restricted deployment, run in `sample` mode or put the app behind authentication.

## Search behaviour

Ranked: exact headword → prefix → headword token → definition text. Within a rank, shorter
headwords sort first.

Queries are folded before matching, so the source's several apostrophe code points
(U+0027, U+2019, U+02BC and others — the consistency issue described in §3.5 of the paper)
all collapse together. `aa'` and `aa’` return the same 4,087 records. Case and combining
marks are folded too.

When a record matches on a later sense, the API returns that sense rather than the record's
first gloss, and the client windows long glosses around the match.

## Landing page

The landing view occupies exactly one screen — masthead, title, search, stats, browse row
and note, with no scrolling. `#main` fills `100dvh` minus the masthead and centres the
stack, and every vertical step is sized with `min(Xvw, Yvh)` so it tightens on a short
screen instead of overflowing. The title scales with it, roughly 121px at 900px tall down
to 65px at 480px.

Two things this depends on: `--masthead-h` must stay the single source of the masthead's
height, since the `min-height` calc subtracts it — override the token in a media query,
never `.masthead__inner { height }` — and the flex children need an explicit `width: 100%`,
because `.shell`'s `margin: 0 auto` would otherwise beat flex stretch and centre the hero.

Verified with no vertical or horizontal overflow at 320×568, 360×780, 375×667, 390×844,
414×896, 768×1024, 1024×480, 1280×560, 1512×742 and 1920×1080. Other views scroll normally.

## Search behaviour in the UI

The search field is mounted once in `index.html`, outside every region the app
re-renders. Typing rewrites the URL with `history.replaceState`, which does not fire
`hashchange`, so nothing re-routes: the input keeps focus and the caret, and the page
never scrolls. The first keystroke of a search pushes one history entry, so a single Back
leaves the search no matter how long the word.

Off the home view the field sticks to the top of the viewport, with a live match count
below it. Results that matched only inside a definition are separated from headword
matches by a divider. The outgoing list stays on screen while the next one loads, so
there is no flash between keystrokes, and stale responses from earlier keystrokes are
discarded.

## Keyboard

| Key | |
|---|---|
| `/` | focus the search field |
| `↑` `↓` | move through results |
| `Enter` | open the first result |
| `Esc` | clear the search and return home |

## Notes on the data

- Extraction artifacts are shown as they are, not cleaned: unresolved redirects are labelled
  as such, and every entry carries a collapsible **Source text** panel with its unparsed
  `raw_body`, which is what makes a parsed record checkable against the dictionary.
- Domain counts on `#/domains` (1,974) run slightly above the paper's 1,945 because a record
  labelled in two domains is counted under each; the paper counts domain-labelled records once.
- The Browse row names the two largest domains from the live index (Medicine, Physics)
  rather than the fixed pair in the original mockup.
