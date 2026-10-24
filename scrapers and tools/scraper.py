import os
import re
import json
import time
import random
from datetime import datetime
from bs4 import BeautifulSoup, NavigableString, Tag, Comment
from curl_cffi import requests

# Your provided HTML bookmarks snippet
BOOKMARKS_HTML = """
<DL><p>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/tod.html">Spurgeon - Treasury of David</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/spe.html">Spurgeon - Verse Expositions of the Bible</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/cal.html">Calvin - Commentary on the Bible</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/mlg.html">Luther - Commentary on Galatians</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/mpc.html">Poole - Annotations on the Holy Bible</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/tsk.html">Bagster - Treasury of Scripture Knowledge</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/mhm.html">Henry - Complete Commentary on the Bible</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/wen.html">Wesley - Explanatory Notes</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/ryl.html">Ryle - Expository Thoughts on the Gospels</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/ctf.html">Contending for the Faith</A>
    <DT><A HREF="https://enduringword.com/commentary/">Guzik - Enduring Word</A>
    <DT><A HREF="https://www.studylight.org/commentaries/eng/geb.html">Gill - Exposition of the Whole Bible</A>
</DL><p>
"""

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


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def sanitize_token(text):
    return re.sub(r"[^a-zA-Z0-9]+", "_", text.strip()).strip("_").lower()


def extract_author_lastname(bookmark_title):
    if " - " in bookmark_title:
        author_part = bookmark_title.split(" - ")[0].strip()
        lastname = author_part.split()[-1]
        return sanitize_token(lastname)
    return sanitize_token(bookmark_title)


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


# =====================================================================
# RICH TEXT FORMATTING, FOOTER TRUNCATION & JSON SANITIZATION
# =====================================================================

# Hard cutoff markers: if any of these appear, everything from that point to the end of the string is cut
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

# Menu/footer entries that begin StudyLight's mega-menu block. A marker only counts when it
# starts a line (optionally after a bullet / tab / bold markers), so ordinary commentary
# prose that happens to mention e.g. "Audio Bibles" mid-sentence is never cut.
FOOTER_MARKERS = [
    "Hebrew Old Testament",
    "Greek Old and New Testament",
    "Old Testament/ New Testament Greek",
    "Bill Klein's",
    "The Greek & Hebrew behind every English word",
    "Berry's NT Synonyms",
    "Devotional & Christian Living",
    "Theology & Doctrine",
    "Sermons & Addresses",
    "Church History & Biography",
    "Bible Commentary & Exposition",
    "All 11 Categories",
    "Evangelical",
    "Reformed / Calvinist",
    "All 7 Theologies",
    "Complete List of",
    "Bible Timeline",
    "Church History Timeline",
    "Today in Christian History",
    "Bible History, Old Testament",
    "The Life and Times of Jesus the Messiah",
    "The Early Church Fathers",
    "History of the Moravian Church",
    "My Sermons",
    "My Studies",
    "Sunday Bulletin Inserts",
    "Gustave Doré's Illustrations",
    "Scripture by Heart",
    "Create a personalized plan",
    "Bible-in-a-Year",
    "Morning and Evening with Tozer",
    "The Believer's Daily Remembrancer",
    "About SL",
    "Contact SL",
    "Copyright Statements",
    "Bulletin Insert",
    "Audio Bibles",
    "My Notes",
    "Auto follows your device",
    "Offline Library",
]

# Strings used for the DOM-level check (first ~80 chars of a container's text)
FOOTER_DOM_STARTERS = tuple(FOOTER_MARKERS) + (
    "Passage Guide", "Research Tools", "Bible Study Tools", "Manage My Preferences",
)

