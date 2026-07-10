from __future__ import annotations
import re
import json
from collections import Counter

# ═══════════════════════════════════════════════════════════════════════════════
# Regex patterns
# ═══════════════════════════════════════════════════════════════════════════════

# POS code pattern
POS_PATTERN = (
    r'(?:'
    # ── Verbs (order: most specific first) ──────────────────────────────────
    r'f\.lg[1-4]?(?:\/[1-4])?|'        # bitransitive
    r'f\.g\/mg[1-4]?|'                  # dual trans/intrans
    r'f\.mg[1-4]?(?:\/[1-4])?|'        # intransitive
    r'f\.g[1-4]?(?:\/[1-4])?|'         # transitive
    # ── Verbal nouns ────────────────────────────────────────────────────────
    r'm\.f\.(?:l|dh)|'                  # magac faleed (verbal noun)
    # ── Nouns (most specific first) ─────────────────────────────────────────
    r'm\.l\.kh|m\.dh\.kh|'             # predicative noun (khabar-only)
    r'm\.l\.u|m\.dh\.u|'               # collective noun
    r'm\.l\/dh|'                        # gender-variable noun
    r'm\.l|m\.dh|'                      # plain masculine / feminine noun
    # ── Pronouns ────────────────────────────────────────────────────────────
    r'mu\.dhm\.ly|mu\.dhm\.y|'         # clitic pronouns (object before subject)
    r'mu\.eb|mu|'                       # independent / general pronoun
    # ── Particles & function words ──────────────────────────────────────────
    r'qr\.dd|qr|'                       # focus particle / general particle
    r'fk|'                              # adverb (falkaab)
    r'ti|'                              # demonstrative (tilmaame)
    r'kh|'                              # predicative adjective
    r'h|'                               # preposition (horyaale)
    r'xi|'                              # conjunction (xiriiriye)
    # ── Other ───────────────────────────────────────────────────────────────
    r'sh\.r|'                           # ideophone (shanqar-raac)
    r'e\.d|'                            # exclamation (erey dareen)
    r'j|'                               # ordinal numeral
    r't'                                # cardinal numeral
    r')'
)

ENTRY_START = re.compile(
    r'(?<!\w)'
    r'([a-zA-ZcdhkshxqwACDHKSXQWÀ-ÿ\'\-]+[¹²³⁴]?)'   # headword
    r'(\s+)'
    r'(' + POS_PATTERN + r')'                             # POS code
    r'(?=\s)',
    re.UNICODE
)

DOMAIN_PATTERN = re.compile(
    r'\(('
    r'daaw\.|fiis\.|baay\.|bot\.|kiim\.|jool\.|c\.nafl?|c\.naf|'
    r'c\.beer|dhaq\.|qaan\.|dii\.|siyaa\.|xis\.|juqr\.|taar\.|'
    r'muus\.|maan\.'
    r')\)'
)

VERB_CONJUGATION_PATTERN = re.compile(
    r'\(([^)]*-[a-zA-Z\u2019\']+[^)]*)\)'
)

NOUN_META_PATTERN = re.compile(
    r'^\s*\('
    r'('
    r'(?:-[a-zA-Z]+(?:,\s*[a-zA-Z\.\/]+)?)'   # -suffix, optional gender
    r'|'
    r'(?:[a-zA-Z]+\s+m\.[a-z\/]+\.?)'          # plainword + gender (e.g. "tuug m.dh")
    r'|'
    r'(?:m\.[a-z\/]+\.?)'                       # gender variant only (m.l/dh)
    r')'
    r'\)\.?\s*'
)

DEFINITION_SPLIT = re.compile(r'(?<!\w)(\d+)\.\s+')

GLOSS_PREFIX_PATTERN = re.compile(
    r'^'
    r'(?P<prep>[A-Za-z]{1,3}\s+)?'          # optional preposition: "U ", "Ku ", "Is "
    r'(?P<abbrev>[A-Za-z][a-z]?)\.'         # abbreviation: "I.", "A.", "a.", "b."
    r'(?:\s*(?P<qualifier>ah|b|t|u|ku|ka|la|is))?' # optional qualifier: "ah", "b." etc
    r':?\s*'
)

VERB_CLASS_LABELS = {
    1: "Class I  (-ay / -tay)       — most common, consonant-final stems",
    2: "Class II (-iyay / -isay)    — stems ending in -i or -ee",
    3: "Class III (-tay / -atay)    — stems ending in -o / -so / -ow",
    4: "Class IV  (-aa / -ayd)      — stative/adjectival, no imperative form",
}

