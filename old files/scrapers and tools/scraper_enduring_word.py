import os
import re
import json
import time
import random
from datetime import datetime
from bs4 import BeautifulSoup, NavigableString, Tag, Comment
from curl_cffi import requests

BSB_URL = "https://bereanbible.com/bsb.txt"
OUTPUT_DIR = "commentaries_json"

DEFAULT_CHAPTER_COUNTS = {
    "Genesis": 50, "Exodus": 40, "Leviticus": 27, "Numbers": 36, "Deuteronomy": 34,
    "Joshua": 24, "Judges": 21, "Ruth": 4, "1 Samuel": 31, "2 Samuel": 24,
    "1 Kings": 22, "2 Kings": 25, "1 Chronicles": 29, "2 Chronicles": 36,
    "Ezra": 10, "Nehemiah": 13, "Esther": 10, "Job": 42, "Psalms": 150,
    "Proverbs": 31, "Ecclesiastes": 12, "Song of Solomon": 8, "Isaiah": 66,
    "Jeremiah": 52, "Lamentations": 5, "Ezekiel": 48, "Daniel": 12,
    "Hosea": 14, "Joel": 3, "Amos": 9, "Obadiah": 1, "Jonah": 4, "Micah": 7,
    "Nahum": 3, "Habakkuk": 3, "Zephaniah": 3, "Haggai": 2, "Zechariah": 14,
    "Malachi": 4, "Matthew": 28, "Mark": 16, "Luke": 24, "John": 21,
    "Acts": 28, "Romans": 16, "1 Corinthians": 16, "2 Corinthians": 13,
    "Galatians": 6, "Ephesians": 6, "Philippians": 4, "Colossians": 4,
    "1 Thessalonians": 5, "2 Thessalonians": 3, "1 Timothy": 6, "2 Timothy": 4,
    "Titus": 3, "Philemon": 1, "Hebrews": 13, "James": 5, "1 Peter": 5,
    "2 Peter": 3, "1 John": 5, "2 John": 1, "3 John": 1, "Jude": 1, "Revelation": 22
}

BOOK_TO_SLUG = {
    "Genesis": "genesis", "Exodus": "exodus", "Leviticus": "leviticus",
    "Numbers": "numbers", "Deuteronomy": "deuteronomy", "Joshua": "joshua",
    "Judges": "judges", "Ruth": "ruth", "1 Samuel": "1-samuel",
    "2 Samuel": "2-samuel", "1 Kings": "1-kings", "2 Kings": "2-kings",
    "1 Chronicles": "1-chronicles", "2 Chronicles": "2-chronicles",
    "Ezra": "ezra", "Nehemiah": "nehemiah", "Esther": "esther",
    "Job": "job", "Psalms": "psalms", "Proverbs": "proverbs",
    "Ecclesiastes": "ecclesiastes", "Song of Solomon": "song-of-solomon",
    "Isaiah": "isaiah", "Jeremiah": "jeremiah", "Lamentations": "lamentations",
    "Ezekiel": "ezekiel", "Daniel": "daniel", "Hosea": "hosea",
    "Joel": "joel", "Amos": "amos", "Obadiah": "obadiah",
    "Jonah": "jonah", "Micah": "micah", "Nahum": "nahum",
    "Habakkuk": "habakkuk", "Zephaniah": "zephaniah", "Haggai": "haggai",
    "Zechariah": "zechariah", "Malachi": "malachi", "Matthew": "matthew",
    "Mark": "mark", "Luke": "luke", "John": "john", "Acts": "acts",
    "Romans": "romans", "1 Corinthians": "1-corinthians",
    "2 Corinthians": "2-corinthians", "Galatians": "galatians",
    "Ephesians": "ephesians", "Philippians": "philippians",
    "Colossians": "colossians", "1 Thessalonians": "1-thessalonians",
    "2 Thessalonians": "2-thessalonians", "1 Timothy": "1-timothy",
    "2 Timothy": "2-timothy", "Titus": "titus", "Philemon": "philemon",
    "Hebrews": "hebrews", "James": "james", "1 Peter": "1-peter",
    "2 Peter": "2-peter", "1 John": "1-john", "2 John": "2-john",
    "3 John": "3-john", "Jude": "jude", "Revelation": "revelation"
}