_FOOTER_MARKER_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:•[ \t]*)?(?:\*\*|\*)?[ \t]*(?:"
    + "|".join(re.escape(m) for m in FOOTER_MARKERS)
    + r")",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------
# FOOTER / MENU TRUNCATION
#
# All footer truncation flows through truncate_footers(). Every pattern
# below is a "find earliest cut point" regex. The final text is simply
# text[:cut] where cut is the minimum match start across all patterns.
# ---------------------------------------------------------------------

# StudyLight author-list footer. Renders as plain paragraphs like
#   Charles Spurgeon44
#   (blank)
#   Martin Luther22
#   ...
# Bullets are optional (site is inconsistent), blank lines between entries
# are allowed, and the name must start with a capital letter and end with
# a letter / period / close-paren directly before the digit — this prevents
# ordinary prose like "verse 3" / "chapter 4" (space before digit) from
# matching. Requires 2+ consecutive entries so a stray "NIV2011" line is safe.
_AUTHOR_COUNT_LIST_RE = re.compile(
    r"(?:^|\n)"
    r"(?:[ \t]*•?[ \t]*"
    r"[A-Z][A-Za-z \t.'\u00a0-]*?[A-Za-z.)']"
    r"\d{1,4}[ \t]*(?:\n|$)"
    r"(?:[ \t]*\n)*){2,}"
)

# "Light / Dark / Auto" theme switcher (StudyLight's dark-mode toggle).
# Bullets and blank lines between entries are both optional.
_THEME_SWITCH_RE = re.compile(
    r"(?:^|\n)[ \t]*•?[ \t]*Light[ \t]*\n"
    r"(?:[ \t]*\n)*"
    r"[ \t]*•?[ \t]*Dark[ \t]*\n"
    r"(?:[ \t]*\n)*"
    r"[ \t]*•?[ \t]*Auto\b.*",
    re.DOTALL | re.IGNORECASE,
)


def _link_density(el):
    total = len(el.get_text("", strip=True)) or 1
    linked = sum(len(a.get_text("", strip=True)) for a in el.find_all("a"))
    return linked / total


def strip_noise_elements(root_tag):
    """Removes UI menus, drawers, footers, comments, and 'Back to top' links."""
    if not isinstance(root_tag, Tag):
        return

    # 1. Remove HTML comments (StudyLight has broken comments with raw <li><a>)
    for comment in root_tag.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # 2. Remove non-content DOM trees
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

    # 3. Remove menu/footer containers that start with a known heading AND
    #    look like a menu (mostly links, or very short)
    for el in root_tag.find_all(["ul", "ol", "div", "section", "li"]):
        if getattr(el, "decomposed", False):
            continue
        full_txt = el.get_text(" ", strip=True)
        if full_txt.startswith(FOOTER_DOM_STARTERS) and (
            _link_density(el) > 0.5 or len(full_txt) < 600
        ):
            el.decompose()

    # 4. Remove "Back to top" anchors
    for a in root_tag.find_all("a"):
        href = (a.get("href") or "").strip().lower()
        txt = a.get_text(" ", strip=True).lower()
        if href in ("#top", "#page-top", "#header") or "back to top" in txt \
                or "return to top" in txt or txt == "top":
            a.decompose()


def truncate_footers(text):
    """Cuts everything from the earliest footer/menu marker.

    Single source of truth for footer truncation. Every pattern is a
    'find earliest cut point' regex; the minimum wins. This replaces the
    previous split across CUTOFF_REGEX.sub(), a duplicate
    truncate_menu_footer(), and several ad-hoc string.split() calls.
    """
    cut = len(text)
    for rx in (
        CUTOFF_REGEX,          # copyright / Passage Guide / Research Tools / etc.
        _FOOTER_MARKER_RE,     # mega-menu headings
        _AUTHOR_COUNT_LIST_RE, # "Charles Spurgeon44 / Martin Luther22 / ..."
        _THEME_SWITCH_RE,      # Light / Dark / Auto
    ):
        m = rx.search(text)
        if m and m.start() < cut:
            cut = m.start()
    return text[:cut]


def clean_formatted_verse(text):
    """Truncates footer leaks, strips HTML remnants, sanitizes JSON output."""
    if not text:
        return ""

    # 1. Unified footer/menu truncation (see truncate_footers)
    text = truncate_footers(text)

    # 2. Strip leaked raw HTML tags
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)

    # 3. Remove inline boilerplate ("Back to top", "Previous chapter", ...)
    for pat in BOILERPLATE_PATTERNS:
        text = re.sub(pat, "", text)

    # 4. Remove lone UTF-16 surrogates
    text = re.sub(r"[\ud800-\udfff]", "", text)

    # 5. Control chars + unicode line separators
    text = (text
            .replace("\u2028", "\n")
            .replace("\u2029", "\n")
            .replace("\r\n", "\n")
            .replace("\r", "\n"))
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # 6. Whitespace normalization
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n\t *", "\n\t", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 7. Trailing "Back to top"
    text = re.sub(
        r"(?i)(\s*[\|\•\↑\▲\▴\-]*\s*\b(?:back\s+to\s+top|top)\b\s*)+$",
        "", text,
    )
    return text.strip()


