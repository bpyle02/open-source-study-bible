import gzip
import json
import os
import re
import sqlite3
import tempfile
import threading
import zlib
from contextlib import closing
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request


app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
BIBLES_DIR = BASE_DIR / "bibles"
COMMENTARIES_DIR = BASE_DIR / "commentaries"
SERMONS_DIR = BASE_DIR / "sermons"
FOOTNOTES_DIR = BASE_DIR / "footnotes"
CROSS_REFERENCES_DIR = BASE_DIR / "cross-references"
MARKUP_DIR = BASE_DIR / "markup"
MARKUP_FILE = MARKUP_DIR / "verse-markup.json.gz"
DATABASE_DIR = BASE_DIR / "cache"
DATABASE_FILE = DATABASE_DIR / "reader.sqlite3"
DATABASE_SCHEMA_VERSION = "11"
TRANSLATION_NAMES = {
    "BSB": "Berean Standard Bible",
    "ENGWEBP": "World English Bible",
    "KJV": "King James Version",
}
CROSS_REFERENCE_BOOK_ALIASES = {
    "1kgs": "1kings",
    "2kgs": "2kings",
    "jas": "james",
    "phil": "philippians",
    "phlm": "philemon",
}


TRANSLATION_FILES = {
    path.name.removesuffix("_translation.json.gz").upper(): path
    for path in sorted(BIBLES_DIR.glob("*_translation.json.gz"))
}
COMMENTARY_FILES = sorted(COMMENTARIES_DIR.glob("*.json.gz"))
SERMON_FILES = sorted(SERMONS_DIR.glob("*.json.gz"))
FOOTNOTE_FILES = sorted(FOOTNOTES_DIR.glob("*.json.gz"))
CROSS_REFERENCE_FILES = sorted(CROSS_REFERENCES_DIR.glob("*.json.gz"))
MARKUP_LOCK = threading.Lock()
MARKUP_TYPES = {"highlight", "underline", "bracket"}
MARKUP_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


def normalize_book_name(name):
    return re.sub(r"[^a-z0-9]", "", name.casefold())


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
            "format": "markdown",
        })
    entries.sort(key=lambda entry: (
        entry["verse"] is None,
        entry["verse"] if entry["verse"] is not None else 0,
    ))
    return entries


def encode_payload(payload):
    return zlib.compress(
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        level=1,
    )


def parse_reference(reference):
    match = re.fullmatch(r"(.+)\.(\d+)\.(\d+)", reference)
    if match is None:
        raise ValueError(f"Invalid cross-reference: {reference}")
    book, chapter, verse = match.groups()
    return book, int(chapter), int(verse)


def format_cross_reference(start, end, book_names):
    start_book, start_chapter, start_verse = start
    start_label = f"{book_names[start_book]} {start_chapter}:{start_verse}"
    if end is None:
        return start_label

    end_book, end_chapter, end_verse = end
    if start_book == end_book and start_chapter == end_chapter:
        end_label = str(end_verse)
    elif start_book == end_book:
        end_label = f"{end_chapter}:{end_verse}"
    else:
        end_label = f"{book_names[end_book]} {end_chapter}:{end_verse}"
    return f"{start_label}–{end_label}"


def normalize_cross_reference_source_id(source_name):
    slug = re.sub(r"[^a-z0-9]+", "-", (source_name or "custom").casefold())
    return slug.strip("-") or "custom"


