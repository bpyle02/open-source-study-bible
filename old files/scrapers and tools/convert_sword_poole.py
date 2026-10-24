import argparse
import configparser
import gzip
import json
import re
import struct
import zlib
from html.parser import HTMLParser
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODULE = ROOT_DIR / "files" / "sipoole"
DEFAULT_OUTPUT = ROOT_DIR / "commentaries" / "poole.json.gz"
MODULE_OUTPUTS = {
    "sibarnes": ("barnes", "Albert Barnes"),
    "siluthercmt": ("luther-selected-passages", "Martin Luther"),
    "sinetnotes": ("net-notes", "NET Bible Translators"),
    "siryle": ("ryle", "J.C. Ryle"),
    "sispurgeon": ("spurgeon-sword", "Charles Spurgeon"),
    "sipoole": ("poole", "Matthew Poole"),
}
BOOKS = [
    ("Gen", "GEN", "Genesis"), ("Exod", "EXO", "Exodus"),
    ("Lev", "LEV", "Leviticus"), ("Num", "NUM", "Numbers"),
    ("Deut", "DEU", "Deuteronomy"), ("Josh", "JOS", "Joshua"),
    ("Judg", "JDG", "Judges"), ("Ruth", "RUT", "Ruth"),
    ("1Sam", "1SA", "1 Samuel"), ("2Sam", "2SA", "2 Samuel"),
    ("1Kgs", "1KI", "1 Kings"), ("2Kgs", "2KI", "2 Kings"),
    ("1Chr", "1CH", "1 Chronicles"), ("2Chr", "2CH", "2 Chronicles"),
    ("Ezra", "EZR", "Ezra"), ("Neh", "NEH", "Nehemiah"),
    ("Esth", "EST", "Esther"), ("Job", "JOB", "Job"),
    ("Ps", "PSA", "Psalms"), ("Prov", "PRO", "Proverbs"),
    ("Eccl", "ECC", "Ecclesiastes"), ("Song", "SNG", "Song of Solomon"),
    ("Isa", "ISA", "Isaiah"), ("Jer", "JER", "Jeremiah"),
    ("Lam", "LAM", "Lamentations"), ("Ezek", "EZK", "Ezekiel"),
    ("Dan", "DAN", "Daniel"), ("Hos", "HOS", "Hosea"),
    ("Joel", "JOL", "Joel"), ("Amos", "AMO", "Amos"),
    ("Obad", "OBA", "Obadiah"), ("Jonah", "JON", "Jonah"),
    ("Mic", "MIC", "Micah"), ("Nah", "NAH", "Nahum"),
    ("Hab", "HAB", "Habakkuk"), ("Zeph", "ZEP", "Zephaniah"),
    ("Hag", "HAG", "Haggai"), ("Zech", "ZEC", "Zechariah"),
    ("Mal", "MAL", "Malachi"),
    ("Matt", "MAT", "Matthew"), ("Mark", "MRK", "Mark"),
    ("Luke", "LUK", "Luke"), ("John", "JHN", "John"),
    ("Acts", "ACT", "Acts"), ("Rom", "ROM", "Romans"),
    ("1Cor", "1CO", "1 Corinthians"), ("2Cor", "2CO", "2 Corinthians"),
    ("Gal", "GAL", "Galatians"), ("Eph", "EPH", "Ephesians"),
    ("Phil", "PHP", "Philippians"), ("Col", "COL", "Colossians"),
    ("1Thess", "1TH", "1 Thessalonians"),
    ("2Thess", "2TH", "2 Thessalonians"),
    ("1Tim", "1TI", "1 Timothy"), ("2Tim", "2TI", "2 Timothy"),
    ("Titus", "TIT", "Titus"), ("Phlm", "PHM", "Philemon"),
    ("Heb", "HEB", "Hebrews"), ("Jas", "JAS", "James"),
    ("1Pet", "1PE", "1 Peter"), ("2Pet", "2PE", "2 Peter"),
    ("1John", "1JN", "1 John"), ("2John", "2JN", "2 John"),
    ("3John", "3JN", "3 John"), ("Jude", "JUD", "Jude"),
    ("Rev", "REV", "Revelation"),
]
BOOK_BY_OSIS = {osis_id: (book_id, name) for osis_id, book_id, name in BOOKS}
BOOK_MARKER = re.compile(
    r'<div\b(?=[^>]*\bosisID="([^"]+)")(?=[^>]*\btype="book")[^>]*/?>',
    re.IGNORECASE,
)
CHAPTER_MARKER = re.compile(
    r'<chapter\b(?=[^>]*\bosisID="([^".]+)\.(\d+)")[^>]*/?>',
    re.IGNORECASE,
)


class OsisTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs = []
        self.parts = []

    def _flush(self):
        text = "".join(self.parts).strip()
        if text:
            self.paragraphs.append(text)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag != "div":
            return
        attributes = {name.casefold(): value for name, value in attrs}
        if attributes.get("type") != "x-p":
            return
        if "sid" in attributes:
            self._flush()
        elif "eid" in attributes:
            self._flush()

    def handle_data(self, data):
        self.parts.append(data)

    def text(self, source):
        self.feed(source)
        self._flush()
        return "\n\n".join(self.paragraphs)


def read_blocks(module_dir, testament):
    bzs_path = module_dir / f"{testament}.bzs"
    bzz_path = module_dir / f"{testament}.bzz"
    if not bzs_path.is_file() or not bzz_path.is_file():
        raise FileNotFoundError(f"Missing SWORD {testament.upper()} block data")

    bzs = bzs_path.read_bytes()
    bzz = bzz_path.read_bytes()
    if len(bzs) % 12:
        raise ValueError(f"Invalid block index length: {bzs_path}")

    blocks = []
    for offset in range(0, len(bzs), 12):
        data_offset, compressed_size, uncompressed_size = struct.unpack_from(
            "<III", bzs, offset
        )
        compressed = bzz[data_offset:data_offset + compressed_size]
        if len(compressed) != compressed_size:
            raise ValueError(f"Block extends past end of {bzz_path}")
        block = zlib.decompress(compressed)
        if len(block) != uncompressed_size:
            raise ValueError(
                f"Unexpected decompressed size in {testament.upper()} block "
                f"{offset // 12}: expected {uncompressed_size}, got {len(block)}"
            )
        blocks.append(block)
    return blocks


def read_index(module_dir, testament, blocks):
    index_path = module_dir / f"{testament}.bzv"
    index_data = index_path.read_bytes()
    if len(index_data) % 10:
        raise ValueError(f"Invalid verse index length: {index_path}")

    entries = []
    for offset in range(0, len(index_data), 10):
        block_id, item_offset, item_size = struct.unpack_from(
            "<IIH", index_data, offset
        )
        if block_id == 0 or item_size == 0:
            entries.append("")
            continue
        if block_id >= len(blocks):
            raise ValueError(f"Invalid block ID {block_id} in {index_path}")
        content = blocks[block_id]
        item = content[item_offset:item_offset + item_size]
        if len(item) != item_size:
            raise ValueError(f"Invalid data slice in {index_path} at {offset // 10}")
        entries.append(item.decode("utf-8", errors="replace"))
    return entries


def parse_testament(module_dir, testament):
    blocks = read_blocks(module_dir, testament)
    index_entries = read_index(module_dir, testament, blocks)
    chapters = {}
    current_book_id = None
    current_book_name = None
    current_chapter = None
    current_verse = 0

    for raw_entry in index_entries:
        book_match = BOOK_MARKER.search(raw_entry)
        if book_match:
            book = BOOK_BY_OSIS.get(book_match.group(1))
            if book is None:
                raise ValueError(
                    f"Unknown OSIS book identifier: {book_match.group(1)}"
                )
            current_book_id, current_book_name = book
            current_chapter = None
            current_verse = 0
            continue

        chapter_match = CHAPTER_MARKER.search(raw_entry)
        if chapter_match:
            osis_id, chapter_text = chapter_match.groups()
            book = BOOK_BY_OSIS.get(osis_id)
            if book is None:
                raise ValueError(f"Unknown OSIS book identifier: {osis_id}")
            current_book_id, current_book_name = book
            current_chapter = int(chapter_text)
            current_verse = 0
            chapters.setdefault(
                (current_book_id, current_chapter),
                {"book_name": current_book_name, "entries": []},
            )
            continue

        if current_book_id is None or current_chapter is None:
            continue

        current_verse += 1
        text = OsisTextParser().text(raw_entry) if raw_entry else ""
        if "No Commentary on these verses is yet included" in text:
            continue
        paragraphs = [
            paragraph.strip()
            for paragraph in text.split("\n\n")
            if paragraph.strip()
            and not re.fullmatch(r"\d+", paragraph.strip())
            and not paragraph.strip().startswith(
                "The Bible.org ministry has provided the NET Bible"
            )
        ]
        text = "\n\n".join(paragraphs)
        if text:
            chapters[(current_book_id, current_chapter)]["entries"].append({
                "type": "verse",
                "number": current_verse,
                "content": [text],
            })

    return chapters


