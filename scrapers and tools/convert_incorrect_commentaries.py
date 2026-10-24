import argparse
import gzip
import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = ROOT_DIR / "scrapers and tools" / "commentaries_json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "scrapers and tools" / "commentaries_json_gz"
AUTHOR_PREFIXES = {
    "cal": ("john-calvin", "John Calvin"),
    "mlg": ("luther", "Martin Luther"),
    "mpc": ("poole", "Matthew Poole"),
    "tsk": ("treasury-of-scripture-knowledge", "Treasury of Scripture Knowledge"),
    "spurgeon": ("charles-spurgeon", "Charles Spurgeon"),
}
BOOKS = [
    ("GEN", "Genesis"), ("EXO", "Exodus"), ("LEV", "Leviticus"),
    ("NUM", "Numbers"), ("DEU", "Deuteronomy"), ("JOS", "Joshua"),
    ("JDG", "Judges"), ("RUT", "Ruth"), ("1SA", "1 Samuel"),
    ("2SA", "2 Samuel"), ("1KI", "1 Kings"), ("2KI", "2 Kings"),
    ("1CH", "1 Chronicles"), ("2CH", "2 Chronicles"), ("EZR", "Ezra"),
    ("NEH", "Nehemiah"), ("EST", "Esther"), ("JOB", "Job"),
    ("PSA", "Psalms"), ("PRO", "Proverbs"), ("ECC", "Ecclesiastes"),
    ("SNG", "Song of Solomon"), ("ISA", "Isaiah"), ("JER", "Jeremiah"),
    ("LAM", "Lamentations"), ("EZK", "Ezekiel"), ("DAN", "Daniel"),
    ("HOS", "Hosea"), ("JOL", "Joel"), ("AMO", "Amos"), ("OBA", "Obadiah"),
    ("JON", "Jonah"), ("MIC", "Micah"), ("NAH", "Nahum"), ("HAB", "Habakkuk"),
    ("ZEP", "Zephaniah"), ("HAG", "Haggai"), ("ZEC", "Zechariah"),
    ("MAL", "Malachi"), ("MAT", "Matthew"), ("MRK", "Mark"), ("LUK", "Luke"),
    ("JHN", "John"), ("ACT", "Acts"), ("ROM", "Romans"),
    ("1CO", "1 Corinthians"), ("2CO", "2 Corinthians"), ("GAL", "Galatians"),
    ("EPH", "Ephesians"), ("PHP", "Philippians"), ("COL", "Colossians"),
    ("1TH", "1 Thessalonians"), ("2TH", "2 Thessalonians"),
    ("1TI", "1 Timothy"), ("2TI", "2 Timothy"), ("TIT", "Titus"),
    ("PHM", "Philemon"), ("HEB", "Hebrews"), ("JAS", "James"),
    ("1PE", "1 Peter"), ("2PE", "2 Peter"), ("1JN", "1 John"),
    ("2JN", "2 John"), ("3JN", "3 John"), ("JUD", "Jude"),
    ("REV", "Revelation"),
]