SLUG_TO_BOOK = {v: k for k, v in BOOK_TO_SLUG.items()}
SLUG_TO_BOOK["psalm"] = "Psalms"
SLUG_TO_BOOK["song-of-songs"] = "Song of Solomon"

session = requests.Session(impersonate="chrome")
session.headers.update({
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
})

CUTOFF_REGEX = re.compile(
    r"(?:"
    r"\(\s*Copyright\b.*|"
    r"(?:^|\n)\s*(?:•\s*)?Passage Guide\s*\n\s*(?:\t•\s*)?Map of Bible Topics.*|"
    r"(?:^|\n)\s*(?:•\s*)?Research Tools\b.*|"
    r"(?:^|\n)\s*Bible Study Tools\s*Language Tools.*|"
    r"(?:^|\n)\s*Found a dead link or an error\?.*|"
    r"(?:^|\n)\s*©\s*2001[–\-]\d{4}\s*StudyLight\.org.*"
    r")",
    re.IGNORECASE | re.DOTALL
)

BOILERPLATE_PATTERNS = [
    r"(?i)\bback\s+to\s+top\b[\s\↑\▲\▴\•\|]*",
    r"(?i)\breturn\s+to\s+top\b[\s\↑\▲\▴\•\|]*",
    r"(?i)\btop\s+of\s+page\b[\s\↑\▲\▴\•\|]*",
    r"(?i)\b(?:previous|next)\s+chapter\b.*",
]

FOOTER_MARKERS = [
    "Hebrew Old Testament", "Greek Old and New Testament", "Old Testament/ New Testament Greek",
    "Bill Klein's", "The Greek & Hebrew behind every English word", "Berry's NT Synonyms",
    "Devotional & Christian Living", "Theology & Doctrine", "Sermons & Addresses",
    "Church History & Biography", "Bible Commentary & Exposition", "All 11 Categories",
    "Evangelical", "Reformed / Calvinist", "All 7 Theologies", "Complete List of",
    "Bible Timeline", "Church History Timeline", "Today in Christian History",
    "Bible History, Old Testament", "The Life and Times of Jesus the Messiah",
    "The Early Church Fathers", "History of the Moravian Church", "My Sermons",
    "My Studies", "Sunday Bulletin Inserts", "Gustave Doré's Illustrations",
    "Scripture by Heart", "Create a personalized plan", "Bible-in-a-Year",
    "Morning and Evening with Tozer", "The Believer's Daily Remembrancer", "About SL",
    "Contact SL", "Copyright Statements", "Bulletin Insert", "Audio Bibles",
    "My Notes", "Auto follows your device", "Offline Library",
]

FOOTER_DOM_STARTERS = tuple(FOOTER_MARKERS) + ("Passage Guide", "Research Tools", "Bible Study Tools", "Manage My Preferences",)

_FOOTER_MARKER_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:•[ \t]*)?(?:\*\*|\*)?[ \t]*(?:" + "|".join(re.escape(m) for m in FOOTER_MARKERS) + r")",
    re.IGNORECASE,
)

_AUTHOR_COUNT_LIST_RE = re.compile(
    r"(?:^|\n)(?:[ \t]*•?[ \t]*[A-Z][A-Za-z \t.'\u00a0-]*?[A-Za-z.)']\d{1,4}[ \t]*(?:\n|$)(?:[ \t]*\n)*){2,}"
)

_THEME_SWITCH_RE = re.compile(
    r"(?:^|\n)[ \t]*•?[ \t]*Light[ \t]*\n(?:[ \t]*\n)*[ \t]*•?[ \t]*Dark[ \t]*\n(?:[ \t]*\n)*[ \t]*•?[ \t]*Auto\b.*",
    re.DOTALL | re.IGNORECASE,
)

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def sanitize_token(text):
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.strip()).strip("_").lower()