def load_footnote_sources():
    sources = {}
    for path in sorted(FOOTNOTES_DIR.glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as source_file:
            data = json.load(source_file)
        if not isinstance(data, dict):
            continue
        translation_id = data.get("translation_id") or data.get("translationId")
        if not isinstance(translation_id, str) or not translation_id.strip():
            translation_id = path.name.rsplit("_", 1)[0].upper()
        translation_id = translation_id.upper()
        notes = data.get("footnotes", [])
        if not isinstance(notes, list):
            notes = []
        if not notes:
            for chapter in data.get("chapters", []):
                if not isinstance(chapter, dict):
                    continue
                book_id = chapter.get("book_id") or chapter.get("bookId")
                chapter_num = chapter.get("chapter")
                chapter_notes = chapter.get("footnotes") or chapter.get("notes") or []
                if not isinstance(chapter_notes, list):
                    continue
                for note in chapter_notes:
                    if isinstance(note, dict):
                        note = dict(note)
                        if isinstance(book_id, str) and book_id:
                            note.setdefault("book_id", book_id)
                        if isinstance(chapter_num, int):
                            note.setdefault("chapter", chapter_num)
                        notes.append(note)
        if notes:
            sources.setdefault(translation_id, []).extend(notes)
    return sources


def make_bible_chapter(source, book_name, chapter_num, extra_footnotes=None):
    extra_footnotes = extra_footnotes or []
    footnotes_by_id = {}
    footnotes_by_verse = {}
    for note in [*source.get("footnotes", []), *extra_footnotes]:
        note_id = note.get("noteId")
        reference = note.get("reference", {})
        verse_num = reference.get("verse")
        if (not isinstance(verse_num, int)
                and isinstance(note.get("verse"), int)):
            verse_num = note.get("verse")
        text = note.get("text")
        caller = note.get("caller", "")
        if isinstance(note_id, int):
            footnotes_by_id[note_id] = {
                "caller": caller,
                "text": text if isinstance(text, str) else "",
            }
        if isinstance(verse_num, int) and isinstance(text, str):
            footnotes_by_verse.setdefault(verse_num, []).append(
                f"{caller} {text}".strip()
            )

    blocks = []
    verses = []

    def flush_verses():
        if verses:
            blocks.append({"type": "paragraph", "verses": verses.copy()})
            verses.clear()

    for item in source.get("content", []):
        item_type = item.get("type")
        if item_type == "verse":
            verse_num = item.get("number")
            if not isinstance(verse_num, int):
                continue
            segments = []
            inline_note_ids = set()
            last_poem = None
            for part in item.get("content", []):
                if isinstance(part, str):
                    segments.append({
                        "text": part,
                        "red": False,
                        "bold": False,
                    })
                elif isinstance(part, dict):
                    part_text = part.get("text")
                    if isinstance(part_text, str):
                        poem = part.get("poem")
                        if (isinstance(poem, int) and isinstance(last_poem, int)
                                and poem != last_poem
                                and (not segments or not segments[-1]["text"].endswith("\n"))):
                            segments.append({
                                "text": "\n",
                                "red": False,
                                "bold": False,
                            })
                        segments.append({
                            "text": part_text,
                            "red": False,
                            "bold": False,
                        })
                        if isinstance(poem, int):
                            last_poem = poem
                    if part.get("lineBreak"):
                        if not segments or not segments[-1]["text"].endswith("\n"):
                            segments.append({
                                "text": "\n",
                                "red": False,
                                "bold": False,
                            })
                    note_id = part.get("noteId")
                    if isinstance(note_id, int):
                        inline_note_ids.add(note_id)
                        note = footnotes_by_id.get(note_id, {})
                        segments.append({
                            "text": note.get("caller") or "\u2020",
                            "red": False,
                            "bold": False,
                            "fn": True,
                        })

            verse_footnotes = footnotes_by_verse.get(verse_num, [])
            if inline_note_ids:
                verse_footnotes = list(verse_footnotes)
                for note_id in inline_note_ids:
                    note = footnotes_by_id.get(note_id)
                    if note and note["text"]:
                        formatted_note = f'{note["caller"]} {note["text"]}'.strip()
                        if formatted_note not in verse_footnotes:
                            verse_footnotes.append(formatted_note)
            if verse_footnotes and not inline_note_ids:
                caller = next(
                    (note.get("caller") for note in source.get("footnotes", [])
                     if note.get("reference", {}).get("verse") == verse_num
                     and note.get("caller")),
                    "\u2020",
                )
                segments.append({
                    "text": caller,
                    "red": False,
                    "bold": False,
                    "fn": True,
                })
            verses.append({
                "num": verse_num,
                "segments": segments,
                "footnotes": verse_footnotes,
            })
        elif item_type == "line_break":
            flush_verses()
        elif item_type in ("heading", "hebrew_subtitle"):
            flush_verses()
            text = "".join(
                part for part in item.get("content", [])
                if isinstance(part, str)
            ).strip()
            if text:
                blocks.append({"type": "heading", "text": text})
    flush_verses()
    return {
        "chapter_heading": f"{book_name} {chapter_num}",
        "blocks": blocks,
    }


def source_manifest():
    files = sorted(
        (*BIBLES_DIR.glob("*_translation.json.gz"),
         *COMMENTARIES_DIR.glob("*.json.gz"),
         *SERMONS_DIR.glob("*.json.gz"),
         *FOOTNOTES_DIR.glob("*.json.gz"),
         *CROSS_REFERENCES_DIR.glob("*.json.gz")),
        key=lambda path: str(path.relative_to(BASE_DIR)).casefold(),
    )
    return json.dumps([
        {
            "path": str(path.relative_to(BASE_DIR)),
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in files
    ], separators=(",", ":"))


def read_cross_reference_data(path):
    with gzip.open(path, "rt", encoding="utf-8") as source_file:
        data = json.load(source_file)
    if isinstance(data, list):
        return {
            "source": path.stem,
            "label": path.stem.replace("_", " ").title(),
            "references": data,
            "notes": [],
        }
    if isinstance(data, dict):
        source_name = data.get("source") or data.get("name") or path.stem
        label = data.get("label") or data.get("title") or source_name
        refs = data.get("references")
        if refs is None:
            refs = data.get("cross_references") or data.get("entries") or []
        return {
            "source": source_name,
            "label": label,
            "references": refs,
            "notes": data.get("notes") or [],
        }
    raise ValueError(f"Invalid cross-reference source JSON: {path}")


def iter_cross_reference_records(source_name, reference_data, book_names):
    references = reference_data.get("references") or []
    if not isinstance(references, list):
        return []

    records = []
    for item in references:
        if isinstance(item, dict):
            source_reference = item.get("source") or item.get("source_reference")
            target_reference = item.get("target") or item.get("target_reference")
            votes = item.get("votes", item.get("weight", 1))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            source_reference, target_reference = item[:2]
            votes = item[2] if len(item) >= 3 else 1
        else:
            continue
        if not isinstance(source_reference, str) or not isinstance(target_reference, str):
            continue
        try:
            source = parse_reference(source_reference)
            target_parts = target_reference.split("-", maxsplit=1)
            target = parse_reference(target_parts[0])
            target_end = None
            if len(target_parts) == 2:
                target_end = parse_reference(target_parts[1])
            source_book = resolve_book_name(source[0], book_names)
            target_book = resolve_book_name(target[0], book_names)
            reference_label = format_cross_reference(
                (target_book, target[1], target[2]),
                (
                    (
                        resolve_book_name(target_end[0], book_names),
                        target_end[1],
                        target_end[2],
                    ) if target_end is not None else None
                ),
                book_names,
            )
            records.append((
                normalize_cross_reference_source_id(source_name),
                source_book,
                source[1],
                source[2],
                reference_label,
                target_book,
                target[1],
                target[2],
                int(votes),
            ))
        except (TypeError, ValueError):
            continue
    return records


def resolve_book_name(abbreviation, book_names):
    if abbreviation in book_names:
        return abbreviation
    normalized = normalize_book_name(abbreviation)
    target_name = CROSS_REFERENCE_BOOK_ALIASES.get(normalized, normalized)
    matches = [
        book_id for book_id, name in book_names.items()
        if normalize_book_name(name).startswith(target_name)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Could not map cross-reference book abbreviation: {abbreviation}"
        )
    return matches[0]


def get_cross_reference_sources():
    sources = []
    for path in CROSS_REFERENCE_FILES:
        data = read_cross_reference_data(path)
        source_name = data.get("source") or path.stem
        label = data.get("label") or source_name
        sources.append({
            "id": normalize_cross_reference_source_id(source_name),
            "label": str(label),
            "path": str(path.relative_to(BASE_DIR)),
        })
    return sources


def database_is_current(manifest):
    if not DATABASE_FILE.is_file():
        return False
    try:
        with closing(sqlite3.connect(DATABASE_FILE)) as connection:
            metadata = dict(connection.execute(
                "SELECT key, value FROM metadata"
            ).fetchall())
    except sqlite3.DatabaseError:
        return False
    return (
        metadata.get("schema_version") == DATABASE_SCHEMA_VERSION
        and metadata.get("source_manifest") == manifest
    )


def build_database(target, manifest):
    with closing(sqlite3.connect(target)) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE bible_books (
                translation_id TEXT NOT NULL,
                book_id TEXT NOT NULL,
                name TEXT NOT NULL,
                book_order INTEGER NOT NULL,
                PRIMARY KEY (translation_id, book_id)
            );
            CREATE TABLE bible_chapters (
                translation_id TEXT NOT NULL,
                book_id TEXT NOT NULL,
                chapter INTEGER NOT NULL,
                payload BLOB NOT NULL,
                PRIMARY KEY (translation_id, book_id, chapter),
                FOREIGN KEY (translation_id, book_id)
                    REFERENCES bible_books (translation_id, book_id)
            );
            CREATE TABLE commentaries (
                commentary_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                date_written TEXT NOT NULL,
                sort_order INTEGER NOT NULL
            );
            CREATE TABLE commentary_books (
                commentary_id TEXT NOT NULL,
                book_id TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                PRIMARY KEY (commentary_id, normalized_name),
                FOREIGN KEY (commentary_id)
                    REFERENCES commentaries (commentary_id)
            );
            CREATE TABLE commentary_chapters (
                commentary_id TEXT NOT NULL,
                book_id TEXT NOT NULL,
                chapter INTEGER NOT NULL,
                entries BLOB NOT NULL,
                PRIMARY KEY (commentary_id, book_id, chapter),
                FOREIGN KEY (commentary_id)
                    REFERENCES commentaries (commentary_id)
            );
            CREATE TABLE sermons (
                sermon_id TEXT PRIMARY KEY,
                source_file TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                date_written TEXT NOT NULL,
                text TEXT NOT NULL,
                sort_order INTEGER NOT NULL
            );
            CREATE TABLE sermon_references (
                sermon_id TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                book_name TEXT NOT NULL,
                chapter INTEGER NOT NULL,
                verse INTEGER NOT NULL,
                PRIMARY KEY (sermon_id, normalized_name, chapter, verse),
                FOREIGN KEY (sermon_id) REFERENCES sermons (sermon_id)
            );
            CREATE INDEX commentary_books_by_name
                ON commentary_books (normalized_name, commentary_id);
            CREATE INDEX sermon_references_by_passage
                ON sermon_references (normalized_name, chapter, verse);
            CREATE TABLE cross_references (
                source_name TEXT NOT NULL,
                source_book_id TEXT NOT NULL,
                source_chapter INTEGER NOT NULL,
                source_verse INTEGER NOT NULL,
                target_reference TEXT NOT NULL,
                target_book_id TEXT NOT NULL,
                target_chapter INTEGER NOT NULL,
                target_verse INTEGER NOT NULL,
                votes INTEGER NOT NULL,
                PRIMARY KEY (
                    source_name, source_book_id, source_chapter, source_verse,
                    target_reference
                )
            ) WITHOUT ROWID;
            CREATE TABLE cross_reference_notes (
                source_name TEXT NOT NULL,
                source_book_id TEXT NOT NULL,
                source_chapter INTEGER NOT NULL,
                source_verse INTEGER NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (
                    source_name, source_book_id, source_chapter, source_verse
                )
            ) WITHOUT ROWID;
        """)
        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            (
                ("schema_version", DATABASE_SCHEMA_VERSION),
                ("source_manifest", manifest),
            ),
        )

        translation_footnotes = load_footnote_sources()
        for translation_id, path in TRANSLATION_FILES.items():
            with gzip.open(path, "rt", encoding="utf-8") as source_file:
                data = json.load(source_file)
            if (not isinstance(data, dict)
                    or not isinstance(data.get("books"), list)
                    or not isinstance(data.get("chapters"), list)):
                raise ValueError(f"Invalid Bible translation JSON: {path}")

            book_names = {}
            for book_order, book in enumerate(data["books"]):
                book_id = book.get("id")
                if not isinstance(book_id, str) or not book_id:
                    continue
                name = book.get("name") or book.get("commonName") or book_id
                book_names[book_id] = name
                connection.execute(
                    "INSERT OR REPLACE INTO bible_books "
                    "(translation_id, book_id, name, book_order) VALUES (?, ?, ?, ?)",
                    (translation_id, book_id, name, book_order),
                )

            notes_by_chapter = {}
            for note in translation_footnotes.get(translation_id, []):
                chapter_num = note.get("chapter")
                book_id = note.get("book_id") or note.get("bookId")
                if (isinstance(book_id, str)
                        and book_id
                        and isinstance(chapter_num, int)):
                    notes_by_chapter.setdefault((book_id, chapter_num), []).append(note)

            for item in data["chapters"]:
                book_id = item.get("book_id")
                chapter = item.get("chapter")
                if (not isinstance(book_id, str)
                        or book_id not in book_names
                        or not isinstance(chapter, int)):
                    continue
                chapter_data = item.get("data", {})
                source = chapter_data.get("chapter", {})
                payload = encode_payload(make_bible_chapter(
                    source,
                    book_names[book_id],
                    chapter,
                    notes_by_chapter.get((book_id, chapter), []),
                ))
                connection.execute(
                    "INSERT OR REPLACE INTO bible_chapters "
                    "(translation_id, book_id, chapter, payload) VALUES (?, ?, ?, ?)",
                    (translation_id, book_id, chapter, payload),
                )

        for sort_order, path in enumerate(COMMENTARY_FILES):
            commentary_id = path.name
            with gzip.open(path, "rt", encoding="utf-8") as source_file:
                data = json.load(source_file)
            if not isinstance(data, dict):
                raise ValueError(f"Invalid commentary JSON in {path}")
            metadata = data.get("metadata")
            if not isinstance(metadata, dict):
                raise ValueError(f"Missing commentary metadata in {path}")
            title = metadata.get("title")
            author = metadata.get("author")
            date_written = metadata.get("date_written")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (title, author, date_written)
            ):
                raise ValueError(f"Invalid commentary metadata in {path}")

            connection.execute(
                "INSERT INTO commentaries "
                "(commentary_id, title, author, date_written, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (commentary_id, title, author, date_written, sort_order),
            )
            book_ids = {}
            for book in data.get("books", []):
                book_id = book.get("id")
                if not isinstance(book_id, str) or not book_id:
                    continue
                for name in (book.get("name"), book.get("commonName")):
                    if isinstance(name, str) and name:
                        normalized_name = normalize_book_name(name)
                        if normalized_name:
                            connection.execute(
                                "INSERT OR IGNORE INTO commentary_books "
                                "(commentary_id, book_id, normalized_name) "
                                "VALUES (?, ?, ?)",
                                (commentary_id, book_id, normalized_name),
                            )
                book_ids[book_id] = True

            chapters = data.get("chapters", {})
            if isinstance(chapters, list):
                chapter_records = (
                    (item.get("book_id"), item.get("chapter"), item.get("data", {}))
                    for item in chapters
                )
            elif isinstance(chapters, dict):
                chapter_records = (
                    (key.rsplit(" ", 1)[0], int(key.rsplit(" ", 1)[1]), value)
                    for key, value in chapters.items()
                    if " " in key and key.rsplit(" ", 1)[1].isdigit()
                )
            else:
                chapter_records = ()

            for book_id, chapter, record_data in chapter_records:
                if (book_id not in book_ids or not isinstance(chapter, int)
                        or not isinstance(record_data, dict)):
                    continue
                record = record_data.get("chapter", record_data)
                entries = extract_entries(record)
                connection.execute(
                    "INSERT OR REPLACE INTO commentary_chapters "
                    "(commentary_id, book_id, chapter, entries) VALUES (?, ?, ?, ?)",
                    (commentary_id, book_id, chapter, encode_payload(entries)),
                )

        sermon_sort_order = 0
        for path in SERMON_FILES:
            with gzip.open(path, "rt", encoding="utf-8") as source_file:
                data = json.load(source_file)
            if (not isinstance(data, dict)
                    or not isinstance(data.get("metadata"), dict)
                    or not isinstance(data.get("sermons"), list)):
                raise ValueError(f"Invalid sermon JSON: {path}")

            for field in ("title", "author", "date_written"):
                value = data["metadata"].get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"Invalid sermon metadata in {path}: {field}")

            for sermon_index, sermon in enumerate(data["sermons"]):
                if not isinstance(sermon, dict):
                    raise ValueError(f"Invalid sermon record in {path}")
                title = sermon.get("title")
                author = sermon.get("author")
                date_written = sermon.get("date_written")
                text = sermon.get("text")
                references = sermon.get("references")
                if (not all(isinstance(value, str) and value.strip()
                            for value in (title, author, date_written, text))
                        or not isinstance(references, list)
                        or not references):
                    raise ValueError(f"Invalid sermon record in {path}")

                sermon_id = f"{path.name}:{sermon_index}"
                connection.execute(
                    "INSERT INTO sermons "
                    "(sermon_id, source_file, title, author, date_written, "
                    "text, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        sermon_id, path.name, title, author, date_written,
                        text, sermon_sort_order,
                    ),
                )
                sermon_sort_order += 1
                for reference in references:
                    if not isinstance(reference, dict):
                        raise ValueError(f"Invalid sermon reference in {path}")
                    book_name = reference.get("book")
                    chapter = reference.get("chapter")
                    verse = reference.get("verse")
                    if (not isinstance(book_name, str) or not book_name.strip()
                            or not isinstance(chapter, int)
                            or not isinstance(verse, int)):
                        raise ValueError(f"Invalid sermon reference in {path}")
                    connection.execute(
                        "INSERT INTO sermon_references "
                        "(sermon_id, normalized_name, book_name, chapter, verse) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            sermon_id, normalize_book_name(book_name),
                            book_name, chapter, verse,
                        ),
                    )

        book_rows = connection.execute(
            "SELECT book_id, name FROM bible_books WHERE translation_id = ?",
            ("BSB",),
        ).fetchall()
        book_names = {row[0]: row[1] for row in book_rows}
        cross_reference_rows = []
        cross_reference_files = [
            path for path in sorted(CROSS_REFERENCES_DIR.glob("*.json.gz"))
        ]

        for path in cross_reference_files:
            source_data = read_cross_reference_data(path)
            source_name = source_data.get("source") or path.stem
            source_id = normalize_cross_reference_source_id(source_name)
            for row in iter_cross_reference_records(
                    source_name, source_data, book_names):
                cross_reference_rows.append(row)
                if len(cross_reference_rows) >= 10000:
                    connection.executemany(
                        "INSERT OR REPLACE INTO cross_references "
                        "(source_name, source_book_id, source_chapter, source_verse, "
                        "target_reference, target_book_id, target_chapter, "
                        "target_verse, votes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        cross_reference_rows,
                    )
                    cross_reference_rows.clear()
            for note in source_data.get("notes", []):
                if not isinstance(note, dict):
                    continue
                source_reference = note.get("source") or note.get(
                    "source_reference"
                )
                text = note.get("text")
                if not isinstance(source_reference, str) or not isinstance(text, str):
                    continue
                try:
                    note_book, note_chapter, note_verse = parse_reference(
                        source_reference
                    )
                    note_book_id = resolve_book_name(note_book, book_names)
                except ValueError:
                    continue
                connection.execute(
                    "INSERT OR REPLACE INTO cross_reference_notes "
                    "(source_name, source_book_id, source_chapter, "
                    "source_verse, text) VALUES (?, ?, ?, ?, ?)",
                    (
                        source_id,
                        note_book_id,
                        note_chapter,
                        note_verse,
                        text,
                    ),
                )
            if cross_reference_rows:
                connection.executemany(
                    "INSERT OR REPLACE INTO cross_references "
                    "(source_name, source_book_id, source_chapter, source_verse, "
                    "target_reference, target_book_id, target_chapter, "
                    "target_verse, votes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    cross_reference_rows,
                )
                cross_reference_rows.clear()
        connection.commit()


def ensure_database():
    manifest = source_manifest()
    if database_is_current(manifest):
        return

    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            prefix="reader-", suffix=".sqlite3", dir=DATABASE_DIR,
            delete=False) as temporary_file:
        temporary_path = Path(temporary_file.name)
    try:
        build_database(temporary_path, manifest)
        os.replace(temporary_path, DATABASE_FILE)
    finally:
        temporary_path.unlink(missing_ok=True)


def open_database():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def read_verse_markups():
    if not MARKUP_FILE.is_file():
        return {}
    with gzip.open(MARKUP_FILE, "rt", encoding="utf-8") as source_file:
        data = json.load(source_file)
    if (not isinstance(data, dict)
            or data.get("version") != 1
            or not isinstance(data.get("verses"), dict)):
        raise ValueError(f"Invalid verse markup data in {MARKUP_FILE}")
    return data["verses"]


def write_verse_markups(verse_markups):
    MARKUP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            prefix="verse-markup-", suffix=".json.gz", dir=MARKUP_DIR,
            delete=False) as temporary_file:
        temporary_path = Path(temporary_file.name)
    try:
        with gzip.open(temporary_path, "wt", encoding="utf-8") as output_file:
            json.dump(
                {"version": 1, "verses": verse_markups},
                output_file,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        os.replace(temporary_path, MARKUP_FILE)
    finally:
        temporary_path.unlink(missing_ok=True)


ensure_database()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/translations")
def get_translations():
    return jsonify([
        {
            "id": translation_id,
            "name": TRANSLATION_NAMES.get(translation_id, translation_id),
        }
        for translation_id in TRANSLATION_FILES
    ])


@app.route("/api/books/<translation_id>")
def get_books(translation_id):
    if translation_id not in TRANSLATION_FILES:
        abort(404, description=f"Bible translation not found: {translation_id}")
    with closing(open_database()) as connection:
        rows = connection.execute(
            "SELECT b.book_id, b.name, c.chapter "
            "FROM bible_books AS b "
            "JOIN bible_chapters AS c "
            "ON c.translation_id = b.translation_id AND c.book_id = b.book_id "
            "WHERE b.translation_id = ? "
            "ORDER BY b.book_order, c.chapter",
            (translation_id,),
        ).fetchall()
    books = []
    for row in rows:
        if not books or books[-1]["id"] != row["book_id"]:
            books.append({
                "id": row["book_id"],
                "name": row["name"],
                "chapters": [],
            })
        books[-1]["chapters"].append(row["chapter"])
    return jsonify(books)


@app.route("/api/bible/<translation_id>/<book_id>/<int:chapter>")
def get_bible_chapter(translation_id, book_id, chapter):
    if translation_id not in TRANSLATION_FILES:
        abort(404, description=f"Bible translation not found: {translation_id}")
    with closing(open_database()) as connection:
        book = connection.execute(
            "SELECT name FROM bible_books "
            "WHERE translation_id = ? AND book_id = ?",
            (translation_id, book_id),
        ).fetchone()
        if book is None:
            abort(404, description=f"Bible book not found: {book_id}")
        record = connection.execute(
            "SELECT payload FROM bible_chapters "
            "WHERE translation_id = ? AND book_id = ? AND chapter = ?",
            (translation_id, book_id, chapter),
        ).fetchone()
        cross_reference_rows = connection.execute(
            "SELECT source_name, source_verse, target_reference, target_book_id, "
            "target_chapter, target_verse "
            "FROM cross_references "
            "WHERE source_book_id = ? AND source_chapter = ? "
            "ORDER BY source_verse, votes DESC, target_reference",
            (book_id, chapter),
        ).fetchall()
        cross_reference_note_rows = connection.execute(
            "SELECT source_name, source_verse, text "
            "FROM cross_reference_notes "
            "WHERE source_book_id = ? AND source_chapter = ? "
            "ORDER BY source_verse, source_name",
            (book_id, chapter),
        ).fetchall()
    if record is None:
        abort(404, description=f"Bible passage not found: {book['name']} {chapter}")
    payload = json.loads(zlib.decompress(record["payload"]))
    cross_references_by_verse = {}
    cross_reference_notes_by_verse = {}
    for row in cross_reference_rows:
        cross_references_by_verse.setdefault(row["source_verse"], []).append({
            "source": row["source_name"],
            "reference": row["target_reference"],
            "book_id": row["target_book_id"],
            "chapter": row["target_chapter"],
            "verse": row["target_verse"],
        })
    for row in cross_reference_note_rows:
        cross_reference_notes_by_verse.setdefault(row["source_verse"], []).append({
            "source": row["source_name"],
            "text": row["text"],
        })
    for block in payload["blocks"]:
        for verse in block.get("verses", []):
            verse["cross_references"] = cross_references_by_verse.get(
                verse["num"], []
            )
            verse["cross_reference_notes"] = cross_reference_notes_by_verse.get(
                verse["num"], []
            )
    return jsonify(payload)


@app.route("/api/commentaries/<path:book>/<int:chapter>")
def get_commentaries(book, chapter):
    normalized_name = normalize_book_name(book)
    with closing(open_database()) as connection:
        rows = connection.execute(
            "SELECT c.commentary_id, c.title, c.author, c.date_written, "
            "ch.entries "
            "FROM commentary_books AS b "
            "JOIN commentaries AS c ON c.commentary_id = b.commentary_id "
            "LEFT JOIN commentary_chapters AS ch "
            "ON ch.commentary_id = b.commentary_id "
            "AND ch.book_id = b.book_id AND ch.chapter = ? "
            "WHERE b.normalized_name = ? "
            "ORDER BY c.sort_order",
            (chapter, normalized_name),
        ).fetchall()
    return jsonify([
        {
            "id": row["commentary_id"],
            "title": row["title"],
            "author": row["author"],
            "date_written": row["date_written"],
            "entries": (
                json.loads(zlib.decompress(row["entries"]))
                if row["entries"] else []
            ),
        }
        for row in rows
    ])


@app.route("/api/sermons/<path:book>/<int:chapter>")
def get_sermons(book, chapter):
    normalized_name = normalize_book_name(book)
    with closing(open_database()) as connection:
        rows = connection.execute(
            "SELECT s.sermon_id, s.title, s.author, s.date_written, s.text, "
            "r.verse "
            "FROM sermon_references AS r "
            "JOIN sermons AS s ON s.sermon_id = r.sermon_id "
            "WHERE r.normalized_name = ? AND r.chapter = ? "
            "ORDER BY s.sort_order, r.verse",
            (normalized_name, chapter),
        ).fetchall()

    sermons_by_id = {}
    for row in rows:
        sermon = sermons_by_id.get(row["sermon_id"])
        if sermon is None:
            sermon = {
                "id": row["sermon_id"],
                "title": row["title"],
                "author": row["author"],
                "date_written": row["date_written"],
                "text": row["text"],
                "verses": [],
            }
            sermons_by_id[row["sermon_id"]] = sermon
        sermon["verses"].append(row["verse"])
    return jsonify(list(sermons_by_id.values()))


@app.route("/api/cross-reference-sources")
def get_cross_reference_sources_api():
    return jsonify(get_cross_reference_sources())


@app.route(
    "/api/markup/<translation_id>/<book_id>/<int:chapter>",
    methods=["GET", "PUT"],
)
def verse_markup(translation_id, book_id, chapter):
    if translation_id not in TRANSLATION_FILES:
        abort(404, description=f"Bible translation not found: {translation_id}")
    with closing(open_database()) as connection:
        record = connection.execute(
            "SELECT payload FROM bible_chapters "
            "WHERE translation_id = ? AND book_id = ? AND chapter = ?",
            (translation_id, book_id, chapter),
        ).fetchone()
    if record is None:
        abort(404, description=f"Bible passage not found: {book_id} {chapter}")
    chapter_data = json.loads(zlib.decompress(record["payload"]))
    valid_verses = {
        verse["num"]
        for block in chapter_data.get("blocks", [])
        for verse in block.get("verses", [])
        if isinstance(verse.get("num"), int)
    }

    passage_prefix = f"{translation_id}|{book_id}|{chapter}|"
    if request.method == "GET":
        with MARKUP_LOCK:
            verse_markups = read_verse_markups()
        passage_markups = {
            key[len(passage_prefix):]: markup
            for key, markup in verse_markups.items()
            if isinstance(key, str) and key.startswith(passage_prefix)
        }
        return jsonify(passage_markups)

    payload = request.get_json()
    if not isinstance(payload, dict) or not isinstance(payload.get("verses"), list):
        abort(400, description="Expected a verses list.")
    updates = {}
    for item in payload["verses"]:
        if not isinstance(item, dict):
            abort(400, description="Each verse markup must be an object.")
        verse = item.get("verse")
        markup = item.get("markup")
        if type(verse) is not int or verse < 1:
            abort(400, description="Verse numbers must be positive integers.")
        if verse not in valid_verses:
            abort(400, description=f"Verse {verse} is not in this chapter.")
        if verse in updates:
            abort(400, description=f"Duplicate verse markup: {verse}")
        if not isinstance(markup, dict):
            abort(400, description="Markup must be an object.")
        if set(markup) - MARKUP_TYPES:
            abort(400, description="Unsupported verse markup type.")
        for color in markup.values():
            if not isinstance(color, str) or not MARKUP_COLOR_PATTERN.fullmatch(color):
                abort(400, description="Markup colors must use #RRGGBB format.")
        updates[verse] = markup

    if not updates:
        abort(400, description="At least one verse markup update is required.")

    with MARKUP_LOCK:
        verse_markups = read_verse_markups()
        for verse, markup in updates.items():
            key = f"{passage_prefix}{verse}"
            if markup:
                verse_markups[key] = markup
            else:
                verse_markups.pop(key, None)
        write_verse_markups(verse_markups)
    return jsonify({"saved": sorted(updates)})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
