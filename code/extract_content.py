#!/usr/bin/env python3
"""
Extract structured content (sections with headings + body paragraphs) from the
Intro.pdf and naxwe.pdf source documents into JSON files the Laravel app reads.

Output: one JSON file per PDF, shaped as:
{
  "title": "...",
  "sections": [
     {"id": "s1", "num": "1", "title": "...", "level": 2, "html": "<p>..</p>"},
     ...
  ]
}
Heading detection uses font weight (bold flag) + size, plus numbering patterns.
Body text on the content pages is clean; decorative cover/TOC fonts are skipped.
"""
import fitz, re, json, sys, html

BOLD = 2 ** 4

def line_info(line):
    """Merge spans of a line; return (text, max_size, is_bold_majority)."""
    parts, sizes, bold_chars, total_chars = [], [], 0, 0
    for s in line["spans"]:
        t = s["text"]
        parts.append(t)
        sizes.append(s["size"])
        n = len(t.strip())
        total_chars += n
        if s["flags"] & BOLD:
            bold_chars += n
    text = "".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    max_size = max(sizes) if sizes else 0
    is_bold = total_chars > 0 and (bold_chars / total_chars) > 0.6
    return text, max_size, is_bold

def slugify(num, title):
    base = (num + "-" + title).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:60] or "section"

def heading_level(num, size):
    if num:
        depth = num.count(".") + 1 if re.match(r"^\d", num) else 1
        return min(2 + (depth - 1), 4)
    if size >= 16:
        return 2
    if size >= 13:
        return 3
    return 3

# Lines we never want as content/headings (page chrome)
def is_noise(text):
    if not text:
        return True
    if re.fullmatch(r"\d{1,4}", text):          # bare page numbers
        return True
    if re.fullmatch(r"[ivxlcdmIVXLCDM]+", text):  # roman numeral page nums
        return True
    return False

NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.*\S)$")   # "2.1 Title" / "3. Title"

def looks_like_heading(text, size, bold, body_size):
    if len(text) > 90:
        return None
    m = NUM_RE.match(text)
    if m and bold:
        return m.group(1), m.group(2)
    # bold standalone short line, not ending in sentence punctuation
    if bold and size >= 12 and len(text) <= 70 and not text.endswith((".", ",", ":", ";")):
        # avoid catching inline emphasised words: require it be reasonably title-ish
        if text[0].isupper() or text[0].isdigit():
            return "", text
    return None

def extract(path, doc_title, start_page=0):
    doc = fitz.open(path)
    # estimate body font size = most common size
    from collections import Counter
    sizes = Counter()
    for p in doc:
        for b in p.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if s["text"].strip():
                        sizes[round(s["size"])] += len(s["text"])
    body_size = sizes.most_common(1)[0][0] if sizes else 11

    sections = []
    cur = None
    para = []
    pending_num = ""        # a bold "2.1"-only line waiting for its title line
    PURE_NUM = re.compile(r"^(\d+(?:\.\d+)*)\.?$")

    def flush_para():
        nonlocal para
        if para and cur is not None:
            txt = " ".join(para).strip()
            txt = re.sub(r"\s+", " ", txt)
            if txt:
                cur["paras"].append(txt)
        para = []

    for pi in range(start_page, doc.page_count):
        page = doc[pi]
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                text, size, bold = line_info(l)
                if is_noise(text):
                    flush_para()
                    continue
                # a bold standalone number ("2.1") -> remember, attach to next title
                if bold and PURE_NUM.match(text):
                    flush_para()
                    pending_num = PURE_NUM.match(text).group(1)
                    continue
                hd = looks_like_heading(text, size, bold, body_size)
                if hd is not None:
                    flush_para()
                    num, title = hd
                    if pending_num and not num:
                        num = pending_num
                    pending_num = ""
                    cur = {"id": slugify(num, title), "num": num,
                           "title": title, "level": heading_level(num, size),
                           "paras": [], "page": pi + 1}
                    sections.append(cur)
                else:
                    if cur is None:
                        cur = {"id": "intro", "num": "", "title": doc_title,
                               "level": 2, "paras": [], "page": pi + 1}
                        sections.append(cur)
                    para.append(text)
    flush_para()

    # Build html, drop empty sections
    out = []
    seen = set()
    for s in sections:
        sid = s["id"]
        i = 2
        while sid in seen:
            sid = f"{s['id']}-{i}"; i += 1
        seen.add(sid)
        body = "".join(f"<p>{html.escape(p)}</p>" for p in s["paras"])
        out.append({"id": sid, "num": s["num"], "title": s["title"],
                    "level": s["level"], "html": body, "page": s["page"]})
    return {"title": doc_title, "sections": out}


def extract_abbreviations(path, pages):
    """The 'Ereyada la isku gaabiyay' glossary is a 4-column table
    (code | Somali | Italian | English). Rebuild it by column position."""
    doc = fitz.open(path)

    def col_of(x):
        if x < 105: return 0
        if x < 215: return 1
        if x < 305: return 2
        return 3

    rows = []
    for pi in pages:
        page = doc[pi]
        words = [w for w in page.get_text("words") if w[1] < 600]
        words.sort(key=lambda w: (round(w[1]), w[0]))
        bucket = {}
        for w in words:
            y = round(w[1])
            key = next((k for k in bucket if abs(k - y) <= 4), y)
            bucket.setdefault(key, []).append(w)
        for y in sorted(bucket):
            cells = ["", "", "", ""]
            for w in sorted(bucket[y], key=lambda w: w[0]):
                c = col_of(w[0])
                cells[c] = (cells[c] + " " + w[4]).strip()
            code = cells[0]
            if code and " " not in code and len(code) <= 9 and (cells[1] or cells[2] or cells[3]):
                rows.append(cells)
    return rows


if __name__ == "__main__":
    intro = extract("pdf docs/Intro.pdf",
                    "Hordhaca Qaamuuska", start_page=5)   # skip cover/TOC
    naxwe = extract("pdf docs/naxwe.pdf",
                    "Naxwaha Af-Soomaaliga oo Kooban", start_page=0)

    # Replace the mangled "Ereyada la isku gaabiyay" paragraph with a real table.
    abbr_rows = extract_abbreviations("pdf docs/Intro.pdf", [21, 22])
    for s in intro["sections"]:
        if "gaabiyay" in s["title"].lower():
            s["type"] = "abbreviations"
            s["columns"] = ["Abbreviation", "Somali", "Italian", "English"]
            s["rows"] = abbr_rows
            s["html"] = ""
            break
    json.dump(intro, open("/tmp/about_content.json", "w"),
              ensure_ascii=False, indent=2)
    json.dump(naxwe, open("/tmp/grammar_content.json", "w"),
              ensure_ascii=False, indent=2)
    print("about sections:", len(intro["sections"]))
    for s in intro["sections"][:40]:
        print(f"  [{s['level']}] {s['num']:>5}  {s['title'][:60]}  ({len(s['html'])}c)")
    print("grammar sections:", len(naxwe["sections"]))
    for s in naxwe["sections"][:50]:
        print(f"  [{s['level']}] {s['num']:>6}  {s['title'][:55]}  ({len(s['html'])}c)")
