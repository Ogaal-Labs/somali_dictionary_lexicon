# Qaamuuska Af-Soomaaliga — Structured Somali Lexicon

A machine-readable, structured lexicon for Somali NLP research, extracted from the
printed **Qaamuuska Af-Soomaaliga** monolingual dictionary. Somali is spoken by
22M+ people yet has almost no structured computational resources; this project turns
a ~1,000-page print dictionary into a clean JSON dataset of **46,314 entries**.

## What's in this repository

```
somali_dictionary_lexicon/
├── code/                       # The extraction pipeline (Python)
│   ├── extractor.py            #   Driver: reads the PDF page-by-page, checkpoints, writes JSON
│   ├── parser.py               #   Core parser: headword / POS / morphology / senses / synonyms regex logic
│   ├── extract_content.py      #   Front-matter extractor: intro & grammar PDFs → structured sections
│   ├── schema.sql              #   PostgreSQL DDL describing the dataset (entries / definitions / synonyms)
│   └── requirements.txt        #   Python dependencies
├── data/
│   └── qaamuuska_full_v3.json  # ★ Final full dataset — 46,314 entries
└── pdf/
    ├── qaamuuska_full.pdf      # The complete source dictionary
    ├── intro.pdf               # Front matter: introduction + abbreviation key (cut section)
    └── grammar_naxwe.pdf       # Somali grammar (naxwe) reference (cut section)
```

## Source

Puglielli, A. & Mansuur, C. (2012). *Qaamuuska Af-Soomaaliga.*
Centro Studi Somali, Roma Tre University Press, Rome, Italy. ISBN 978-88-97524-02-1.
Original PDF: <https://romatrepress.uniroma3.it/wp-content/uploads/2019/05/qaam-cama.pdf>

## The dataset

`data/qaamuuska_full_v3.json` is a JSON array of entry objects. Each entry looks like:

```json
{
  "headword": "aa'",
  "homonym_index": null,
  "pos_code": "f.g1",
  "pos_category": "verb",
  "is_khabar_only": false,
  "gender": null,
  "verb_class": 1,
  "verb_class_label": "Class I  (-ay / -tay) — most common, consonant-final stems",
  "verb_transitivity": "g",
  "conjugation_raw": "(-'ay, -'day)",
  "noun_plural_raw": null,
  "noun_plural": null,
  "domain": null,
  "redirect_to": null,
  "synonyms": [],
  "definitions": [
    { "sense_number": 1, "gloss_prefix": null, "gloss": "Cid ama wax garaacid, u cagajuglayn.", "domain": null, "partial_synonym": null },
    { "sense_number": 2, "gloss_prefix": null, "gloss": "Dagaallamid.", "domain": null, "partial_synonym": null }
  ],
  "source_page": 50,
  "raw_body": "(-'ay, -'day) 1. Cid ama wax garaacid, u cagajuglayn. 2. Dagaallamid.",
  "id": 1
}
```

### Key fields

| Field | Description |
|-------|-------------|
| `headword` | The entry word (imperative form for verbs) |
| `homonym_index` | Disambiguates homonyms (e.g. `beer¹` vs `beer²`) |
| `pos_code` | Raw part-of-speech code from the dictionary (e.g. `f.lg1`, `m.l.kh`) |
| `pos_category` | Normalized POS (verb, noun, pronoun, particle, …) |
| `gender` | For nouns: `m` (masculine), `f` (feminine), or `null` |
| `verb_class` | For verbs: conjugation class 1–4 |
| `verb_transitivity` | For verbs: transitive / intransitive marker |
| `domain` | Subject-domain marker (medicine, physics, law, …) where tagged |
| `definitions[]` | One or more numbered senses, each with a Somali `gloss` |
| `synonyms[]` | Synonym cross-references |
| `redirect_to` | Set when the entry redirects to a canonical spelling |
| `source_page` | Page number in the source PDF |

### Coverage

- **Total entries:** 46,314
- **Nouns:** 34,726 | **Verbs:** 11,445 | **Adjectives:** 2,014 (Somali Class IV stative/adjectival verbs)
- **Entries with synonyms:** 11,415
- **Domain-tagged entries:** ~1,945

`code/schema.sql` gives the full relational schema (entries → definitions → synonyms)
if you want to load the data into PostgreSQL.

## Reproducing the extraction

```bash
cd code
pip install -r requirements.txt
# Place the source dictionary as qaamuuska.pdf one level up (or edit PDF_PATH in extractor.py),
# then run:
python extractor.py
```

`extractor.py` reads the PDF from `START_PAGE` onward, feeds each page's text to the
regexes in `parser.py`, and writes `qaamuuska_full_v3.json` with periodic checkpoints.
`extract_content.py` separately turns the intro and grammar (`naxwe`) PDFs into
structured section JSON.

**Dependencies:** `pdfplumber`, `pymupdf`, `tqdm` (Python 3.9+).

## Intended use

NLP research: POS tagging, lemmatization, morphological analysis, machine-translation
lexicon seeding, and embedding training for Somali.

## Extraction quality

Evaluated on a 100-entry manual-vs-extracted sample: **98.0% precision** (headwords
100%, POS codes 99%, definitions/senses 98%). Known edge case: some diacritic vowel-tone
characters (e.g. `ų`) do not always survive PDF text extraction.

## License

- **Code:** MIT
- **Data:** CC BY-NC 4.0 — non-commercial research use. The underlying dictionary is
  © Centro Studi Somali / Roma Tre University Press; this structured derivative is
  released for research under CC BY-NC, subject to publisher confirmation.

## Citation

If you use this dataset, please cite the source dictionary (Puglielli & Mansuur, 2012)
and this repository.