def get_target_filepath(author_lastname, book_name, commentary_url):
    manifest_path = os.path.join(OUTPUT_DIR, "_file_manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    book_slug = sanitize_token(book_name)
    unique_source_key = f"{commentary_url}::{book_name}"

    if unique_source_key in manifest:
        return os.path.join(OUTPUT_DIR, manifest[unique_source_key])

    base_key = f"{author_lastname}_{book_slug}"
    existing_matches = [
        fname for k, fname in manifest.items()
        if fname == f"{base_key}.json" or re.match(rf"^{re.escape(base_key)}_\d+\.json$", fname)
    ]
    
    count = len(existing_matches) + 1
    filename = f"{base_key}.json" if count == 1 else f"{base_key}_{count}.json"

    manifest[unique_source_key] = filename
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return os.path.join(OUTPUT_DIR, filename)

def _link_density(el):
    total = len(el.get_text("", strip=True)) or 1
    linked = sum(len(a.get_text("", strip=True)) for a in el.find_all("a"))
    return linked / total

def strip_noise_elements(root_tag):
    if not isinstance(root_tag, Tag):
        return

    for comment in root_tag.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    noise_selectors = [
        "script", "style", "nav", "footer", "header", "aside", "iframe", "noscript",
        ".advertisement", ".ads", ".ad-container", ".back-to-top", ".top-link",
        ".share-buttons", ".social-share", ".pagination", ".chapter-nav",
        "#footer", "#nav", "#header", ".mega-menu", ".drawer", ".offcanvas",
        ".site-footer", ".copyright", ".other-commentaries", ".related-resources",
    ]
    for sel in noise_selectors:
        for el in root_tag.select(sel):
            el.decompose()

    for el in root_tag.find_all(["ul", "ol", "div", "section", "li"]):
        if getattr(el, "decomposed", False):
            continue
        full_txt = el.get_text(" ", strip=True)
        if full_txt.startswith(FOOTER_DOM_STARTERS) and (_link_density(el) > 0.5 or len(full_txt) < 600):
            el.decompose()

    for a in root_tag.find_all("a"):
        href = (a.get("href") or "").strip().lower()
        txt = a.get_text(" ", strip=True).lower()
        if href in ("#top", "#page-top", "#header") or "back to top" in txt or "return to top" in txt or txt == "top":
            a.decompose()

def truncate_footers(text):
    cut = len(text)
    for rx in (CUTOFF_REGEX, _FOOTER_MARKER_RE, _AUTHOR_COUNT_LIST_RE, _THEME_SWITCH_RE):
        m = rx.search(text)
        if m and m.start() < cut:
            cut = m.start()
    return text[:cut]

def clean_formatted_verse(text):
    if not text:
        return ""
    text = truncate_footers(text)
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    for pat in BOILERPLATE_PATTERNS:
        text = re.sub(pat, "", text)
    text = re.sub(r"[\ud800-\udfff]", "", text)
    text = text.replace("\u2028", "\n").replace("\u2029", "\n").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n\t *", "\n\t", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?i)(\s*[\|\•\↑\▲\▴\-]*\s*\b(?:back\s+to\s+top|top)\b\s*)+$", "", text)
    return text.strip()

def html_node_to_markdown(node):
    if isinstance(node, Comment): return ""
    if isinstance(node, NavigableString): return re.sub(r"[ \r\n]+", " ", str(node))
    if not isinstance(node, Tag): return ""

    name = node.name.lower()
    if name == "br": return "\n"
    if name == "hr": return "\n---\n"

    inner = "".join(html_node_to_markdown(child) for child in node.children)
    if name in ("b", "strong"): return f" **{inner.strip()}** " if inner.strip() else ""
    if name in ("i", "em"): return f" *{inner.strip()}* " if inner.strip() else ""
    if name == "li": return f"\n\t• {inner.strip()}" if inner.strip() else ""
    if name in ("ul", "ol"): return f"\n{inner.strip()}\n\n"
    
    if name == "blockquote":
        stripped = inner.strip()
        if not stripped: return ""
        tabbed = "\n".join(f"\t{line.strip()}" for line in stripped.splitlines() if line.strip())
        return f"\n\n{tabbed}\n\n"
        
    if name in ("p", "div", "section", "article"): return f"{inner.strip()}\n\n" if inner.strip() else ""
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"): return f"\n\n**{inner.strip()}**\n\n" if inner.strip() else ""
    return inner

def extract_rich_text(element):
    strip_noise_elements(element)
    return clean_formatted_verse(html_node_to_markdown(element))