def html_node_to_markdown(node):
    if isinstance(node, Comment):
        return ""

    if isinstance(node, NavigableString):
        text = str(node)
        text = re.sub(r"[ \r\n]+", " ", text)
        return text

    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()

    if name == "br":
        return "\n"
    if name == "hr":
        return "\n---\n"

    inner = "".join(html_node_to_markdown(child) for child in node.children)

    if name in ("b", "strong"):
        stripped = inner.strip()
        return f" **{stripped}** " if stripped else ""

    if name in ("i", "em"):
        stripped = inner.strip()
        return f" *{stripped}* " if stripped else ""

    if name == "li":
        stripped = inner.strip()
        return f"\n\t• {stripped}" if stripped else ""

    if name in ("ul", "ol"):
        return f"\n{inner.strip()}\n\n"

    if name == "blockquote":
        stripped = inner.strip()
        if not stripped:
            return ""
        tabbed = "\n".join(f"\t{line.strip()}" for line in stripped.splitlines() if line.strip())
        return f"\n\n{tabbed}\n\n"

    if name in ("p", "div", "section", "article"):
        stripped = inner.strip()
        return f"{stripped}\n\n" if stripped else ""

    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        stripped = inner.strip()
        return f"\n\n**{stripped}**\n\n" if stripped else ""

    return inner


def extract_rich_text(element):
    strip_noise_elements(element)
    raw_md = html_node_to_markdown(element)
    return clean_formatted_verse(raw_md)


# =====================================================================
# NETWORK & CORE UTILITIES
# =====================================================================

def write_json_atomic(filepath, data):
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    json.loads(json_str)  # verify before touching disk
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    os.replace(tmp_path, filepath)  # atomic: file is either the old version or the complete new one


def fetch_url(url, referer=None, max_retries=3):
    headers = {}
    if referer:
        headers["Referer"] = referer

    for attempt in range(1, max_retries + 1):
        try:
            log(f"GET {url} (Attempt {attempt}/{max_retries})", "DEBUG")
            resp = session.get(url, headers=headers, timeout=20)
            
            if resp.status_code == 404:
                log(f"404 Not Found: {url}", "DEBUG")
                return None
                
            if resp.status_code in (403, 429):
                wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                log(f"HTTP {resp.status_code} on {url}. Waiting {wait:.1f}s before retry...", "WARN")
                time.sleep(wait)
                continue
                
            resp.raise_for_status()
            return resp
            
        except Exception as e:
            log(f"Request error on {url}: {e}", "WARN")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                log(f"Giving up on {url} after {max_retries} attempts.", "ERROR")
                return None
    return None


def parse_bookmarks(html_str):
    soup = BeautifulSoup(html_str, "html.parser")
    sources = []
    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        href = a.get("href")
        author_last = extract_author_lastname(title)
        sources.append({
            "title": title,
            "author_lastname": author_last,
            "url": href
        })
    return sources


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
                if book == "Psalm":
                    book = "Psalms"
                chapter, verse = match.group(2), match.group(3)
                structure.setdefault(book, {}).setdefault(chapter, []).append(verse)
        log(f"Successfully loaded {len(structure)} books from bsb.txt.")
    else:
        log("Could not load bsb.txt. Using built-in 66-book chapter count map.", "WARN")
        for book, ch_count in DEFAULT_CHAPTER_COUNTS.items():
            structure[book] = {str(ch): [] for ch in range(1, int(ch_count) + 1)}
    return structure


