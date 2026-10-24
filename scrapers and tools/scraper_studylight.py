import os
import re
import json
import time
import random
import argparse
from datetime import datetime
from bs4 import BeautifulSoup, NavigableString, Tag, Comment
from curl_cffi import requests

BSB_URL = "https://bereanbible.com/bsb.txt"
OUTPUT_DIR = "commentaries_json"

# Browser impersonation profiles supported by curl_cffi
IMPERSONATE_PROFILES = [
    "chrome124",
    "chrome120",
    "chrome119",
    "chrome116",
    "edge101",
    "safari17_0",
    "safari15_5",
]

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


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


# =====================================================================
# CLOUDFLARE-RESILIENT SESSION MANAGER
# =====================================================================

class CloudflareSessionManager:
    def __init__(self):
        self.profile_idx = 0
        self.session = None
        self.warmed_up = False
        self._init_session()

    def _get_current_profile(self):
        return IMPERSONATE_PROFILES[self.profile_idx % len(IMPERSONATE_PROFILES)]

    def _init_session(self, rotate=False):
        if rotate:
            self.profile_idx += 1
        profile = self._get_current_profile()
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
        # Let curl_cffi manage default browser headers to match TLS/HTTP2 fingerprint
        try:
            self.session = requests.Session(impersonate=profile)
        except Exception:
            self.session = requests.Session(impersonate="chrome")
        self.warmed_up = False
        log(f"Initialized curl_cffi session with profile '{profile}'", "DEBUG")

    @staticmethod
    def is_cloudflare_blocked(resp):
        if resp is None:
            return True
        if resp.status_code in (403, 429, 503):
            return True
        text_head = resp.text[:4000].lower()
        if (
            "<title>just a moment...</title>" in text_head
            or "cf-browser-verification" in text_head
            or "challenge-platform" in text_head
            or "attention required! | cloudflare" in text_head
        ):
            return True
        return False

    def warmup(self):
        if self.warmed_up:
            return
        try:
            log("Warming up session on studylight.org homepage...", "DEBUG")
            resp = self.session.get("https://www.studylight.org/", timeout=20)
            if not self.is_cloudflare_blocked(resp):
                self.warmed_up = True
                time.sleep(random.uniform(1.0, 2.0))
        except Exception as e:
            log(f"Warmup warning: {e}", "DEBUG")

    def _fallback_browser_fetch(self, url):
        """
        Optional fallback if DrissionPage or Playwright is installed locally
        and Cloudflare forces a hard interactive/JS Turnstile challenge.
        """
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            log(f"Attempting headless browser bypass via DrissionPage for {url}...", "WARN")
            co = ChromiumOptions().headless(True)
            page = ChromiumPage(co)
            page.get(url)
            time.sleep(4)
            html = page.html
            cookies = {c["name"]: c["value"] for c in page.cookies()}
            page.quit()
            if cookies:
                self.session.cookies.update(cookies)
            if html and "just a moment..." not in html[:2000].lower():
                return html
        except ImportError:
            pass
        except Exception as e:
            log(f"Browser fallback failed: {e}", "DEBUG")
        return None

    def get(self, url, referer=None, max_retries=5):
        if "studylight.org" in url and not self.warmed_up:
            self.warmup()

        for attempt in range(1, max_retries + 1):
            headers = {}
            if referer:
                headers["Referer"] = referer

            try:
                log(f"GET {url} (Attempt {attempt}/{max_retries}, Profile: {self._get_current_profile()})", "DEBUG")
                resp = self.session.get(url, headers=headers, timeout=25)

                if resp.status_code == 404:
                    return None

                if self.is_cloudflare_blocked(resp):
                    wait_time = (2 ** attempt) + random.uniform(1.5, 3.5)
                    log(
                        f"Cloudflare challenge/block (HTTP {resp.status_code}) on {url}. "
                        f"Rotating fingerprint & sleeping {wait_time:.1f}s...",
                        "WARN"
                    )
                    time.sleep(wait_time)
                    self._init_session(rotate=True)
                    if "studylight.org" in url:
                        self.warmup()
                    continue

                resp.raise_for_status()
                return resp.text

            except Exception as e:
                wait_time = (2 ** attempt) + random.uniform(1.0, 2.5)
                log(f"Request error ({e}) on {url}. Retrying in {wait_time:.1f}s...", "WARN")
                time.sleep(wait_time)
                if attempt >= 2:
                    self._init_session(rotate=True)

        # Final fallback to real browser if installed
        fallback_html = self._fallback_browser_fetch(url)
        if fallback_html:
            return fallback_html

        log(f"Exhausted all {max_retries} attempts for {url}", "ERROR")
        return None


