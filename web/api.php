<?php
/**
 * Qaamuuska-NLP — backend.
 *
 * One file, three jobs:
 *   1. CLI database builder   php api.php build          (full lexicon)
 *                             php api.php build sample   (500-entry sample)
 *   2. Router for the PHP dev server
 *                             php -S localhost:8000 api.php
 *   3. JSON API               api.php?action=...
 *
 * The lexicon never reaches the browser as a file. It lives in private/ as
 * SQLite, and only capped, per-request slices of it are serialised out.
 */

declare(strict_types=1);
mb_internal_encoding('UTF-8');

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/**
 * 'full'   — serve all 46,314 records. For local research work.
 * 'sample' — serve only the 500-entry illustrative sample. Use this for any
 *            public deployment until redistribution rights are settled.
 */
const MODE = 'full';

const PRIVATE_DIR   = __DIR__ . '/private';
const SOURCE_JSON   = ['full' => 'qaamuuska_full_v3.json', 'sample' => 'sample_500_entries.json'];
const DB_FILE       = ['full' => 'qaamuuska-full.sqlite',  'sample' => 'qaamuuska-sample.sqlite'];

/** Response caps. These bound how fast the lexicon can be walked. */
const MAX_LIMIT       = 50;
const MAX_OFFSET      = 5000;
const SUGGEST_LIMIT   = 10;

/**
 * Aggregate figures for the whole resource, as reported in the paper. Shown in
 * the masthead regardless of MODE, because they describe Qaamuuska-NLP itself
 * rather than whatever slice this instance happens to serve.
 */
const CORPUS_TOTALS = [
    'records'     => 46314,
    'nouns'       => 34726,
    'verbs'       => 11445,
    'definitions' => 32801,
];

/** Source dictionary's domain abbreviations, expanded. Paper, Table 3. */
const DOMAINS = [
    'daaw.'  => 'Medicine',
    'fiis.'  => 'Physics',
    'xis.'   => 'Mathematics',
    'baay.'  => 'Biology',
    'kiim.'  => 'Chemistry',
    'dii.'   => 'Religion',
    'juqr.'  => 'Geography',
    'jool.'  => 'Geology',
    'bot.'   => 'Botany',
    'muus.'  => 'Music',
    'siyaa.' => 'Politics',
    'taar.'  => 'History',
    'dhaq.'  => 'Commerce',
    'c.nafl' => 'Zoology',
    'qaan.'  => 'Law',
    'c.naf'  => 'Psychology',
];

/** Part-of-speech codes, expanded. */
const POS_LABELS = [
    'noun' => 'Noun', 'verb' => 'Verb', 'exclamation' => 'Exclamation',
    'pronoun' => 'Pronoun', 'particle' => 'Particle',
    'preposition' => 'Preposition', 'numeral' => 'Numeral',
];

const GENDER_LABELS = [
    'm' => 'masculine', 'f' => 'feminine', 'b' => 'either gender',
];

const TRANSITIVITY_LABELS = [
    'g'  => 'transitive', 'mg' => 'intransitive', 'lg' => 'bitransitive',
];

// ---------------------------------------------------------------------------
// Text normalisation
// ---------------------------------------------------------------------------

/**
 * Fold a Somali string to a comparable key.
 *
 * The source dictionary writes the glottal apostrophe with more than one code
 * point (paper, §3.5), so U+2019, U+02BC, U+02BE and the backtick all fold to
 * a plain U+0027. Case is folded and combining marks are dropped, which lets
 * "aa'" and "aa’" and "AA'" all meet on the same key.
 */
function normalize(string $s): string
{
    $s = strtr($s, [
        "\u{2019}" => "'", "\u{2018}" => "'", "\u{02BC}" => "'",
        "\u{02BE}" => "'", "\u{02BB}" => "'", "\u{0060}" => "'",
        "\u{00B4}" => "'", "\u{2032}" => "'",
    ]);
    $s = mb_strtolower($s);
    if (class_exists('Normalizer')) {
        $s = \Normalizer::normalize($s, \Normalizer::FORM_D) ?: $s;
        $s = preg_replace('/\p{Mn}+/u', '', $s) ?? $s;
    }
    // Strip the superscript homonym digits the extraction preserved inline.
    $s = strtr($s, ['¹' => '', '²' => '', '³' => '', '⁴' => '']);
    return trim($s);
}