def make_commentary(module_path):
    config_files = sorted((module_path / "mods.d").glob("*.conf"))
    if len(config_files) != 1:
        raise ValueError(
            f"Expected one module config in {module_path / 'mods.d'}, "
            f"found {len(config_files)}"
        )
    config_path = config_files[0]
    config = configparser.ConfigParser(interpolation=None)
    config.read(config_path, encoding="utf-8")
    if not config.sections():
        raise ValueError(f"No module section found in {config_path}")
    module_section = config.sections()[0]
    module_id = module_section.casefold()
    module_config = config[module_section]
    if "DataPath" not in module_config:
        raise ValueError(f"Missing DataPath in {config_path}")
    data_path = Path(module_config["DataPath"].replace("\\", "/"))
    module_data = (module_path / data_path).resolve()
    if not module_data.is_dir():
        raise FileNotFoundError(f"SWORD module data not found: {module_data}")
    output_id, author_name = MODULE_OUTPUTS.get(
        module_id,
        (module_id.removeprefix("si"), module_config.get("Description", module_id)),
    )

    chapters = {}
    for testament in ("ot", "nt"):
        chapters.update(parse_testament(module_data, testament))

    books = []
    for _, book_id, book_name in BOOKS:
        available = sorted(
            chapter for (candidate_id, chapter) in chapters
            if candidate_id == book_id
        )
        if available:
            books.append({
                "id": book_id,
                "commentaryId": output_id,
                "name": book_name,
                "commonName": book_name,
                "numberOfChapters": max(available),
            })

    output_chapters = []
    for (book_id, chapter_number), chapter_data in sorted(
            chapters.items(),
            key=lambda item: (
                next(i for i, book in enumerate(BOOKS) if book[1] == item[0][0]),
                item[0][1],
            )):
        output_chapters.append({
            "book_id": book_id,
            "chapter": chapter_number,
            "data": {
                "commentary": {
                    "id": output_id,
                    "name": module_config.get("Description", author_name),
                },
                "book": {
                    "id": book_id,
                    "name": chapter_data["book_name"],
                },
                "chapter": {
                    "number": chapter_number,
                    "content": chapter_data["entries"],
                },
            },
        })

    if not output_chapters:
        raise ValueError(f"No Bible chapter references found in {module_path}")
    return {
        "metadata": {
            "title": "Poole's Annotations on the Holy Bible",
            "author": author_name,
            "date_written": "1669–1679 (published 1683–1700)",
        },
        "books": books,
        "chapters": output_chapters,
        "output_id": output_id,
        "author_name": author_name,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert a SWORD zCom module to a compressed commentary file."
    )
    parser.add_argument(
        "module",
        nargs="?",
        type=Path,
        default=DEFAULT_MODULE,
        help=(
            "SWORD module directory, or 'all' to convert every SWORD module "
            f"under {ROOT_DIR / 'files'} (default: {DEFAULT_MODULE})"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON.GZ file (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    modules = (
        sorted(path for path in (ROOT_DIR / "files").iterdir()
               if path.is_dir() and (path / "mods.d").is_dir())
        if str(args.module).casefold() == "all"
        else [args.module]
    )
    if any(not module.is_dir() for module in modules):
        parser.error("SWORD module directory not found: " +
                     ", ".join(str(module) for module in modules if not module.is_dir()))

    for module in modules:
        commentary = make_commentary(module)
        output_path = args.output if len(modules) == 1 else (
            DEFAULT_OUTPUT.parent / f"{commentary['output_id']}.json.gz"
        )
        if len(modules) == 1 and args.output == DEFAULT_OUTPUT:
            output_path = DEFAULT_OUTPUT.parent / f"{commentary['output_id']}.json.gz"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(output_path, "wt", encoding="utf-8") as output_file:
            payload = {
                key: value for key, value in commentary.items()
                if key not in ("output_id", "author_name")
            }
            json.dump(payload, output_file, ensure_ascii=False, separators=(",", ":"))

        entry_count = sum(
            len(chapter["data"]["chapter"]["content"])
            for chapter in commentary["chapters"]
        )
        print(
            f"{commentary['author_name']}: wrote {len(commentary['books'])} books, "
            f"{len(commentary['chapters'])} chapters, and {entry_count} verse notes "
            f"to {output_path}"
        )


if __name__ == "__main__":
    main()