cf_client = CloudflareSessionManager()


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


# =====================================================================
# HTML STYLING & MARKDOWN CONVERSION
# =====================================================================

def clean_formatted_verse(text):
    if not text:
        return ""
    text = re.sub(r"[\ud800-\udfff]", "", text)
    text = text.replace("\u2028", "\n").replace("\u2029", "\n").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n\t *", "\n\t", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_node_to_markdown(node):
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return re.sub(r"[ \r\n]+", " ", str(node))
    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    if name in ("script", "style", "noscript", "iframe"):
        return ""
    if is_return_to_top(node):
        return ""
    if name == "br":
        return "\n"
    if name == "hr":
        return "\n---\n"

    inner = "".join(html_node_to_markdown(child) for child in node.children)
    if name in ("b", "strong"):
        return f" **{inner.strip()}** " if inner.strip() else ""
    if name in ("i", "em"):
        return f" *{inner.strip()}* " if inner.strip() else ""
    if name == "u":
        return f" <u>{inner.strip()}</u> " if inner.strip() else ""
    if name in ("sup", "sub"):
        return f"<{name}>{inner.strip()}</{name}>" if inner.strip() else ""
    if name == "li":
        return f"\n\t• {inner.strip()}" if inner.strip() else ""
    if name in ("ul", "ol"):
        return f"\n{inner.strip()}\n\n"
    if name == "blockquote":
        stripped = inner.strip()
        if not stripped:
            return ""
        tabbed = "\n".join(f"\t{line.strip()}" for line in stripped.splitlines() if line.strip())
        return f"\n\n{tabbed}\n\n"
    if name in ("p", "div", "section", "article"):
        return f"{inner.strip()}\n\n" if inner.strip() else ""
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return f"\n\n**{inner.strip()}**\n\n" if inner.strip() else ""
    return inner


# =====================================================================
# VERSATILE SECTION PARSING LOGIC
# =====================================================================

def is_return_to_top(node):
    """Checks if a node is or contains the StudyLight 'Back to top' marker."""
    if not isinstance(node, Tag):
        return False
    classes = node.get("class") or []
    if "return-to-top-div" in classes or "ctp-top" in classes or "return-to-top-link" in classes:
        return True
    if node.name == "a" and (node.get("href") == "#TopofPage" or "back to top" in node.get_text(" ", strip=True).lower()):
        return True
    return False


def is_entry_header(node):
    """Checks if a node is a commentary section header."""
    return isinstance(node, Tag) and node.name == "h3" and "commentaries-entry-number" in (node.get("class") or [])


def extract_section_nodes(h3_tag):
    nodes = []
    curr = h3_tag.next_sibling
    hit_boundary = False

    while curr:
        if is_return_to_top(curr) or is_entry_header(curr):
            hit_boundary = True
            break
        if isinstance(curr, Tag) and (curr.select_one(".return-to-top-div, .ctp-top") or curr.select_one("h3.commentaries-entry-number")):
            for child in curr.children:
                if is_return_to_top(child) or is_entry_header(child):
                    break
                nodes.append(child)
            hit_boundary = True
            break
        nodes.append(curr)
        curr = curr.next_sibling

    if not hit_boundary and h3_tag.parent and h3_tag.parent.name not in ("body", "main", "article"):
        curr = h3_tag.parent.next_sibling
        while curr:
            if is_return_to_top(curr) or is_entry_header(curr):
                break
            if isinstance(curr, Tag) and (curr.select_one(".return-to-top-div, .ctp-top") or curr.select_one("h3.commentaries-entry-number")):
                for child in curr.children:
                    if is_return_to_top(child) or is_entry_header(child):
                        break
                    nodes.append(child)
                break
            nodes.append(curr)
            curr = curr.next_sibling

    return nodes