/** First letter of a headword, for the A–Z browse index. */
function initial(string $norm): string
{
    $c = mb_substr($norm, 0, 1);
    return preg_match('/^\p{L}$/u', $c) ? mb_strtoupper($c) : '#';
}

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------

function db_path(string $mode): string
{
    return PRIVATE_DIR . '/' . DB_FILE[$mode];
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }
    $path = db_path(MODE);
    if (!is_file($path)) {
        fail(503, 'Database not built. Run: php api.php build' . (MODE === 'sample' ? ' sample' : ''));
    }
    $pdo = new PDO('sqlite:' . $path, null, null, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $pdo->exec('PRAGMA query_only = ON');
    return $pdo;
}

const SCHEMA = <<<'SQL'
DROP TABLE IF EXISTS entries;
DROP TABLE IF EXISTS definitions;
DROP TABLE IF EXISTS synonyms;
DROP TABLE IF EXISTS search;
DROP TABLE IF EXISTS meta;

CREATE TABLE entries (
    id                 INTEGER PRIMARY KEY,
    headword           TEXT NOT NULL,
    headword_norm      TEXT NOT NULL,
    initial            TEXT NOT NULL,
    homonym_index      INTEGER,
    pos_code           TEXT,
    pos_category       TEXT,
    gender             TEXT,
    is_khabar_only     INTEGER NOT NULL DEFAULT 0,
    verb_class         INTEGER,
    verb_class_label   TEXT,
    verb_transitivity  TEXT,
    conjugation_raw    TEXT,
    noun_plural_raw    TEXT,
    plural_suffix      TEXT,
    plural_gender      TEXT,
    domain             TEXT,
    redirect_to        TEXT,
    redirect_to_id     INTEGER,
    source_page        INTEGER,
    raw_body           TEXT,
    def_count          INTEGER NOT NULL DEFAULT 0,
    preview            TEXT
);

CREATE TABLE definitions (
    entry_id        INTEGER NOT NULL,
    sense_number    INTEGER,
    gloss_prefix    TEXT,
    gloss           TEXT,
    domain          TEXT,
    partial_synonym TEXT
);

