-- ===========================================================================
-- PostgreSQL Schema DDL for Qaamuuska Af-Soomaaliga Structured NLP Dataset
-- ===========================================================================

-- Drop tables if they exist (clean setup)
DROP TABLE IF EXISTS synonyms CASCADE;
DROP TABLE IF EXISTS definitions CASCADE;
DROP TABLE IF EXISTS entries CASCADE;

-- 1. ENTRIES TABLE
-- Stores individual headwords, POS information, morphology metadata, and redirects.
CREATE TABLE entries (
    id SERIAL PRIMARY KEY,
    headword VARCHAR(255) NOT NULL,
    homonym_index INTEGER,              -- Nullable: disambiguates homonyms (e.g., beer¹ vs beer²)
    pos_code VARCHAR(50) NOT NULL,       -- Raw POS code from the dictionary (e.g., f.lg1, m.l.kh)
    pos_category VARCHAR(50) NOT NULL,   -- Normalized POS category (e.g., verb, noun, pronoun, particle)
    is_khabar_only BOOLEAN DEFAULT FALSE,-- True for predicative-only nouns/adjectives (m.l.kh, m.dh.kh)
    gender VARCHAR(10),                 -- For nouns: 'm' (masc), 'f' (fem), 'b' (both), or NULL
    verb_class INTEGER,                 -- For verbs: 1, 2, 3, or 4 conjugation class
    verb_class_label VARCHAR(255),      -- Human-readable description of conjugation class
    verb_transitivity VARCHAR(10),       -- For verbs: 'g' (trans), 'mg' (intrans), 'lg' (bitrans), 'g/mg'
    conjugation_raw VARCHAR(255),       -- Raw verb conjugation prefix/suffix text (e.g., (-yeelay, -yeshay))
    noun_plural_raw VARCHAR(255),       -- Raw noun plural metadata text (e.g., (-ooyin, m.l.))
    noun_plural JSONB,                  -- Structured plural info: {"plural_suffix": "...", "plural_gender": "..."}
    domain VARCHAR(50),                 -- Subject domain marker at word-level (e.g., daaw., kiim., bot.)
    redirect_to VARCHAR(255),           -- Headword string of target entry (for ld/eeg pointers)
    redirect_to_id INTEGER REFERENCES entries(id) ON DELETE SET NULL, -- Resolved target entry ID
    source_page INTEGER,                -- PDF page number from source dictionary
    raw_body TEXT NOT NULL              -- Raw body text of dictionary entry before parsing
);

-- 2. DEFINITIONS TABLE
-- Stores individual sense definitions for each headword.
CREATE TABLE definitions (
    id SERIAL PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    sense_number INTEGER NOT NULL,      -- Sense order number (starts at 1)
    gloss_prefix VARCHAR(255),          -- Expanded headword abbreviation (e.g., "Iskadhal ah:" -> "Iskadhal ah")
    gloss TEXT NOT NULL,                -- Definition body text in Somali
    domain VARCHAR(50),                 -- Subject domain marker at sense-level (e.g. daaw., bot.)
    partial_synonym VARCHAR(255)        -- Nullable placeholder for partial synonyms
);

-- 3. SYNONYMS TABLE
-- Stores synonym links (ld references).
CREATE TABLE synonyms (
    id SERIAL PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    target_headword VARCHAR(255) NOT NULL, -- Target headword of the synonym
    target_homonym_index INTEGER,          -- Disambiguator index for the target
    target_entry_id INTEGER REFERENCES entries(id) ON DELETE SET NULL -- Resolved target database entry ID
);

-- ===========================================================================
-- Indexes for performance and quick query lookup
-- ===========================================================================

-- Speed up headword searching and autocomplete lookups
CREATE INDEX idx_entries_headword ON entries (headword);
CREATE INDEX idx_entries_headword_lower ON entries (LOWER(headword));

-- Speed up filtering by part-of-speech category and subject domain
CREATE INDEX idx_entries_pos_category ON entries (pos_category);
CREATE INDEX idx_entries_domain ON entries (domain);

-- Foreign key indexes to speed up joins
CREATE INDEX idx_definitions_entry_id ON definitions (entry_id);
CREATE INDEX idx_synonyms_entry_id ON synonyms (entry_id);
CREATE INDEX idx_entries_redirect_to_id ON entries (redirect_to_id);
CREATE INDEX idx_synonyms_target_entry_id ON synonyms (target_entry_id);

-- GIN Index on JSONB plural column for fast key/value queries
CREATE INDEX idx_entries_noun_plural ON entries USING gin (noun_plural);