def assign_section(verses_data, h3_tag, formatted_text):
    header_text = h3_tag.get_text(" ", strip=True)
    a_tag = h3_tag.find("a")
    data_entry = (a_tag.get("data-entry") or a_tag.get("name") or "") if a_tag else ""

    v_match = (
        re.search(r"(?:verses?|ver\.?|v\.?)\s*(\d+)(?:\s*[\-–—]\s*(\d+))?", header_text, re.I)
        or re.search(r"verse-(\d+)(?:-(\d+))?", data_entry, re.I)
    )

    if v_match:
        start = int(v_match.group(1))
        end = int(v_match.group(2)) if v_match.group(2) else start
        key = str(start)
        verses_data[key] = f"{verses_data[key]}\n\n{formatted_text}" if key in verses_data else formatted_text
        for v in range(start + 1, end + 1):
            verses_data.setdefault(str(v), f"See commentary on verse {start}")
        return

    if "intro" in header_text.lower() or "intro" in data_entry.lower() or "overview" in header_text.lower():
        key = "Introduction"
    else:
        key = header_text if header_text else "Introduction"

    verses_data[key] = f"{verses_data[key]}\n\n{formatted_text}" if key in verses_data else formatted_text


def parse_studylight_chapter(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    verses_data = {}

    headers = soup.find_all("h3", class_="commentaries-entry-number")
    for h3 in headers:
        section_nodes = extract_section_nodes(h3)
        raw_md = "".join(html_node_to_markdown(node) for node in section_nodes)
        formatted_text = clean_formatted_verse(raw_md)
        if formatted_text:
            assign_section(verses_data, h3, formatted_text)

    return verses_data


# =====================================================================
# NETWORK & FILE OPERATIONS
# =====================================================================

def write_json_atomic(filepath, data):
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    json.loads(json_str)
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(json_str)
    os.replace(tmp_path, filepath)


def fetch_url(url, referer=None, max_retries=5):
    return cf_client.get(url, referer=referer, max_retries=max_retries)


def load_bible_structure(bsb_url):
    structure = {}
    log(f"Attempting to load Bible structure from {bsb_url}...")
    try:
        # Use a separate, isolated request so we don't pollute the StudyLight session
        resp = requests.get(bsb_url, impersonate="chrome", timeout=20)
        if resp and resp.status_code == 200:
            ref_pattern = re.compile(r"^([1-3]?\s?[A-Za-z\s]+)\s+(\d+):(\d+)\t")
            for line in resp.text.splitlines():
                match = ref_pattern.match(line)
                if match:
                    book = match.group(1).strip()
                    book = "Psalms" if book == "Psalm" else book
                    structure.setdefault(book, {}).setdefault(match.group(2), []).append(match.group(3))
            log(f"Successfully loaded {len(structure)} books from bsb.txt.")
            return structure
    except Exception as e:
        log(f"Error fetching bsb.txt: {e}", "DEBUG")

    log("Could not load bsb.txt. Using built-in 66-book chapter count map.", "WARN")
    for book, ch_count in DEFAULT_CHAPTER_COUNTS.items():
        structure[book] = {str(ch): [] for ch in range(1, int(ch_count) + 1)}
    return structure


def save_book_json(filepath, book_name, book_data):
    if not book_data or not book_data.get(book_name):
        return
    try:
        write_json_atomic(filepath, book_data)
        log(f"SAVED & VERIFIED {filepath}", "SUCCESS")
    except Exception as e:
        log(f"JSON validation failed for {filepath}: {e}", "ERROR")


def get_studylight_books(commentary_url):
    log(f"Discovering available books at {commentary_url}...")
    html_text = fetch_url(commentary_url, referer="https://www.studylight.org/commentaries/")
    if not html_text:
        return None, {}

    soup = BeautifulSoup(html_text, "html.parser")
    code = commentary_url.rstrip("/").split("/")[-1].replace(".html", "")
    available_books = {}

    pattern = re.compile(rf"/commentaries/eng/{re.escape(code)}/([a-z0-9\-]+?)(?:-(\d+))?\.html")
    for a in soup.find_all("a", href=True):
        if (m := pattern.search(a["href"])) and m.group(1) in SLUG_TO_BOOK:
            available_books[SLUG_TO_BOOK[m.group(1)]] = m.group(1)

    log(f"Found {len(available_books)} books for StudyLight code '{code}'.")
    return code, available_books


def get_studylight_book_chapters(code, slug, max_chapters, referer_url):
    book_index_url = f"https://www.studylight.org/commentaries/eng/{code}/{slug}.html"
    html_text = fetch_url(book_index_url, referer=referer_url, max_retries=4)
    if not html_text:
        return list(range(1, int(max_chapters) + 1))

    soup = BeautifulSoup(html_text, "html.parser")
    chapters = set()
    ch_pattern = re.compile(rf"/commentaries/eng/{re.escape(code)}/{re.escape(slug)}-(\d+)\.html")
    for a in soup.find_all("a", href=True):
        if m := ch_pattern.search(a["href"]):
            chapters.add(int(m.group(1)))

    if not chapters and parse_studylight_chapter(html_text):
        return ["INDEX_DIRECT", html_text]

    return sorted(chapters) if chapters else list(range(1, int(max_chapters) + 1))


def scrape_studylight_commentary(source, bible_structure):
    title, author_last, url = source["title"], source["author_lastname"], source["url"]
    log("==================================================")
    log(f"Starting StudyLight Commentary: {title}")
    log("==================================================")

    code, books = get_studylight_books(url)
    if not code or not books:
        return

    for book_name, slug in books.items():
        target_file = get_target_filepath(author_last, book_name, url)
        if os.path.exists(target_file):
            continue

        log(f"--> Scraping {title} | Book: {book_name}")
        book_payload = {book_name: {}}
        max_chapters = len(bible_structure.get(book_name, {})) or int(DEFAULT_CHAPTER_COUNTS.get(book_name, 150))
        chapters_to_fetch = get_studylight_book_chapters(code, slug, max_chapters, referer_url=url)

        if chapters_to_fetch and chapters_to_fetch[0] == "INDEX_DIRECT":
            if verses := parse_studylight_chapter(chapters_to_fetch[1]):
                book_payload[book_name]["1"] = verses
        else:
            prev_url = f"https://www.studylight.org/commentaries/eng/{code}/{slug}.html"
            for ch in chapters_to_fetch:
                ch_url = f"https://www.studylight.org/commentaries/eng/{code}/{slug}-{ch}.html"
                if not (html_text := fetch_url(ch_url, referer=prev_url)):
                    continue
                if chapter_verses := parse_studylight_chapter(html_text):
                    book_payload[book_name][str(ch)] = chapter_verses
                prev_url = ch_url
                time.sleep(random.uniform(1.0, 2.2))

        save_book_json(target_file, book_name, book_payload)


def main():
    parser = argparse.ArgumentParser(description="Scrape StudyLight commentaries.")
    parser.add_argument("input", help="Comma-separated list of StudyLight URLs or path to a .txt file containing URLs.")
    args = parser.parse_args()

    if os.path.isfile(args.input):
        with open(args.input, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
    else:
        urls = [u.strip() for u in args.input.split(",") if u.strip()]

    if not urls:
        print("No valid URLs provided.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    bible_structure = load_bible_structure(BSB_URL)

    sources = []
    for url in urls:
        m = re.search(r"/commentaries/eng/([^/.]+)\.html", url)
        code = m.group(1) if m else "unknown"
        sources.append({
            "title": f"StudyLight - {code.upper()}",
            "author_lastname": code,
            "url": url
        })

    for idx, source in enumerate(sources, 1):
        log(f"Processing source {idx}/{len(sources)}: {source['url']}")
        scrape_studylight_commentary(source, bible_structure)
        time.sleep(random.uniform(1.5, 3.0))

    log("All StudyLight sources finished processing!", "SUCCESS")


if __name__ == "__main__":
    main()