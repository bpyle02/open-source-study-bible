import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

from flask import Flask, abort, jsonify, render_template


app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
BIBLE_CACHE_FILE = BASE_DIR / "cache" / "bsb_cache.json"
BIBLE_TEXT_FILE = BASE_DIR / "bibles" / "bsb.txt"
COMMENTARIES_DIR = BASE_DIR / "commentaries"
COMMENTARY_TITLES = {
    "henry": "Matthew Henry",
    "jamieson-fausset-brown": "Jamieson-Fausset-Brown",
    "john-calvin": "John Calvin",
    "john-gill": "John Gill",
}


def load_bible():
    if BIBLE_CACHE_FILE.is_file():
        with BIBLE_CACHE_FILE.open(encoding="utf-8") as bible_file:
            payload = json.load(bible_file)
        books = payload.get("book_order")
        bible_data = payload.get("bible_data")
        if not isinstance(books, list) or not isinstance(bible_data, dict):
            raise ValueError(f"Invalid Bible cache format: {BIBLE_CACHE_FILE}")
        return books, bible_data

    if not BIBLE_TEXT_FILE.is_file():
        raise FileNotFoundError(
            f"Bible data is missing: expected {BIBLE_CACHE_FILE} or {BIBLE_TEXT_FILE}"
        )

    bible_data = {}
    book_order = []
    verse_pattern = re.compile(r"^(.+?)\s+(\d+):(\d+)\t(.*)$")
    with BIBLE_TEXT_FILE.open(encoding="utf-8", errors="replace") as bible_file:
        for line in bible_file:
            match = verse_pattern.match(line.rstrip("\r\n"))
            if not match:
                continue
            book, chapter, verse, text = match.groups()
            chapter_num = int(chapter)
            verse_num = int(verse)
            if book not in bible_data:
                bible_data[book] = {}
                book_order.append(book)
            chapter_data = bible_data[book].setdefault(
                str(chapter_num),
                {"chapter_heading": f"{book} {chapter_num}", "blocks": []},
            )
            chapter_data["blocks"].append({
                "type": "paragraph",
                "verses": [{
                    "num": verse_num,
                    "segments": [{"text": text, "red": False, "bold": False}],
                    "footnotes": [],
                }],
            })
    if not book_order:
        raise ValueError(f"No Bible verses found in {BIBLE_TEXT_FILE}")
    return book_order, bible_data


BOOK_ORDER, BIBLE_DATA = load_bible()
COMMENTARY_FILES = sorted(COMMENTARIES_DIR.glob("*.json.gz"))


@lru_cache(maxsize=4)
def load_commentary(path):
    with gzip.open(path, "rt", encoding="utf-8") as commentary_file:
        data = json.load(commentary_file)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid commentary JSON in {path}")
    return data


def normalize_book_name(name):
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def find_commentary_book(data, book_name):
    normalized_name = normalize_book_name(book_name)
    for book in data.get("books", []):
        names = (book.get("name"), book.get("commonName"))
        if any(
            name and normalize_book_name(name) == normalized_name
            for name in names
        ):
            return book.get("id")
    return None


def chapter_record(data, book_id, chapter_num):
    chapters = data.get("chapters", {})
    if isinstance(chapters, list):
        for item in chapters:
            if (item.get("book_id") == book_id
                    and item.get("chapter") == chapter_num):
                record = item.get("data", {})
                return record.get("chapter", record)
        return None
    return chapters.get(f"{book_id} {chapter_num}")


def extract_entries(record):
    if not isinstance(record, dict):
        return []

    content = record.get("content", [])
    entries = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("content", "")
        if isinstance(text, list):
            text = "".join(part for part in text if isinstance(part, str))
        elif not isinstance(text, str):
            text = str(text)
        text = text.strip()
        if not text:
            continue
        number = item.get("number")
        entries.append({
            "verse": number if isinstance(number, int) else None,
            "text": text,
        })
    entries.sort(key=lambda entry: (
        entry["verse"] is None,
        entry["verse"] if entry["verse"] is not None else 0,
    ))
    return entries


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/books")
def get_books():
    books = []
    for book in BOOK_ORDER:
        chapter_numbers = sorted(
            (int(number) for number in BIBLE_DATA.get(book, {})),
        )
        if chapter_numbers:
            books.append({"name": book, "chapters": chapter_numbers})
    return jsonify(books)


@app.route("/api/bible/<path:book>/<int:chapter>")
def get_bible_chapter(book, chapter):
    if book not in BIBLE_DATA or str(chapter) not in BIBLE_DATA[book]:
        abort(404, description=f"Bible passage not found: {book} {chapter}")
    return jsonify(BIBLE_DATA[book][str(chapter)])


@app.route("/api/commentaries/<path:book>/<int:chapter>")
def get_commentaries(book, chapter):
    results = []
    for path in COMMENTARY_FILES:
        data = load_commentary(str(path))
        book_id = find_commentary_book(data, book)
        if book_id is None:
            continue
        record = chapter_record(data, book_id, chapter)
        results.append({
            "id": path.name,
            "author": COMMENTARY_TITLES.get(
                path.stem.removesuffix(".json"), path.stem
            ),
            "entries": extract_entries(record),
        })
    return jsonify(results)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
