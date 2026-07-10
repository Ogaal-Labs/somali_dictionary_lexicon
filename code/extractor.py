import sys
import time
import json
import urllib.request
from pathlib import Path

# Add current directory to path to resolve local imports cleanly
current_dir = Path(__file__).parent.resolve()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

try:
    import pdfplumber
    from tqdm import tqdm
except ImportError:
    import subprocess
    print("Installing required packages (pdfplumber, pymupdf, tqdm)...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install",
         "pdfplumber", "pymupdf", "tqdm", "--quiet"]
    )
    import pdfplumber
    from tqdm import tqdm

import parser

# ═══════════════════════════════════════════════════════════════════════════════
# Settings & Configuration
# ═══════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent.parent.resolve()

PDF_PATH        = BASE_DIR / "qaamuuska.pdf"
OUTPUT_PATH     = BASE_DIR / "qaamuuska_full_v3.json"
CHECKPOINT_PATH = BASE_DIR / "qaamuuska_checkpoint_v3.json"

PDF_URL = ("https://romatrepress.uniroma3.it/wp-content/uploads"
           "/2019/05/qaam-cama.pdf")

START_PAGE       = 24
END_PAGE         = 916
CHECKPOINT_EVERY = 50

# ═══════════════════════════════════════════════════════════════════════════════
# Functions
# ═══════════════════════════════════════════════════════════════════════════════

def download_pdf(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"PDF already present: {dest} "
              f"({dest.stat().st_size / 1_000_000:.1f} MB)")
        return
    print(f"Downloading PDF from:\n  {url}")
    print("This may take a minute (~8 MB)...")
    urllib.request.urlretrieve(url, dest)
    print(f"Saved → {dest}  ({dest.stat().st_size / 1_000_000:.1f} MB)")


def extract_page_columns(pdf, page_num: int) -> str:
    """
    Cropping the page at the vertical midpoint to read the left column, 
    then the right column, preventing interweaved lines.
    """
    page  = pdf.pages[page_num - 1]
    width = page.width

    left_text  = page.crop((0,         0, width / 2, page.height)).extract_text() or ""
    right_text = page.crop((width / 2, 0, width,     page.height)).extract_text() or ""

    def strip_header(text: str) -> str:
        lines = text.split('\n')
        if lines and len(lines[0].strip().split()) <= 2:
            lines = lines[1:]
        return ' '.join(lines)

    return strip_header(left_text) + ' ' + strip_header(right_text)


def extract_full_dictionary(pdf_path: Path,
                             start_page: int,
                             end_page:   int,
                             checkpoint_every: int,
                             output_path:      Path,
                             checkpoint_path:  Path) -> list:
    """
    Extract all dictionary entries from start_page to end_page.
    """
    all_entries = []
    resume_from = start_page
    next_id     = 1

    # Resume from checkpoint if it exists
    if checkpoint_path.exists():
        with open(checkpoint_path, 'r', encoding='utf-8') as f:
            checkpoint = json.load(f)
        all_entries = checkpoint['entries']
        resume_from = checkpoint['last_page'] + 1
        next_id     = checkpoint.get('next_id', len(all_entries) + 1)
        print(f"Resuming from page {resume_from} "
              f"({len(all_entries)} entries, next id={next_id})")
    else:
        print(f"Starting extraction — pages {start_page}–{end_page}")

    if resume_from > end_page:
        print("Already complete. Loading from checkpoint.")
        return all_entries

    start_time       = time.time()
    page_text_buffer = []

    with pdfplumber.open(pdf_path) as pdf:
        pbar = tqdm(range(resume_from, end_page + 1),
                    desc="Pages", unit="pg")

        for page_num in pbar:
            page_text = extract_page_columns(pdf, page_num)
            page_text_buffer.append((page_num, page_text))

            should_flush = (
                (page_num % checkpoint_every == 0) or
                (page_num == end_page)
            )

            if should_flush:
                combined = ' '.join(t for _, t in page_text_buffer)
                matches  = list(parser.ENTRY_START.finditer(combined))

                for i, match in enumerate(matches):
                    hw    = match.group(1)
                    pos   = match.group(3)
                    start = match.end()
                    end_  = (matches[i + 1].start()
                              if i + 1 < len(matches)
                              else len(combined))
                    body = combined[start:end_].strip()

                    entry       = parser.extract_entry(hw, pos, body,
                                                       source_page=page_num)
                    entry["id"] = next_id
                    next_id    += 1
                    all_entries.append(entry)

                page_text_buffer = []

                with open(checkpoint_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'last_page': page_num,
                        'next_id':   next_id,
                        'entries':   all_entries,
                    }, f, ensure_ascii=False)

                elapsed = time.time() - start_time
                pbar.set_postfix({
                    'entries': len(all_entries),
                    'time':    f'{elapsed / 60:.1f}m',
                })

    return all_entries


def main():
    # 1. Run Parser Unit Tests first
    parser.run_unit_tests()
    print("Unit tests completed successfully.\n")

    # 2. Download the dictionary PDF
    download_pdf(PDF_URL, PDF_PATH)

    # 3. Extract entries
    entries = extract_full_dictionary(
        pdf_path         = PDF_PATH,
        start_page       = START_PAGE,
        end_page         = END_PAGE,
        checkpoint_every = CHECKPOINT_EVERY,
        output_path      = OUTPUT_PATH,
        checkpoint_path  = CHECKPOINT_PATH,
    )

    # 4. Resolve redirects
    entries = parser.resolve_redirects(entries)

    # 5. Save final database
    print(f"\nSaving {len(entries)} entries → {OUTPUT_PATH}")
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    
    print(f"Done. Final file size: {OUTPUT_PATH.stat().st_size / 1_000_000:.1f} MB")
    
    # 6. Report stats
    parser.print_stats(entries)


if __name__ == '__main__':
    main()