POS_CATEGORY_MAP = {
    'f':    'verb',
    'm':    'noun',
    'mu':   'pronoun',
    'fk':   'adverb',
    'ti':   'demonstrative',
    'kh':   'predicative_adj',
    'qr':   'particle',
    'h':    'preposition',
    'xi':   'conjunction',
    'e.d':  'exclamation',
    'sh.r': 'ideophone',
    'j':    'numeral_ordinal',
    't':    'numeral_cardinal',
}

# ═══════════════════════════════════════════════════════════════════════════════
# Field Parsers & Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def parse_homonym(hw: str):
    """
    'beer²' → ('beer', 2)
    'cun'   → ('cun', None)
    Also handles ASCII fallback superscripts: 'beer2' → ('beer', 2)
    """
    superscript_map = {'¹': 1, '²': 2, '³': 3, '⁴': 4}
    for char, num in superscript_map.items():
        if hw.endswith(char):
            return hw[:-1], num
    m = re.match(r'^(.+?)([1-4])$', hw)
    if m:
        return m.group(1), int(m.group(2))
    return hw, None


def parse_noun_meta(body: str) -> tuple:
    """
    For noun entries, extract leading plural/gender-variant parenthetical.
    """
    m = NOUN_META_PATTERN.match(body)
    if not m:
        return None, None, body

    raw = m.group(1).strip()
    cleaned_body = body[m.end():].strip()

    noun_plural = _parse_plural_raw(raw)
    return raw, noun_plural, cleaned_body


def _parse_plural_raw(raw: str) -> dict | None:
    """
    Parse plural raw string into structured dict.
    """
    gender_map = {
        'm.l':     'm',
        'm.dh':    'f',
        'm.l/dh':  'b',
        'm.l.':    'm',
        'm.dh.':   'f',
    }

    # Try "suffix, gender" format: "-ayaal, m.l/dh"
    m = re.match(r'^(-?[a-zA-Z]+),\s*(m\.[a-z\/]+\.?)$', raw)
    if m:
        suffix = m.group(1)
        gender_code = m.group(2).rstrip('.')
        gender = gender_map.get(gender_code) or gender_map.get(gender_code + '.')
        return {"plural_suffix": suffix, "plural_gender": gender}

    # Try "word gender" format without comma: "tuug m.dh"
    m = re.match(r'^([a-zA-Z]+)\s+(m\.[a-z\/]+\.?)$', raw)
    if m:
        suffix = m.group(1)
        gender_code = m.group(2).rstrip('.')
        gender = gender_map.get(gender_code) or gender_map.get(gender_code + '.')
        return {"plural_suffix": suffix, "plural_gender": gender}

    # Just a suffix: "-oyin"
    m = re.match(r'^(-[a-zA-Z]+)$', raw)
    if m:
        return {"plural_suffix": m.group(1), "plural_gender": None}

    return None


def expand_gloss_prefix(gloss: str, headword: str) -> tuple:
    """
    Detect and expand headword abbreviations at the start of a gloss.
    """
    if not gloss or not headword:
        return None, gloss

    m = GLOSS_PREFIX_PATTERN.match(gloss)
    if not m:
        return None, gloss

    abbrev_letter = m.group('abbrev').upper()
    prep = (m.group('prep') or '').strip()
    qualifier = (m.group('qualifier') or '').strip()

    if not headword.upper().startswith(abbrev_letter):
        return None, gloss

    expanded_hw = headword.capitalize()
    if prep:
        prefix = f"{prep.capitalize()} {expanded_hw}"
    else:
        prefix = expanded_hw
        if qualifier == 'ah':
            prefix += " ah"
        elif qualifier and qualifier != abbrev_letter.lower():
            prefix += f" {qualifier}"

    cleaned = gloss[m.end():].strip()
    return prefix, cleaned


def parse_synonym_ref(ref_str: str) -> dict:
    """
    Parse a single synonym reference string into a structured dict.
    """
    hw, idx = parse_homonym(ref_str.strip().rstrip('.'))
    return {"headword": hw, "homonym_index": idx}