def write_json_atomic(filepath, data):
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    json.loads(json_str) 
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    os.replace(tmp_path, filepath)

def fetch_url(url, referer=None, max_retries=3):
    headers = {"Referer": referer} if referer else {}
    for attempt in range(1, max_retries + 1):
        try:
            log(f"GET {url} (Attempt {attempt}/{max_retries})", "DEBUG")
            resp = session.get(url, headers=headers, timeout=20)
            if resp.status_code == 404: return None
            if resp.status_code in (403, 429):
                time.sleep((2 ** attempt) + random.uniform(0.5, 1.5))
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt < max_retries: time.sleep(2 ** attempt)
            else: return None
    return None

def load_bible_structure(bsb_url):
    structure = {}
    log(f"Attempting to load Bible structure from {bsb_url}...")
    resp = fetch_url(bsb_url, max_retries=2)
    if resp and resp.status_code == 200:
        ref_pattern = re.compile(r"^([1-3]?\s?[A-Za-z\s]+)\s+(\d+):(\d+)\t")
        for line in resp.text.splitlines():
            match = ref_pattern.match(line)
            if match:
                book = match.group(1).strip()
                book = "Psalms" if book == "Psalm" else book
                structure.setdefault(book, {}).setdefault(match.group(2), []).append(match.group(3))
        log(f"Successfully loaded {len(structure)} books from bsb.txt.")
    else:
        log("Could not load bsb.txt. Using built-in 66-book chapter count map.", "WARN")
        for book, ch_count in DEFAULT_CHAPTER_COUNTS.items():
            structure[book] = {str(ch): [] for ch in range(1, int(ch_count) + 1)}
    return structure

def save_book_json(filepath, book_name, book_data):
    if not book_data or not book_data.get(book_name): return
    try:
        write_json_atomic(filepath, book_data)
        log(f"SAVED & VERIFIED {filepath}", "SUCCESS")
    except Exception as e:
        log(f"JSON validation failed for {filepath}: {e}", "ERROR")

# =====================================================================
# ENDURING WORD SCRAPER
# =====================================================================

def get_enduring_word_chapter_links():
    url = "https://enduringword.com/commentary/"
    log(f"Discovering Enduring Word chapter links from {url}...")
    resp = fetch_url(url)
    if not resp: return {}
        
    soup = BeautifulSoup(resp.text, "html.parser")
    book_links = {}
    for a in soup.find_all("a", href=True):
        m = re.search(r"enduringword\.com/bible-commentary/([a-z0-9\-]+)-(\d+)/?", a["href"])
        if m and m.group(1) in SLUG_TO_BOOK:
            book_links.setdefault(SLUG_TO_BOOK[m.group(1)], {})[int(m.group(2))] = a["href"]
    log(f"Discovered links for {len(book_links)} books on Enduring Word.")
    return book_links