def normalize_book_name(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


BOOK_BY_NORMALIZED_NAME = {
    normalize_book_name(name): (book_id, name)
    for book_id, name in BOOKS
}
BOOK_BY_NORMALIZED_NAME["songofsongs"] = ("SNG", "Song of Solomon")


def get_book(book_name):
    book = BOOK_BY_NORMALIZED_NAME.get(normalize_book_name(book_name))
    if book is None:
        raise ValueError(f"Unrecognized Bible book name: {book_name}")
    return book


def new_book_record(book_id, book_name, author_id, author_name, introduction=None):
    record = {
        "id": book_id,
        "commentaryId": author_id,
        "name": book_name,
        "commonName": book_name,
    }
    if introduction:
        record["introduction"] = introduction
    return record


def append_entry(chapters, book_id, book_name, chapter, verse, text):
    if not text:
        return
    key = (book_id, chapter)
    record = chapters.setdefault(key, {
        "book_id": book_id,
        "book_name": book_name,
        "chapter": chapter,
        "content": [],
    })
    item = {
        "type": "verse" if verse is not None else "introduction",
        "content": [text],
    }
    if verse is not None:
        item["number"] = verse
    record["content"].append(item)


def convert_nested_book_files(json_files, author_id, author_name):
    chapters = {}
    book_metadata = {}
    json_files = sorted(json_files)
    if not json_files:
        raise ValueError(f"No JSON datasets found for {author_name}")

    for path in json_files:
        with path.open(encoding="utf-8") as source_file:
            data = json.load(source_file)
        if not isinstance(data, dict) or len(data) != 1:
            raise ValueError(f"Expected one book-keyed object in {path}")
        source_book_name, source_chapters = next(iter(data.items()))
        book_id, book_name = get_book(source_book_name)
        if not isinstance(source_chapters, dict):
            raise ValueError(f"Expected chapter map for {source_book_name} in {path}")
        book_metadata[book_id] = (book_name, author_id, author_name, None)

        for chapter_text, source_verses in source_chapters.items():
            try:
                chapter = int(chapter_text)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid chapter number {chapter_text!r} in {path}") from error
            if chapter < 1 or not isinstance(source_verses, dict):
                raise ValueError(f"Invalid chapter data in {path}: {chapter_text}")
            for verse_text, commentary in source_verses.items():
                try:
                    verse_number = int(verse_text)
                except (TypeError, ValueError) as error:
                    raise ValueError(f"Invalid verse number {verse_text!r} in {path}") from error
                if verse_number < 0 or not isinstance(commentary, str):
                    raise ValueError(f"Invalid commentary at {source_book_name} {chapter}:{verse_text}")
                append_entry(
                    chapters, book_id, book_name, chapter,
                    verse_number or None, commentary.strip(),
                )

    return chapters, book_metadata


def convert_wesley_files(author_dir):
    chapters = {}
    book_metadata = {}
    json_files = sorted(author_dir.glob("*.json"))
    if not json_files:
        raise ValueError(f"No JSON datasets found in {author_dir}")

    for path in json_files:
        with path.open(encoding="utf-8") as source_file:
            data = json.load(source_file)
        if not isinstance(data, dict) or "notes" not in data:
            if isinstance(data, list):
                continue
            raise ValueError(f"Unrecognized Wesley dataset: {path}")

        book_name = data.get("name")
        if not isinstance(book_name, str) or not isinstance(data["notes"], list):
            raise ValueError(f"Invalid Wesley book dataset: {path}")
        book_id, book_name = get_book(book_name)
        introduction = data.get("intro")
        if not isinstance(introduction, str):
            introduction = ""
        book_metadata[book_id] = (
            book_name,
            "wesley",
            "John Wesley",
            introduction.strip(),
        )

        for note in data["notes"]:
            if not isinstance(note, dict):
                raise ValueError(f"Invalid note entry in {path}")
            chapter = note.get("chapter")
            verse_start = note.get("verse_start")
            verse_end = note.get("verse_end")
            comment = note.get("comment")
            if (not isinstance(chapter, int) or not isinstance(verse_start, int)
                    or not isinstance(verse_end, int) or not isinstance(comment, str)
                    or chapter < 1 or verse_start < 1 or verse_end < verse_start):
                raise ValueError(f"Invalid Wesley note reference in {path}: {note!r}")
            lemma = note.get("lemma")
            text = (
                f"**{lemma}**\n\n{comment}"
                if isinstance(lemma, str) and lemma else comment
            )
            for verse in range(verse_start, verse_end + 1):
                append_entry(chapters, book_id, book_name, chapter, verse, text.strip())

    return chapters, book_metadata


def make_author_payload(chapters, book_metadata, author_id, author_name):
    book_order = {book_id: index for index, (book_id, _) in enumerate(BOOKS)}
    output_books = []
    for book_id in sorted(book_metadata, key=book_order.__getitem__):
        book_name, _, _, introduction = book_metadata[book_id]
        chapter_count = max(
            chapter for candidate_id, chapter in chapters if candidate_id == book_id
        )
        output_books.append({
            **new_book_record(
                book_id, book_name, author_id, author_name, introduction
            ),
            "numberOfChapters": chapter_count,
        })

    output_chapters = []
    for (book_id, chapter_number), record in sorted(
        chapters.items(),
        key=lambda item: (book_order[item[0][0]], item[0][1]),
    ):
        output_chapters.append({
            "book_id": book_id,
            "chapter": chapter_number,
            "data": {
                "commentary": {
                    "id": author_id,
                    "name": f"{author_name} Commentary",
                },
                "book": {"id": book_id, "name": record["book_name"]},
                "chapter": {
                    "number": chapter_number,
                    "content": record["content"],
                },
            },
        })
    return {"books": output_books, "chapters": output_chapters}


def write_author_archive(chapters, book_metadata, author_id, author_name, output_dir):
    if not chapters:
        raise ValueError(f"No commentary entries found for {author_name}")

    payload = make_author_payload(
        chapters, book_metadata, author_id, author_name
    )
    output_path = output_dir / f"{author_id}.json.gz"
    with gzip.open(output_path, "wt", encoding="utf-8") as output_file:
        json.dump(payload, output_file, ensure_ascii=False, separators=(",", ":"))

    entry_count = sum(
        len(chapter["data"]["chapter"]["content"])
        for chapter in payload["chapters"]
    )
    print(
        f"{author_name}: wrote {len(payload['books'])} books, "
        f"{len(payload['chapters'])} chapters, and {entry_count} entries "
        f"to {output_path}"
    )
    return output_path


def convert_author(author_dir, output_dir):
    author_id = normalize_book_name(author_dir.name)
    author_name = {
        "guzik": "David Guzik",
        "spurgeon": "Charles Spurgeon",
        "wesley": "John Wesley",
    }.get(author_id, author_dir.name)

    if author_id == "wesley":
        chapters, book_metadata = convert_wesley_files(author_dir)
    else:
        chapters, book_metadata = convert_nested_book_files(
            author_dir.glob("*.json"), author_id, author_name
        )
    return write_author_archive(
        chapters, book_metadata, author_id, author_name, output_dir
    )


def convert_prefixed_files(prefix, json_files, output_dir):
    author_id, author_name = AUTHOR_PREFIXES[prefix]
    chapters, book_metadata = convert_nested_book_files(
        json_files, author_id, author_name
    )
    return write_author_archive(
        chapters, book_metadata, author_id, author_name, output_dir
    )


def main():
    parser = argparse.ArgumentParser(
        description="Combine per-book commentary JSON files into author archives."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Per-book JSON files or author folders (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Destination for compressed archives (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()
    if not args.input_dir.is_dir():
        parser.error(f"Commentary dataset directory not found: {args.input_dir}")

    author_files = {}
    unknown_files = []
    for path in sorted(args.input_dir.glob("*.json")):
        if path.name == "_file_manifest.json":
            continue
        prefix = path.stem.split("_", 1)[0].casefold()
        if prefix not in AUTHOR_PREFIXES:
            unknown_files.append(path.name)
        else:
            author_files.setdefault(prefix, []).append(path)
    if unknown_files:
        parser.error(
            "Unrecognized commentary filename prefix for: "
            + ", ".join(unknown_files)
        )

    author_dirs = sorted(path for path in args.input_dir.iterdir() if path.is_dir())
    if not author_dirs and not author_files:
        parser.error(
            f"No commentary JSON files or author folders found in {args.input_dir}"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for prefix, json_files in sorted(author_files.items()):
        convert_prefixed_files(prefix, json_files, args.output_dir)
    for author_dir in author_dirs:
        convert_author(author_dir, args.output_dir)


if __name__ == "__main__":
    main()