def parse_definitions(body_text: str, headword: str = "") -> list:
    """
    Split numbered definitions into a list of dicts.
    """
    defs  = []
    parts = DEFINITION_SPLIT.split(body_text.strip())

    if len(parts) == 1:
        text = parts[0].strip()
        if text:
            prefix, clean_text = expand_gloss_prefix(text, headword)
            defs.append({
                "sense_number":    1,
                "gloss_prefix":    prefix,
                "gloss":           clean_text,
                "domain":          None,
                "partial_synonym": None,
            })
    else:
        i = 1
        while i < len(parts) - 1:
            sense_num = int(parts[i])
            gloss_raw = parts[i + 1].strip()
            gloss_raw = _strip_trailing_entry_bleed(gloss_raw)

            domain = None
            dm = DOMAIN_PATTERN.search(gloss_raw)
            if dm:
                domain    = dm.group(1)
                gloss_raw = DOMAIN_PATTERN.sub('', gloss_raw).strip()

            prefix, clean_gloss = expand_gloss_prefix(gloss_raw, headword)

            defs.append({
                "sense_number":    sense_num,
                "gloss_prefix":    prefix,
                "gloss":           clean_gloss,
                "domain":          domain,
                "partial_synonym": None,
            })
            i += 2

    return defs


def _strip_trailing_entry_bleed(gloss: str) -> str:
    """
    Remove trailing text that looks like the start of another dictionary entry.
    """
    bleed_pattern = re.compile(
        r'\.\s+[a-zA-Z\-\']+[¹²³⁴]\s+' + POS_PATTERN,
        re.UNICODE
    )
    m = bleed_pattern.search(gloss)
    if m:
        return gloss[:m.start() + 1].strip()
    return gloss


def extract_entry(headword_raw: str, pos_raw: str,
                  body_raw: str, source_page: int = None) -> dict:
    """
    Parse one raw entry into a structured dict.
    """
    headword, homonym_index = parse_homonym(headword_raw.strip())
    pos_code = pos_raw.strip()

    # ── POS decomposition ─────────────────────────────────────────────────────
    if pos_code.startswith('f.'):
        pos_category = 'verb'
        if 'lg'    in pos_code:    transitivity = 'lg'
        elif 'mg'  in pos_code:    transitivity = 'mg'
        elif 'g/mg' in pos_code:   transitivity = 'g/mg'
        else:                      transitivity = 'g'
        cm = re.search(r'[1-4]', pos_code)
        verb_class = int(cm.group()) if cm else None
    elif pos_code.startswith('m.'):
        pos_category = 'noun'
        transitivity = None
        verb_class   = None
    elif pos_code.startswith('mu'):
        pos_category = 'pronoun'
        transitivity = None
        verb_class   = None
    elif pos_code.startswith('qr'):
        pos_category = 'particle'
        transitivity = None
        verb_class   = None
    elif pos_code == 'fk':
        pos_category = 'adverb'
        transitivity = None
        verb_class   = None
    elif pos_code == 'h':
        pos_category = 'preposition'
        transitivity = None
        verb_class   = None
    elif pos_code == 'xi':
        pos_category = 'conjunction'
        transitivity = None
        verb_class   = None
    elif pos_code == 'kh':
        pos_category = 'predicative_adj'
        transitivity = None
        verb_class   = None
    elif pos_code == 'ti':
        pos_category = 'demonstrative'
        transitivity = None
        verb_class   = None
    elif pos_code == 'e.d':
        pos_category = 'exclamation'
        transitivity = None
        verb_class   = None
    elif pos_code == 'sh.r':
        pos_category = 'ideophone'
        transitivity = None
        verb_class   = None
    elif pos_code in ('j', 't'):
        pos_category = 'numeral'
        transitivity = None
        verb_class   = None
    else:
        pos_category = pos_code
        transitivity = None
        verb_class   = None

    # ── Gender — nouns only ───────────────────────────────────────────────────
    gender = None
    if pos_category == 'noun':
        if 'l/dh'  in pos_code:                       gender = 'b'
        elif 'dh'  in pos_code:                       gender = 'f'
        elif re.match(r'm\.l(?:\.|$)', pos_code):     gender = 'm'

    # ── Predicative-only flag ─────────────────────────────────────────────────
    is_khabar_only = '.kh' in pos_code

    # ── Verb class human-readable label ───────────────────────────────────────
    verb_class_label = VERB_CLASS_LABELS.get(verb_class) if verb_class else None

    # ── Body preprocessing ────────────────────────────────────────────────────
    body = body_raw.strip()

    # For NOUNS: extract and remove leading plural/gender-variant paren FIRST
    noun_plural_raw  = None
    noun_plural      = None
    if pos_category == 'noun':
        noun_plural_raw, noun_plural, body = parse_noun_meta(body)

    # For VERBS: extract conjugation paren
    conj_raw = None
    if pos_category == 'verb':
        cm2 = VERB_CONJUGATION_PATTERN.search(body)
        if cm2:
            conj_raw = '(' + cm2.group(1) + ')'
            body     = (body[:cm2.start()] + body[cm2.end():]).strip()

    # ── Word-level domain marker ──────────────────────────────────────────────
    word_domain = None
    dm2 = DOMAIN_PATTERN.search(body[:120])
    if dm2:
        word_domain = dm2.group(1)
        body        = DOMAIN_PATTERN.sub('', body, count=1).strip()

    # ── Synonym / redirect detection ──────────────────────────────────────────
    redirect_to = None
    synonyms    = []

    pure_redirect = re.match(r'^ld\s+([^\.\s][^\.]*?)\.\s*$', body.strip())
    if pure_redirect:
        redirect_to = pure_redirect.group(1).strip()
        definitions = []
    else:
        ld_refs = re.findall(
            r'\bld\s+([a-zA-ZÀ-ÿ\-\'¹²³⁴]+(?:\s[a-zA-Z¹²³⁴]+)?)', body
        )
        synonyms = [parse_synonym_ref(s) for s in ld_refs]

        body_clean = re.sub(
            r'\bld\s+[a-zA-ZÀ-ÿ\-\'¹²³⁴]+(?:\s[a-zA-Z¹²³⁴]+)?\.?',
            '', body
        ).strip()

        eeg_match = re.search(r'\beeg\s+([a-zA-Z¹²³⁴\-\']+)', body_clean)
        if eeg_match and not re.search(r'\d+\.', body_clean):
            redirect_to = eeg_match.group(1).strip()
            definitions = []
        else:
            definitions = parse_definitions(body_clean, headword=headword)

    return {
        "headword":          headword,
        "homonym_index":     homonym_index,
        "pos_code":          pos_code,
        "pos_category":      pos_category,
        "is_khabar_only":    is_khabar_only,
        "gender":            gender,
        "verb_class":        verb_class,
        "verb_class_label":  verb_class_label,
        "verb_transitivity": transitivity,
        "conjugation_raw":   conj_raw,
        "noun_plural_raw":   noun_plural_raw,
        "noun_plural":       noun_plural,
        "domain":            word_domain,
        "redirect_to":       redirect_to,
        "redirect_to_id":    None,
        "synonyms":          synonyms,
        "definitions":       definitions,
        "source_page":       source_page,
        "raw_body":          body_raw.strip(),
    }