def save_book_json(filepath, book_name, book_data):
    if not book_data or not book_data.get(book_name):
        log(f"No verse data extracted for {book_name}; skipping file creation.", "WARN")
        return

    # Validate round-trip JSON serialization before writing to disk
    try:
        write_json_atomic(filepath, book_data)
        total_chapters = len(book_data[book_name])
        total_verses = sum(len(v) for v in book_data[book_name].values())
        log(f"SAVED & VERIFIED {filepath} ({total_chapters} chapters, {total_verses} verses)", "SUCCESS")
    except Exception as e:
        log(f"JSON validation failed for {filepath}: {e}", "ERROR")


# =====================================================================
# STUDYLIGHT SCRAPER
# =====================================================================

def get_studylight_books(commentary_url):
    log(f"Discovering available books at {commentary_url}...")
    resp = fetch_url(commentary_url, referer="https://www.studylight.org/commentaries/")
    if not resp:
        return None, {}
        
    soup = BeautifulSoup(resp.text, "html.parser")
    code = commentary_url.rstrip("/").split("/")[-1].replace(".html", "")
    available_books = {}
    
    pattern = re.compile(rf"/commentaries/eng/{re.escape(code)}/([a-z0-9\-]+?)(?:-(\d+))?\.html")
    for a in soup.find_all("a", href=True):
        m = pattern.search(a["href"])
        if m:
            slug = m.group(1)
            if slug in SLUG_TO_BOOK:
                book_name = SLUG_TO_BOOK[slug]
                available_books[book_name] = slug
                
    log(f"Found {len(available_books)} books for StudyLight code '{code}'.")
    return code, available_books


def get_studylight_book_chapters(code, slug, max_chapters, referer_url):
    book_index_url = f"https://www.studylight.org/commentaries/eng/{code}/{slug}.html"
    log(f"Checking available chapters for '{slug}' at {book_index_url}...", "DEBUG")
    resp = fetch_url(book_index_url, referer=referer_url, max_retries=2)
    
    if not resp:
        log(f"Could not load book index for {slug}, falling back to sequential chapter check.", "WARN")
        return list(range(1, int(max_chapters) + 1))

    soup = BeautifulSoup(resp.text, "html.parser")
    chapters = set()
    
    ch_pattern = re.compile(rf"/commentaries/eng/{re.escape(code)}/{re.escape(slug)}-(\d+)\.html")
    for a in soup.find_all("a", href=True):
        m = ch_pattern.search(a["href"])
        if m:
            chapters.add(int(m.group(1)))

    m_self = ch_pattern.search(resp.url)
    if m_self:
        chapters.add(int(m_self.group(1)))

    if not chapters:
        test_parse = parse_studylight_chapter(resp.text)
        if test_parse:
            log(f"Book index {book_index_url} contains direct commentary (1-chapter book).", "DEBUG")
            return ["INDEX_DIRECT", resp.text]

    sorted_chapters = sorted(chapters)
    log(f"Discovered {len(sorted_chapters)} available chapter(s) for '{slug}': {sorted_chapters}", "DEBUG")
    return sorted_chapters


def assign_verses(data, start, end, text):
    """Store commentary under the first verse in a range; subsequent verses
    in the range get a pointer back to the first verse."""
    start = int(start)
    end = int(end) if end else start
    data[str(start)] = text
    for v in range(start + 1, end + 1):
        data.setdefault(str(v), f"See commentary on verse {start}")