CREATE TABLE synonyms (
    entry_id      INTEGER NOT NULL,
    headword      TEXT NOT NULL,
    homonym_index INTEGER,
    target_id     INTEGER
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE VIRTUAL TABLE search USING fts5(
    headword_norm,
    gloss,
    content='',
    tokenize='unicode61 remove_diacritics 2'
);
SQL;

const INDEXES = <<<'SQL'
CREATE INDEX idx_entries_norm     ON entries(headword_norm);
CREATE INDEX idx_entries_initial  ON entries(initial, headword_norm);
CREATE INDEX idx_entries_pos      ON entries(pos_category, headword_norm);
CREATE INDEX idx_entries_domain   ON entries(domain, headword_norm);
CREATE INDEX idx_entries_target   ON entries(redirect_to_id);
CREATE INDEX idx_defs_entry       ON definitions(entry_id, sense_number);
CREATE INDEX idx_defs_domain      ON definitions(domain);
CREATE INDEX idx_syn_entry        ON synonyms(entry_id);
SQL;

/**
 * Build the SQLite database from the extraction JSON.
 *
 * The full file is 35 MB, so it is streamed record by record rather than
 * decoded in one piece.
 */
function build(string $mode): void
{
    $json = PRIVATE_DIR . '/' . SOURCE_JSON[$mode];
    if (!is_file($json)) {
        fwrite(STDERR, "Source not found: {$json}\n");
        exit(1);
    }

    $out = db_path($mode);
    $tmp = $out . '.building';
    foreach ([$tmp, $tmp . '-journal'] as $stale) {
        if (is_file($stale)) {
            unlink($stale);
        }
    }

    fwrite(STDOUT, "Building {$mode} database from " . basename($json) . "\n");
    $started = microtime(true);

    $pdo = new PDO('sqlite:' . $tmp, null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    $pdo->exec('PRAGMA journal_mode = OFF');
    $pdo->exec('PRAGMA synchronous = OFF');
    foreach (explode(';', SCHEMA) as $stmt) {
        if (trim($stmt) !== '') {
            $pdo->exec($stmt);
        }
    }

    $insEntry = $pdo->prepare(
        'INSERT INTO entries (id, headword, headword_norm, initial, homonym_index, pos_code,
            pos_category, gender, is_khabar_only, verb_class, verb_class_label, verb_transitivity,
            conjugation_raw, noun_plural_raw, plural_suffix, plural_gender, domain, redirect_to,
            redirect_to_id, source_page, raw_body, def_count, preview)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
    );
    $insDef = $pdo->prepare(
        'INSERT INTO definitions (entry_id, sense_number, gloss_prefix, gloss, domain, partial_synonym)
         VALUES (?,?,?,?,?,?)'
    );
    $insSyn = $pdo->prepare(
        'INSERT INTO synonyms (entry_id, headword, homonym_index, target_id) VALUES (?,?,?,?)'
    );
    $insFts = $pdo->prepare('INSERT INTO search (rowid, headword_norm, gloss) VALUES (?,?,?)');

    $pdo->beginTransaction();
    $n = 0;
    $synonymRows = [];

    foreach (stream_records($json) as $e) {
        $head = (string) ($e['headword'] ?? '');
        $norm = normalize($head);

        $glosses = [];
        foreach ($e['definitions'] ?? [] as $d) {
            $g = trim((string) ($d['gloss'] ?? ''));
            if ($g !== '') {
                $glosses[] = $g;
            }
        }
        $preview = $glosses[0] ?? null;
        if ($preview === null && !empty($e['redirect_to'])) {
            $preview = 'eeg ' . $e['redirect_to'];
        }

        $insEntry->execute([
            $e['id'],
            $head,
            $norm,
            initial($norm),
            $e['homonym_index'],
            $e['pos_code'],
            $e['pos_category'],
            $e['gender'],
            !empty($e['is_khabar_only']) ? 1 : 0,
            $e['verb_class'],
            $e['verb_class_label'] !== null ? preg_replace('/\s+/u', ' ', (string) $e['verb_class_label']) : null,
            $e['verb_transitivity'],
            $e['conjugation_raw'],
            $e['noun_plural_raw'],
            $e['noun_plural']['plural_suffix'] ?? null,
            $e['noun_plural']['plural_gender'] ?? null,
            $e['domain'],
            $e['redirect_to'],
            $e['redirect_to_id'],
            $e['source_page'],
            $e['raw_body'],
            count($e['definitions'] ?? []),
            $preview,
        ]);

        foreach ($e['definitions'] ?? [] as $d) {
            $insDef->execute([
                $e['id'], $d['sense_number'] ?? null, $d['gloss_prefix'] ?? null,
                $d['gloss'] ?? null, $d['domain'] ?? null, $d['partial_synonym'] ?? null,
            ]);
        }

        foreach ($e['synonyms'] ?? [] as $s) {
            $synonymRows[] = [$e['id'], (string) ($s['headword'] ?? ''), $s['homonym_index'] ?? null];
        }

        $insFts->execute([$e['id'], $norm, implode(' ', $glosses)]);

        if (++$n % 5000 === 0) {
            $pdo->commit();
            $pdo->beginTransaction();
            fwrite(STDOUT, "  {$n} records\n");
        }
    }
    $pdo->commit();

    // Synonym references name a headword (plus an optional homonym marker)
    // rather than an id, so resolve them against the finished entry index.
    fwrite(STDOUT, "  resolving synonym links\n");
    $index = [];
    foreach ($pdo->query('SELECT id, headword_norm, homonym_index FROM entries') as $row) {
        $index[$row['headword_norm'] . '#' . ($row['homonym_index'] ?? '')] = (int) $row['id'];
        $index[$row['headword_norm']] ??= (int) $row['id'];
    }

    $pdo->beginTransaction();
    foreach ($synonymRows as [$entryId, $synHead, $synHom]) {
        $key    = normalize($synHead);
        $target = $index[$key . '#' . ($synHom ?? '')] ?? $index[$key] ?? null;
        $insSyn->execute([$entryId, $synHead, $synHom, $target]);
    }
    $pdo->commit();

    foreach (explode(';', INDEXES) as $stmt) {
        if (trim($stmt) !== '') {
            $pdo->exec($stmt);
        }
    }

    $meta = $pdo->prepare('INSERT INTO meta (key, value) VALUES (?,?)');
    $meta->execute(['mode', $mode]);
    $meta->execute(['built_at', gmdate('c')]);
    $meta->execute(['source', basename($json)]);
    $meta->execute(['records', (string) $n]);
    $pdo->exec('VACUUM');
    $pdo = null;

    rename($tmp, $out);
    printf(
        "Done: %d records -> %s (%.1f MB) in %.1fs\n",
        $n, basename($out), filesize($out) / 1048576, microtime(true) - $started
    );
}

/**
 * Yield one record at a time from a JSON array of objects.
 *
 * Tracks brace depth outside of strings to find each top-level object, so the
 * 35 MB file never has to be resident as one decoded structure.
 */
function stream_records(string $path): Generator
{
    $fh = fopen($path, 'rb');
    if ($fh === false) {
        throw new RuntimeException("Cannot open {$path}");
    }

    $buf = '';
    $depth = 0;
    $inString = false;
    $escaped = false;

    while (!feof($fh)) {
        $chunk = fread($fh, 1 << 20);
        if ($chunk === false || $chunk === '') {
            break;
        }
        $len = strlen($chunk);
        for ($i = 0; $i < $len; $i++) {
            $c = $chunk[$i];

            if ($depth > 0) {
                $buf .= $c;
            }

            if ($inString) {
                if ($escaped) {
                    $escaped = false;
                } elseif ($c === '\\') {
                    $escaped = true;
                } elseif ($c === '"') {
                    $inString = false;
                }
                continue;
            }

            if ($c === '"') {
                $inString = true;
            } elseif ($c === '{') {
                if ($depth === 0) {
                    $buf = '{';
                }
                $depth++;
            } elseif ($c === '}') {
                $depth--;
                if ($depth === 0) {
                    $record = json_decode($buf, true);
                    if (is_array($record)) {
                        yield $record;
                    }
                    $buf = '';
                }
            }
        }
    }
    fclose($fh);
}

// ---------------------------------------------------------------------------
// Query helpers
// ---------------------------------------------------------------------------

function clamp_limit(mixed $v, int $default = 25): int
{
    $n = is_numeric($v) ? (int) $v : $default;
    return max(1, min(MAX_LIMIT, $n));
}

function clamp_offset(mixed $v): int
{
    $n = is_numeric($v) ? (int) $v : 0;
    return max(0, min(MAX_OFFSET, $n));
}

/** Columns safe to expose in a list. Notably excludes raw_body. */
const LIST_COLUMNS = 'id, headword, homonym_index, pos_code, pos_category, gender,
                      domain, redirect_to, redirect_to_id, def_count, preview';

function decorate(array $row): array
{
    $row['id']            = (int) $row['id'];
    $row['pos_label']     = POS_LABELS[$row['pos_category'] ?? ''] ?? $row['pos_category'];
    $row['gender_label']  = GENDER_LABELS[$row['gender'] ?? ''] ?? null;
    $row['domain_label']  = DOMAINS[$row['domain'] ?? ''] ?? null;
    if (isset($row['homonym_index'])) {
        $row['homonym_index'] = $row['homonym_index'] === null ? null : (int) $row['homonym_index'];
    }
    if (array_key_exists('def_count', $row)) {
        $row['def_count'] = (int) $row['def_count'];
    }
    if (array_key_exists('redirect_to_id', $row)) {
        $row['redirect_to_id'] = $row['redirect_to_id'] === null ? null : (int) $row['redirect_to_id'];
    }
    return $row;
}

/**
 * Escape a user query for FTS5 MATCH.
 *
 * Every token is quoted, which neutralises FTS operators; the final token gets
 * a prefix star so results appear while the word is still being typed.
 */
function fts_query(string $q, bool $prefix = true): ?string
{
    preg_match_all('/[\p{L}\p{N}\']+/u', $q, $m);
    $tokens = array_filter($m[0], static fn($t) => $t !== '');
    if (!$tokens) {
        return null;
    }
    $tokens = array_slice(array_values($tokens), 0, 8);
    $last   = array_key_last($tokens);
    $parts  = [];
    foreach ($tokens as $i => $t) {
        $quoted  = '"' . str_replace('"', '""', $t) . '"';
        $parts[] = ($prefix && $i === $last) ? $quoted . ' *' : $quoted;
    }
    return implode(' ', $parts);
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

/** Masthead figures, browse facets and the domain index. */
function action_stats(): array
{
    $pdo = db();

    $pos = [];
    foreach ($pdo->query('SELECT pos_category, COUNT(*) c FROM entries GROUP BY pos_category ORDER BY c DESC') as $r) {
        $pos[] = [
            'code'  => $r['pos_category'],
            'label' => POS_LABELS[$r['pos_category'] ?? ''] ?? $r['pos_category'],
            'count' => (int) $r['c'],
        ];
    }

    // A record counts toward a domain via its own label or any sense's label.
    $counts = [];
    foreach ($pdo->query(
        'SELECT domain, COUNT(*) c FROM (
             SELECT id, domain FROM entries WHERE domain IS NOT NULL
             UNION
             SELECT entry_id, domain FROM definitions WHERE domain IS NOT NULL
         ) GROUP BY domain'
    ) as $r) {
        $counts[$r['domain']] = (int) $r['c'];
    }
    $domains = [];
    foreach (DOMAINS as $code => $label) {
        $domains[] = ['code' => $code, 'label' => $label, 'count' => $counts[$code] ?? 0];
    }
    usort($domains, static fn($a, $b) => $b['count'] <=> $a['count']);

    $letters = [];
    foreach ($pdo->query('SELECT initial, COUNT(*) c FROM entries GROUP BY initial ORDER BY initial') as $r) {
        $letters[] = ['letter' => $r['initial'], 'count' => (int) $r['c']];
    }

    $meta = [];
    foreach ($pdo->query('SELECT key, value FROM meta') as $r) {
        $meta[$r['key']] = $r['value'];
    }

    return [
        'mode'    => MODE,
        'totals'  => CORPUS_TOTALS,
        'loaded'  => [
            'records'     => (int) $pdo->query('SELECT COUNT(*) FROM entries')->fetchColumn(),
            'definitions' => (int) $pdo->query('SELECT COUNT(*) FROM definitions')->fetchColumn(),
            'redirects'   => (int) $pdo->query('SELECT COUNT(*) FROM entries WHERE redirect_to IS NOT NULL')->fetchColumn(),
            'synonyms'    => (int) $pdo->query('SELECT COUNT(*) FROM synonyms')->fetchColumn(),
        ],
        'pos'     => $pos,
        'domains' => $domains,
        'letters' => $letters,
        'built'   => $meta['built_at'] ?? null,
    ];
}

/**
 * Ranked search.
 *
 * Rank 0 exact headword, 1 prefix, 2 any headword token, 3 definition text.
 * Shorter headwords win ties, so "aad" outranks "aadaamid" for "aad".
 */
function action_search(array $in): array
{
    $q = trim((string) ($in['q'] ?? ''));
    if ($q === '') {
        return ['query' => '', 'total' => 0, 'results' => []];
    }
    $norm   = normalize($q);
    $limit  = clamp_limit($in['limit'] ?? null);
    $offset = clamp_offset($in['offset'] ?? null);
    $pdo    = db();

    $ranked = [];   // id => rank
    $push = static function (array $ids, int $rank) use (&$ranked): void {
        foreach ($ids as $id) {
            $id = (int) $id;
            if (!isset($ranked[$id]) || $ranked[$id] > $rank) {
                $ranked[$id] = $rank;
            }
        }
    };

    $cap = MAX_OFFSET + MAX_LIMIT;

    $st = $pdo->prepare('SELECT id FROM entries WHERE headword_norm = ? LIMIT ?');
    $st->execute([$norm, $cap]);
    $push($st->fetchAll(PDO::FETCH_COLUMN), 0);

    $st = $pdo->prepare(
        "SELECT id FROM entries WHERE headword_norm LIKE ? ESCAPE '\\' AND headword_norm <> ? LIMIT ?"
    );
    $st->execute([addcslashes($norm, '%_\\') . '%', $norm, $cap]);
    $push($st->fetchAll(PDO::FETCH_COLUMN), 1);

    if ($match = fts_query($q)) {
        $st = $pdo->prepare('SELECT rowid FROM search WHERE headword_norm MATCH ? LIMIT ?');
        $st->execute([$match, $cap]);
        $push($st->fetchAll(PDO::FETCH_COLUMN), 2);

        $st = $pdo->prepare('SELECT rowid FROM search WHERE gloss MATCH ? LIMIT ?');
        $st->execute([$match, $cap]);
        $push($st->fetchAll(PDO::FETCH_COLUMN), 3);
    }

    $total = count($ranked);
    if ($total === 0) {
        return ['query' => $q, 'total' => 0, 'results' => []];
    }

    $ids  = array_keys($ranked);
    $ph   = implode(',', array_fill(0, count($ids), '?'));
    $st   = $pdo->prepare(
        'SELECT ' . LIST_COLUMNS . ', headword_norm FROM entries WHERE id IN (' . $ph . ')'
    );
    $st->execute($ids);
    $rows = $st->fetchAll();

    usort($rows, static function ($a, $b) use ($ranked) {
        return [$ranked[(int) $a['id']], mb_strlen($a['headword_norm']), $a['headword_norm'], (int) $a['id']]
           <=> [$ranked[(int) $b['id']], mb_strlen($b['headword_norm']), $b['headword_norm'], (int) $b['id']];
    });

    $page = array_slice($rows, $offset, $limit);
    foreach ($page as &$row) {
        $row['rank'] = $ranked[(int) $row['id']];
        unset($row['headword_norm']);
        $row = decorate($row);
    }
    unset($row);

    swap_in_matching_gloss($pdo, $page, $norm);

    return ['query' => $q, 'total' => $total, 'offset' => $offset, 'limit' => $limit, 'results' => $page];
}

/**
 * Show the sense that actually matched.
 *
 * A record can match on its fourth definition while its stored preview is the
 * first one, which leaves a result looking unrelated to the query. For those
 * rows, swap in the first gloss that really contains the term.
 */
function swap_in_matching_gloss(PDO $pdo, array &$rows, string $norm): void
{
    $ids = [];
    foreach ($rows as $row) {
        if (($row['rank'] ?? 0) >= 2 && $row['def_count'] > 1) {
            $ids[] = (int) $row['id'];
        }
    }
    if (!$ids) {
        return;
    }

    $st = $pdo->prepare(
        'SELECT entry_id, gloss FROM definitions
          WHERE entry_id IN (' . implode(',', array_fill(0, count($ids), '?')) . ')
          ORDER BY entry_id, sense_number'
    );
    $st->execute($ids);

    $best = [];
    foreach ($st as $d) {
        $id = (int) $d['entry_id'];
        if (isset($best[$id]) || $d['gloss'] === null) {
            continue;
        }
        if (str_contains(normalize($d['gloss']), $norm)) {
            $best[$id] = $d['gloss'];
        }
    }

    foreach ($rows as &$row) {
        if (isset($best[(int) $row['id']])) {
            $row['preview'] = $best[(int) $row['id']];
        }
    }
    unset($row);
}

/** Headword-only completions for the search dropdown. */
function action_suggest(array $in): array
{
    $q = trim((string) ($in['q'] ?? ''));
    if ($q === '') {
        return ['results' => []];
    }
    $norm = normalize($q);
    $st = db()->prepare(
        "SELECT id, headword, homonym_index, pos_category, preview
           FROM entries
          WHERE headword_norm LIKE ? ESCAPE '\\'
          ORDER BY LENGTH(headword_norm), headword_norm
          LIMIT ?"
    );
    $st->execute([addcslashes($norm, '%_\\') . '%', SUGGEST_LIMIT]);
    return ['results' => array_map('decorate', $st->fetchAll())];
}

/** One complete record, with its relations resolved in both directions. */
function action_entry(array $in): array
{
    $id  = (int) ($in['id'] ?? 0);
    $pdo = db();

    $st = $pdo->prepare('SELECT * FROM entries WHERE id = ?');
    $st->execute([$id]);
    $entry = $st->fetch();
    if (!$entry) {
        fail(404, 'No entry with id ' . $id);
    }

    $entry = decorate($entry);
    $entry['transitivity_label'] = TRANSITIVITY_LABELS[$entry['verb_transitivity'] ?? ''] ?? null;
    $entry['plural_gender_label'] = GENDER_LABELS[$entry['plural_gender'] ?? ''] ?? null;
    $entry['is_khabar_only'] = (bool) $entry['is_khabar_only'];
    $entry['source_page'] = $entry['source_page'] === null ? null : (int) $entry['source_page'];
    $entry['verb_class'] = $entry['verb_class'] === null ? null : (int) $entry['verb_class'];
    unset($entry['headword_norm'], $entry['initial']);

    $st = $pdo->prepare(
        'SELECT sense_number, gloss_prefix, gloss, domain, partial_synonym
           FROM definitions WHERE entry_id = ? ORDER BY sense_number'
    );
    $st->execute([$id]);
    $entry['definitions'] = array_map(static function ($d) {
        $d['sense_number'] = $d['sense_number'] === null ? null : (int) $d['sense_number'];
        $d['domain_label'] = DOMAINS[$d['domain'] ?? ''] ?? null;
        return $d;
    }, $st->fetchAll());

    $st = $pdo->prepare(
        'SELECT s.headword, s.homonym_index, s.target_id, e.pos_category
           FROM synonyms s LEFT JOIN entries e ON e.id = s.target_id
          WHERE s.entry_id = ?'
    );
    $st->execute([$id]);
    $entry['synonyms'] = array_map(static function ($s) {
        $s['target_id']     = $s['target_id'] === null ? null : (int) $s['target_id'];
        $s['homonym_index'] = $s['homonym_index'] === null ? null : (int) $s['homonym_index'];
        return $s;
    }, $st->fetchAll());

    // The record this one redirects to ("eeg ...").
    $entry['redirect_target'] = null;
    if ($entry['redirect_to_id']) {
        $st = $pdo->prepare('SELECT ' . LIST_COLUMNS . ' FROM entries WHERE id = ?');
        $st->execute([$entry['redirect_to_id']]);
        if ($t = $st->fetch()) {
            $entry['redirect_target'] = decorate($t);
        }
    }

    // Records that redirect here, so a target entry shows its variant forms.
    $st = $pdo->prepare(
        'SELECT id, headword, homonym_index, pos_category FROM entries
          WHERE redirect_to_id = ? ORDER BY headword LIMIT ?'
    );
    $st->execute([$id, MAX_LIMIT]);
    $entry['referenced_by'] = array_map('decorate', $st->fetchAll());

    return ['entry' => $entry];
}

/** Paginated lists by part of speech, subject domain or initial letter. */
function action_browse(array $in): array
{
    $limit  = clamp_limit($in['limit'] ?? null);
    $offset = clamp_offset($in['offset'] ?? null);
    $pdo    = db();

    $pos    = (string) ($in['pos'] ?? '');
    $domain = (string) ($in['domain'] ?? '');
    $letter = (string) ($in['letter'] ?? '');

    if ($pos !== '') {
        if (!isset(POS_LABELS[$pos])) {
            fail(400, 'Unknown part of speech: ' . $pos);
        }
        $where = 'pos_category = ?';
        $args  = [$pos];
        $title = POS_LABELS[$pos] . 's';
    } elseif ($domain !== '') {
        if (!isset(DOMAINS[$domain])) {
            fail(400, 'Unknown domain: ' . $domain);
        }
        $where = 'id IN (SELECT id FROM entries WHERE domain = ?
                         UNION SELECT entry_id FROM definitions WHERE domain = ?)';
        $args  = [$domain, $domain];
        $title = DOMAINS[$domain];
    } elseif ($letter !== '') {
        $where = 'initial = ?';
        $args  = [mb_strtoupper(mb_substr($letter, 0, 1))];
        $title = mb_strtoupper(mb_substr($letter, 0, 1));
    } else {
        fail(400, 'browse needs pos, domain or letter');
    }

    $st = $pdo->prepare('SELECT COUNT(*) FROM entries WHERE ' . $where);
    $st->execute($args);
    $total = (int) $st->fetchColumn();

    $st = $pdo->prepare(
        'SELECT ' . LIST_COLUMNS . ' FROM entries WHERE ' . $where .
        ' ORDER BY headword_norm, homonym_index LIMIT ? OFFSET ?'
    );
    $st->execute([...$args, $limit, $offset]);

    return [
        'title'   => $title,
        'total'   => $total,
        'offset'  => $offset,
        'limit'   => $limit,
        'results' => array_map('decorate', $st->fetchAll()),
    ];
}