def resolve_redirects(entries: list) -> list:
    """
    Resolve redirect headword strings to the integer IDs of target entries.
    """
    index = {}
    for e in entries:
        key = e["headword"].lower()
        index.setdefault(key, []).append(e)

    resolved   = 0
    unresolved = 0

    for e in entries:
        raw = e.get("redirect_to")
        if not raw:
            continue

        target_hw, target_homonym = parse_homonym(raw.strip())
        key = target_hw.lower()
        candidates = index.get(key, [])

        if not candidates:
            unresolved += 1
            continue

        if target_homonym:
            match = next(
                (c for c in candidates if c["homonym_index"] == target_homonym),
                candidates[0]
            )
        else:
            match = candidates[0]

        e["redirect_to_id"] = match["id"]
        resolved += 1

    print(f"Redirects resolved: {resolved} | Unresolved (manual review): {unresolved}")
    return entries


def print_stats(entries: list) -> None:
    pos_counts         = Counter(e['pos_category'] for e in entries)
    verb_class_counts  = Counter(
        e['verb_class'] for e in entries if e.get('verb_class')
    )
    has_redirect       = sum(1 for e in entries if e['redirect_to'])
    has_redirect_id    = sum(1 for e in entries if e['redirect_to_id'])
    has_synonyms       = sum(1 for e in entries if e['synonyms'])
    has_domain         = sum(1 for e in entries if e['domain'])
    has_homonym        = sum(1 for e in entries if e['homonym_index'])
    has_defs           = sum(1 for e in entries if e['definitions'])
    has_noun_meta      = sum(1 for e in entries if e.get('noun_plural_raw'))
    has_gloss_prefix   = sum(
        1 for e in entries
        if any(d.get('gloss_prefix') for d in e.get('definitions', []))
    )
    has_khabar         = sum(1 for e in entries if e.get('is_khabar_only'))
    empty              = sum(
        1 for e in entries
        if not e['definitions'] and not e['redirect_to']
    )

    print(f"""
── Extraction stats ─────────────────────────────────────────────
Total entries:              {len(entries)}
With definitions:           {has_defs}
Redirects (ld / eeg):       {has_redirect}
  └─ Resolved to id:        {has_redirect_id}
With synonyms:              {has_synonyms}
Domain-tagged:              {has_domain}
Homonym entries:            {has_homonym}
Noun plural metadata:       {has_noun_meta}
Gloss prefix (I. ah: etc):  {has_gloss_prefix}
Khabar-only (m.l.kh etc):   {has_khabar}
Empty (no def/redirect):    {empty}

POS breakdown:""")

    for pos, count in pos_counts.most_common():
        bar = '█' * (count // 100)
        print(f"  {pos:<20} {count:>6}  {bar}")

    if verb_class_counts:
        print("\nVerb class breakdown:")
        for vc, count in sorted(verb_class_counts.items()):
            label = VERB_CLASS_LABELS.get(vc, "Unknown")
            print(f"  Class {vc}  {count:>6}  — {label}")


def run_unit_tests():
    """
    Quick sanity checks.
    """
    print("Running unit tests...")
    errors = []

    def check(name, got, expected):
        if got != expected:
            errors.append(f"  FAIL [{name}]: got {got!r}, expected {expected!r}")

    # ── parse_homonym ─────────────────────────────────────────────────────────
    check("homonym_none",  parse_homonym("cun"),    ("cun", None))
    check("homonym_super", parse_homonym("beer²"),  ("beer", 2))
    check("homonym_ascii", parse_homonym("beer2"),  ("beer", 2))
    check("homonym_4",     parse_homonym("fool⁴"),  ("fool", 4))

    # ── expand_gloss_prefix ───────────────────────────────────────────────────
    p, g = expand_gloss_prefix("I. ah: qof labadiisa waalid aysan isku jiinsiyad ahayn.", "iskadhal")
    check("prefix_I_ah_prefix",  p, "Iskadhal ah")
    check("prefix_I_ah_gloss",   g, "qof labadiisa waalid aysan isku jiinsiyad ahayn.")

    p, g = expand_gloss_prefix("A. ah: qaddarinta ama tixgelinta cid la siiyo.", "aabayeel")
    check("prefix_A_ah_prefix",  p, "Aabayeel ah")
    check("prefix_A_ah_gloss",   g, "qaddarinta ama tixgelinta cid la siiyo.")

    p, g = expand_gloss_prefix("U a.: qaddarin ama tixgelin cid siin.", "aabayeel")
    check("prefix_U_a_prefix",   p, "U Aabayeel")
    check("prefix_U_a_gloss",    g, "qaddarin ama tixgelin cid siin.")

    p, g = expand_gloss_prefix("C. ah: wax dad badani yaqaan.", "caan")
    check("prefix_C_ah_prefix",  p, "Caan ah")
    check("prefix_C_ah_gloss",   g, "wax dad badani yaqaan.")

    p, g = expand_gloss_prefix("Cunto quudasho.", "cun")
    check("no_prefix",           p, None)
    check("no_prefix_gloss",     g, "Cunto quudasho.")

    # ── parse_noun_meta ───────────────────────────────────────────────────────
    raw, struct, body = parse_noun_meta("(-ooyin, m.l.) Fal bulsho joogteysato.")
    check("noun_meta_raw",          raw,    "-ooyin, m.l.")
    check("noun_meta_suffix",       struct["plural_suffix"],  "-ooyin")
    check("noun_meta_gender",       struct["plural_gender"],  "m")
    check("noun_meta_body",         body,   "Fal bulsho joogteysato.")

    raw, struct, body = parse_noun_meta("(-ro, m.l) Dhul la falay.")
    check("noun_meta2_suffix",      struct["plural_suffix"],  "-ro")
    check("noun_meta2_gender",      struct["plural_gender"],  "m")

    raw, struct, body = parse_noun_meta("(-ayaal, m.l/dh) Aabbe.")
    check("noun_meta3_suffix",      struct["plural_suffix"],  "-ayaal")
    check("noun_meta3_gender",      struct["plural_gender"],  "b")

    raw, struct, body = parse_noun_meta("(tuug m.dh) Nin xad dhaafay.")
    check("noun_meta4_suffix",      struct["plural_suffix"],  "tuug")
    check("noun_meta4_gender",      struct["plural_gender"],  "f")

    raw, struct, body = parse_noun_meta("Nin baa yimid.")
    check("noun_no_meta_raw",       raw,    None)
    check("noun_no_meta_struct",    struct, None)
    check("noun_no_meta_body",      body,   "Nin baa yimid.")

    # ── parse_synonym_ref ─────────────────────────────────────────────────────
    check("syn_plain",  parse_synonym_ref("aabayeelid"),  {"headword": "aabayeelid", "homonym_index": None})
    check("syn_super",  parse_synonym_ref("soof¹"),       {"headword": "soof",       "homonym_index": 1})

    # ── extract_entry: iskadhal ───────────────────────────────────────────────
    body = "1. I. ah: qof labadiisa waalid aysan isku jiinsiyad ahayn. 2. I. ah: qof labadiisa waalid ay isku qoys yihiin."
    e = extract_entry("iskadhal", "m.l.kh", body)
    check("iskadhal_pos",        e["pos_category"],             "noun")
    check("iskadhal_khabar",     e["is_khabar_only"],           True)
    check("iskadhal_gender",     e["gender"],                   "m")
    check("iskadhal_def1_pre",   e["definitions"][0]["gloss_prefix"], "Iskadhal ah")
    check("iskadhal_def1_gl",    e["definitions"][0]["gloss"],
          "qof labadiisa waalid aysan isku jiinsiyad ahayn.")
    check("iskadhal_def2_pre",   e["definitions"][1]["gloss_prefix"], "Iskadhal ah")

    # ── extract_entry: aabayeel¹ (noun) ──────────────────────────────────────
    body = "1. A. ah: qaddarinta ama tixgelinta cid la siiyo. 2. ld aabayeelid."
    e = extract_entry("aabayeel¹", "m.l", body)
    check("aabayeel1_hw",        e["headword"],                 "aabayeel")
    check("aabayeel1_homonym",   e["homonym_index"],            1)
    check("aabayeel1_def1_pre",  e["definitions"][0]["gloss_prefix"], "Aabayeel ah")
    check("aabayeel1_syn",       e["synonyms"],
          [{"headword": "aabayeelid", "homonym_index": None}])

    # ── extract_entry: aabayeel² (verb) ──────────────────────────────────────
    body = "(-yeelay, -yeshay) U a.: qaddarin ama tixgelin cid siin."
    e = extract_entry("aabayeel²", "f.mg1", body)
    check("aabayeel2_pos",       e["pos_category"],             "verb")
    check("aabayeel2_class",     e["verb_class"],               1)
    check("aabayeel2_conj",      e["conjugation_raw"],          "(-yeelay, -yeshay)")
    check("aabayeel2_def1_pre",  e["definitions"][0]["gloss_prefix"], "U Aabayeel")
    check("aabayeel2_def1_gl",   e["definitions"][0]["gloss"],
          "qaddarin ama tixgelin cid siin.")

    # ── extract_entry: Caado (noun with plural) ───────────────────────────────
    body = "(-ooyin, m.l.) 1. Fal bulsho joogteysato kuna dhaqanto. 2. Fal qof si joogta ah ugu dhaqmo."
    e = extract_entry("Caado", "m.dh", body)
    check("caado_plural_raw",    e["noun_plural_raw"],          "-ooyin, m.l.")
    check("caado_plural_suffix", e["noun_plural"]["plural_suffix"], "-ooyin")
    check("caado_plural_gender", e["noun_plural"]["plural_gender"], "m")
    check("caado_gender",        e["gender"],                   "f")
    check("caado_def_count",     len(e["definitions"]),         2)
    check("caado_def1_no_meta",  e["definitions"][0]["gloss"],
          "Fal bulsho joogteysato kuna dhaqanto.")

    # ── extract_entry: pure redirect (Pattern A) ─────────────────────────────
    body = "ld quraanyo."
    e = extract_entry("quraanjo", "m.dh.u", body)
    check("redirect_to",         e["redirect_to"],              "quraanyo")
    check("redirect_defs",       e["definitions"],              [])

    if errors:
        print(f"\n{len(errors)} test(s) FAILED:")
        for err in errors:
            print(err)
        raise ValueError("Unit tests failed!")
    else:
        print("All tests passed ✓")


if __name__ == '__main__':
    run_unit_tests()