def parse_studylight_chapter(html_content):
    """Extracts formatted verse commentary from a StudyLight chapter HTML page."""
    soup = BeautifulSoup(html_content, "html.parser")
    strip_noise_elements(soup)
    verses_data = {}

    # Method 1: Structured commentary-entry blocks
    entries = soup.select(".commentary-entry, .verse-commentary, .commentaries-entry")
    if entries:
        for entry in entries:
            header = entry.find(
                ["h2", "h3", "h4", "a", "span", "div"],
                string=re.compile(r"(?:Verses?|Ver\.?|v\.?)\s*\d+|^\d+:\d+", re.I)
            )
            if header:
                v_match = re.search(
                    r"(?:Verses?|Ver\.?|v\.?|:)\s*(\d+)(?:\s*[\-–]\s*(\d+))?",
                    header.get_text(), re.I
                )
                if v_match:
                    verse_start = v_match.group(1)
                    verse_end = v_match.group(2)
                    header.decompose()
                    formatted_text = extract_rich_text(entry)
                    if formatted_text:
                        assign_verses(verses_data, verse_start, verse_end, formatted_text)

    # Method 2: Sequential Heading / Paragraph extraction
    if not verses_data:
        current_verse = None
        current_verse_end = None
        buffer = []
        content_root = soup.select_one("main, #content-column, .content, article, body")
        if content_root:
            for tag in content_root.find_all(["h2", "h3", "h4", "p", "blockquote", "ul", "ol"]):
                if tag.name == "p" and tag.find_parent("blockquote"):
                    continue

                plain_txt = tag.get_text(" ", strip=True)
                if not plain_txt:
                    continue

                # Stop immediately if we hit StudyLight's footer navigation lists
                if plain_txt.startswith(FOOTER_DOM_STARTERS):
                    break

                v_match = re.match(
                    r"^(?:[1-3]?\s?[A-Za-z]+\s+\d+:|\b(?:Verses?|Ver\.?|v\.?)\s*)"
                    r"(\d+)(?:\s*[\-–]\s*(\d+))?\b[\.\:\-\s]*(.*)",
                    plain_txt,
                    re.I
                )
                if v_match and tag.name in ("h2", "h3", "h4", "p"):
                    if current_verse and buffer:
                        assign_verses(
                            verses_data, current_verse, current_verse_end,
                            clean_formatted_verse("\n\n".join(buffer))
                        )
                    current_verse = v_match.group(1)
                    current_verse_end = v_match.group(2)

                    rich_txt = extract_rich_text(tag)
                    rich_txt = re.sub(
                        r"^(\*\*|\*)?(?:Verses?|Ver\.?|v\.?|\d+:)\s*\d+"
                        r"(?:\s*[\-–]\s*\d+)?\b[\.\:\-\s]*(\*\*|\*)?\s*",
                        "",
                        rich_txt,
                        flags=re.I
                    ).strip()
                    buffer = [rich_txt] if rich_txt else []
                elif current_verse:
                    rich_txt = extract_rich_text(tag)
                    if rich_txt:
                        buffer.append(rich_txt)

            if current_verse and buffer:
                assign_verses(
                    verses_data, current_verse, current_verse_end,
                    clean_formatted_verse("\n\n".join(buffer))
                )

    return verses_data


def scrape_studylight_commentary(source, bible_structure):
    title = source["title"]
    author_last = source["author_lastname"]
    url = source["url"]
    
    log(f"==================================================")
    log(f"Starting StudyLight Commentary: {title} (Author key: '{author_last}')")
    log(f"==================================================")
    
    code, books = get_studylight_books(url)
    if not code or not books:
        log(f"Could not retrieve books for {title}. Skipping.", "ERROR")
        return

    for book_name, slug in books.items():
        target_file = get_target_filepath(author_last, book_name, url)
        if os.path.exists(target_file):
            log(f"File {target_file} already exists. Skipping {book_name}.")
            continue

        log(f"--> Scraping {title} | Book: {book_name} -> {os.path.basename(target_file)}")
        book_payload = {book_name: {}}
        max_chapters = len(bible_structure.get(book_name, {})) or int(DEFAULT_CHAPTER_COUNTS.get(book_name, 150))

        chapters_to_fetch = get_studylight_book_chapters(code, slug, max_chapters, referer_url=url)
        
        if chapters_to_fetch and chapters_to_fetch[0] == "INDEX_DIRECT":
            verses = parse_studylight_chapter(chapters_to_fetch[1])
            if verses:
                book_payload[book_name]["1"] = verses
                log(f"    Parsed Chapter 1 directly from book index ({len(verses)} verses).", "DEBUG")
        else:
            prev_url = f"https://www.studylight.org/commentaries/eng/{code}/{slug}.html"
            for ch in chapters_to_fetch:
                ch_url = f"https://www.studylight.org/commentaries/eng/{code}/{slug}-{ch}.html"
                resp = fetch_url(ch_url, referer=prev_url)
                if not resp:
                    log(f"    Skipping missing/blocked chapter: {book_name} {ch}", "WARN")
                    continue

                chapter_verses = parse_studylight_chapter(resp.text)
                if chapter_verses:
                    book_payload[book_name][str(ch)] = chapter_verses
                    log(f"    Parsed {book_name} Chapter {ch}: {len(chapter_verses)} verses extracted.", "DEBUG")
                else:
                    log(f"    No verse entries matched on {book_name} Chapter {ch}.", "DEBUG")

                prev_url = ch_url
                time.sleep(random.uniform(0.8, 1.8))

        save_book_json(target_file, book_name, book_payload)