def parse_enduring_word_chapter(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    content = soup.select_one(".entry-content, .avia_textblock, main, article")
    if not content: return {}

    strip_noise_elements(content)
    verses_data = {}
    current_verses = []
    buffer = []

    def flush_buffer():
        nonlocal current_verses, buffer
        if current_verses and buffer:
            combined_text = clean_formatted_verse("\n\n".join(buffer))
            if combined_text:
                start_v = current_verses[0]
                verses_data[start_v] = clean_formatted_verse(
                    verses_data.get(start_v, "") + "\n\n" + combined_text
                )
                for v in current_verses[1:]: 
                    verses_data.setdefault(v, f"See commentary on verse {start_v}")
        
        # Reset state to prepare for upcoming verses/sections
        current_verses = []
        buffer = []

    for elem in content.find_all(["h2", "h3", "h4", "p", "blockquote", "ul", "ol"]):
        if elem.name == "p" and elem.find_parent("blockquote"): continue
        plain_text = elem.get_text(" ", strip=True)
        if not plain_text: continue

        # Detect verse block heading, e.g., "1. (1-4)"
        verse_match = re.match(r"^(\d+)\.\s*\((\d+)(?:\s*[\-–]\s*(\d+))?\)", plain_text)
        
        # Detect section headings, e.g., "A. Title", using negative lookahead to ignore initials like "A. W. Tozer"
        section_match = re.match(r"^[A-Z]\.\s+(?![A-Z]\.)", plain_text)

        is_verse_header = bool(verse_match) and elem.name in ("h2", "h3", "h4", "p")
        is_section_header = bool(section_match) and elem.name in ("h2", "h3", "h4", "p")

        if is_section_header:
            # If current_verses is active, we commit that verse block. 
            # If current_verses is empty, we keep accumulating (this prevents cutting off the first "A." section)
            if current_verses:
                flush_buffer()
            if rich_part := extract_rich_text(elem): 
                buffer.append(rich_part)
                
        elif is_verse_header:
            # If we hit a new verse but are already collecting one inside the SAME section, flush the prior verse
            if current_verses:
                flush_buffer()
                
            start_v = int(verse_match.group(2))
            end_v = int(verse_match.group(3)) if verse_match.group(3) else start_v
            current_verses = [str(v) for v in range(start_v, end_v + 1)]
            
            if rich_heading := extract_rich_text(elem): 
                buffer.append(rich_heading)
                
        else:
            # Standard formatting logic. 
            # Appends to the buffer so it either maps to the upcoming verse block or active verse block.
            if rich_part := extract_rich_text(elem): 
                buffer.append(rich_part)

    # Catch the final trailing data at the end of the chapter
    flush_buffer()
    
    return verses_data

def scrape_enduring_word(source, bible_structure):
    title, author_last, url = source["title"], source["author_lastname"], source["url"]
    log(f"==================================================")
    log(f"Starting Enduring Word Commentary: {title}")
    log(f"==================================================")
    
    discovered = get_enduring_word_chapter_links()
    
    for book_name, slug in BOOK_TO_SLUG.items():
        target_file = get_target_filepath(author_last, book_name, url)
        if os.path.exists(target_file):
            log(f"File {target_file} already exists. Skipping {book_name}.")
            continue

        log(f"--> Scraping {title} | Book: {book_name}")
        book_payload = {book_name: {}}
        known_chapters = discovered.get(book_name, {})
        max_ch = len(bible_structure.get(book_name, {})) or int(DEFAULT_CHAPTER_COUNTS.get(book_name, 150))
        chapters_to_iter = sorted(known_chapters.keys()) if known_chapters else list(range(1, max_ch + 1))
        
        for ch in chapters_to_iter:
            ch_str = str(ch)
            ch_url = known_chapters.get(ch, f"https://enduringword.com/bible-commentary/{'psalm' if slug == 'psalms' else slug}-{ch_str}/")
            resp = fetch_url(ch_url, referer=url)
            if not resp:
                log(f"    Skipping missing/blocked chapter: {book_name} {ch_str}", "WARN")
                continue
                
            chapter_verses = parse_enduring_word_chapter(resp.text)
            if chapter_verses: book_payload[book_name][ch_str] = chapter_verses
            time.sleep(random.uniform(0.8, 1.5))
            
        save_book_json(target_file, book_name, book_payload)

def clean_existing_json_files():
    if not os.path.exists(OUTPUT_DIR): return
    for fname in os.listdir(OUTPUT_DIR):
        if not fname.endswith(".json") or fname == "_file_manifest.json": continue
        fpath = os.path.join(OUTPUT_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f: data = json.loads(f.read(), strict=False)
            modified = False
            for book, chapters in data.items():
                if not isinstance(chapters, dict): continue
                for ch, verses in chapters.items():
                    if not isinstance(verses, dict): continue
                    for v, text in list(verses.items()):
                        if isinstance(text, str):
                            if (cleaned := clean_formatted_verse(text)) != text:
                                verses[v], modified = cleaned, True
            if modified: write_json_atomic(fpath, data)
        except Exception:
            try: os.remove(fpath)
            except OSError: pass

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    clean_existing_json_files()
    bible_structure = load_bible_structure(BSB_URL)
    
    enduring_word_source = {
        "title": "Guzik - Enduring Word",
        "author_lastname": "guzik",
        "url": "https://enduringword.com/commentary/"
    }
    
    scrape_enduring_word(enduring_word_source, bible_structure)
    log("Enduring Word commentary finished processing!", "SUCCESS")

if __name__ == "__main__":
    main()