// ---------------------------------------------------------------------------
// HTTP plumbing
// ---------------------------------------------------------------------------

function send(array $payload, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('X-Content-Type-Options: nosniff');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function fail(int $status, string $message): never
{
    send(['error' => $message], $status);
}

function serve_api(): never
{
    $action = (string) ($_GET['action'] ?? '');
    try {
        $payload = match ($action) {
            'stats'   => action_stats(),
            'search'  => action_search($_GET),
            'suggest' => action_suggest($_GET),
            'entry'   => action_entry($_GET),
            'browse'  => action_browse($_GET),
            default   => fail(400, 'Unknown action. Try stats, search, suggest, entry or browse.'),
        };
    } catch (PDOException $e) {
        error_log('qaamuuska-nlp: ' . $e->getMessage());
        fail(500, 'Query failed.');
    }
    send($payload);
}

/**
 * Static file handling for `php -S localhost:8000 api.php`.
 *
 * Returns true when the request was an ordinary file that the dev server
 * should serve itself. private/ is refused here so the dev server does not
 * hand out the lexicon; Apache and nginx get the same effect from
 * private/.htaccess and their own config.
 */
function serve_static(): bool
{
    $uri  = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
    $path = urldecode($uri);

    if (preg_match('#(^|/)(private|\.)#', $path)) {
        http_response_code(403);
        header('Content-Type: text/plain; charset=utf-8');
        echo "403 Forbidden\n";
        exit;
    }

    if ($path === '/' || $path === '') {
        // The header has to go out before any of the body does.
        header('Content-Type: text/html; charset=utf-8');
        readfile(__DIR__ . '/index.html');
        exit;
    }

    $file = realpath(__DIR__ . $path);
    return $file !== false && is_file($file) && str_starts_with($file, __DIR__);
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

if (PHP_SAPI === 'cli') {
    $cmd = $argv[1] ?? '';
    if ($cmd === 'build') {
        $mode = ($argv[2] ?? 'full') === 'sample' ? 'sample' : 'full';
        build($mode);
        exit(0);
    }
    fwrite(STDERR, "Usage:\n  php api.php build [sample]      build the SQLite database\n"
                 . "  php -S localhost:8000 api.php   run the app\n");
    exit(1);
}

if (PHP_SAPI === 'cli-server') {
    $script = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
    if ($script !== '/api.php') {
        if (serve_static()) {
            return false; // let the dev server deliver the file
        }
        // A URL that is neither api.php nor a file on disk is a missing page,
        // not a malformed API call.
        http_response_code(404);
        header('Content-Type: text/plain; charset=utf-8');
        echo "404 Not Found\n";
        exit;
    }
}

serve_api();