# =====================================================================
# ENDURING WORD SCRAPER
# =====================================================================

def get_enduring_word_chapter_links():
    url = "https://enduringword.com/commentary/"
    log(f"Discovering Enduring Word chapter links from {url}...")
    resp = fetch_url(url)
    if not resp:
        return {}
        
    soup = BeautifulSoup(resp.text, "html.parser")
    book_links = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"enduringword\.com/bible-commentary/([a-z0-9\-]+)-(\d+)/?", href)
        if m:
            slug, ch = m.group(1), m.group(2)
            if slug in SLUG_TO_BOOK:
                book_name = SLUG_TO_BOOK[slug]
                book_links.setdefault(book_name, {})[int(ch)] = href
    log(f"Discovered links for {len(book_links)} books on Enduring Word.")
    return book_links


def parse_enduring_word_chapter(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    content = soup.select_one(".entry-content, .avia_textblock, main, article")
    if not content:
        return {}

    strip_noise_elements(content)
    verses_data = {}
    current_verses = []
    buffer = []

    def flush_buffer():
        if current_verses and buffer:
            combined_text = clean_formatted_verse("\n\n".join(buffer))
            if not combined_text:
                return
            start_v = current_verses[0]
            if start_v in verses_data:
                verses_data[start_v] = clean_formatted_verse(
                    verses_data[start_v] + "\n\n" + combined_text
                )
            else:
                verses_data[start_v] = combined_text
            for v in current_verses[1:]:
                verses_data.setdefault(v, f"See commentary on verse {start_v}")

    for elem in content.find_all(["h2", "h3", "h4", "p", "blockquote", "ul", "ol"]):
        if elem.name == "p" and elem.find_parent("blockquote"):
            continue

        plain_text = elem.get_text(" ", strip=True)
        if not plain_text:
            continue

        # Guzik's heading format: "1. (1-4)" or "2. (5)"
        header_match = re.match(r"^(\d+)\.\s*\((\d+)(?:\s*[\-–]\s*(\d+))?\)", plain_text)
        if elem.name in ("h2", "h3", "h4") and header_match:
            flush_buffer()
            buffer = []
            start_v = int(header_match.group(2))
            end_v = int(header_match.group(3)) if header_match.group(3) else start_v
            current_verses = [str(v) for v in range(start_v, end_v + 1)]

            rich_heading = extract_rich_text(elem)
            if rich_heading:
                buffer.append(rich_heading)
        elif current_verses:
            rich_part = extract_rich_text(elem)
            if rich_part:
                buffer.append(rich_part)

    flush_buffer()
    return verses_data


def scrape_enduring_word(source, bible_structure):
    title = source["title"]
    author_last = source["author_lastname"]
    url = source["url"]
    
    log(f"==================================================")
    log(f"Starting Enduring Word Commentary: {title} (Author key: '{author_last}')")
    log(f"==================================================")
    
    discovered = get_enduring_word_chapter_links()
    
    for book_name, slug in BOOK_TO_SLUG.items():
        target_file = get_target_filepath(author_last, book_name, url)
        if os.path.exists(target_file):
            log(f"File {target_file} already exists. Skipping {book_name}.")
            continue

        log(f"--> Scraping {title} | Book: {book_name} -> {os.path.basename(target_file)}")
        book_payload = {book_name: {}}
        
        known_chapters = discovered.get(book_name, {})
        max_ch = len(bible_structure.get(book_name, {})) or int(DEFAULT_CHAPTER_COUNTS.get(book_name, 150))
        chapters_to_iter = sorted(known_chapters.keys()) if known_chapters else list(range(1, max_ch + 1))
        
        prev_url = url
        for ch in chapters_to_iter:
            ch_str = str(ch)
            ew_slug = "psalm" if slug == "psalms" else slug
            ch_url = known_chapters.get(ch, f"https://enduringword.com/bible-commentary/{ew_slug}-{ch_str}/")
            
            resp = fetch_url(ch_url, referer=prev_url)
            if not resp:
                log(f"    Skipping missing/blocked chapter: {book_name} {ch_str}", "WARN")
                continue
                
            chapter_verses = parse_enduring_word_chapter(resp.text)
            if chapter_verses:
                book_payload[book_name][ch_str] = chapter_verses
                log(f"    Parsed {book_name} Chapter {ch_str}: {len(chapter_verses)} verses extracted.", "DEBUG")
            else:
                log(f"    No verses parsed on {book_name} Chapter {ch_str}.", "DEBUG")
                
            prev_url = ch_url
            time.sleep(random.uniform(0.8, 1.5))
            
        save_book_json(target_file, book_name, book_payload)


# =====================================================================
# REPAIR UTILITY FOR ALREADY-DOWNLOADED FILES
# =====================================================================

def clean_existing_json_files():
    """
    Scans OUTPUT_DIR for any existing .json files, strips the 'Passage Guide'
    footer block, leaked HTML tags, and control characters, and re-saves valid JSON.
    """
    if not os.path.exists(OUTPUT_DIR):
        return

    log("Checking existing JSON files in output directory for footer text / invalid chars...")
    for fname in os.listdir(OUTPUT_DIR):
        if not fname.endswith(".json") or fname == "_file_manifest.json":
            continue
        fpath = os.path.join(OUTPUT_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                raw_content = f.read()

            # Replace any raw unescaped control chars inside existing file before loading
            data = json.loads(raw_content, strict=False)
            modified = False

            for book, chapters in data.items():
                if not isinstance(chapters, dict):
                    continue
                for ch, verses in chapters.items():
                    if not isinstance(verses, dict):
                        continue
                    for v, text in list(verses.items()):
                        if isinstance(text, str):
                            cleaned = clean_formatted_verse(text)
                            if cleaned != text:
                                verses[v] = cleaned
                                modified = True

            if modified:
                write_json_atomic(fpath, data)
                log(f"Repaired and cleaned existing file: {fname}", "SUCCESS")
        except Exception as e:
            log(f"Could not repair {fname} ({e}). Deleting so it will be re-scraped cleanly.", "WARN")
            try:
                os.remove(fpath)
            except OSError:
                pass


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    log(f"Output directory initialized at: {os.path.abspath(OUTPUT_DIR)}")
    
    # 1. Automatically clean any files you already scraped in previous runs
    clean_existing_json_files()
    
    # 2. Load Bible structure & bookmark sources
    bible_structure = load_bible_structure(BSB_URL)
    sources = parse_bookmarks(BOOKMARKS_HTML)
    log(f"Parsed {len(sources)} commentary sources from bookmarks.")
    
    # 3. Run scrapers
    for idx, source in enumerate(sources, 1):
        log(f"Processing source {idx}/{len(sources)}: {source['title']}")
        if "studylight.org" in source["url"]:
            scrape_studylight_commentary(source, bible_structure)
        elif "enduringword.com" in source["url"]:
            scrape_enduring_word(source, bible_structure)
        else:
            log(f"Unknown domain for {source['url']}, skipping.", "WARN")

    log("All commentary sources finished processing!", "SUCCESS")


if __name__ == "__main__":
    main()