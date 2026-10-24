import argparse
import gzip
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT_DIR / "files" / "luther.epub"
DEFAULT_OUTPUT = ROOT_DIR / "commentaries" / "luther.json.gz"
BOOK_ID = "GAL"
BOOK_NAME = "Galatians"
CHAPTERS = 6
CHAPTER_HEADING = re.compile(r"^CHAPTER\s+(\d+)\s*$", re.IGNORECASE)
VERSE_HEADING = re.compile(
    r"^\s*VERSES?\s+(\d+(?:\s*(?:-|–|and|,)\s*\d+)*)\s*\.?\s*",
    re.IGNORECASE,
)


class EpubParagraphParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active_tag = None
        self.text_parts = []
        self.elements = []

    def handle_starttag(self, tag, attrs):
        if self.active_tag is None and tag in ("h1", "h2", "h3", "h4", "p"):
            self.active_tag = tag
            self.text_parts = []
        elif self.active_tag is not None and tag == "br":
            self.text_parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if self.active_tag is not None and tag == "br":
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag == self.active_tag:
            text = "".join(self.text_parts).strip()
            self.elements.append((tag, text))
            self.active_tag = None
            self.text_parts = []

    def handle_data(self, data):
        if self.active_tag is not None:
            self.text_parts.append(data)


def parse_verse_numbers(label):
    numbers = [int(number) for number in re.findall(r"\d+", label)]
    if len(numbers) == 2 and re.search(r"[-–]", label):
        start, end = numbers
        return list(range(start, end + 1))
    return numbers


def add_commentary_text(entries, verse_numbers, text):
    if not text:
        return
    for verse_number in verse_numbers:
        if verse_number not in entries:
            entries[verse_number] = []
        entries[verse_number].append(text)


def extract_chapters(epub_path):
    chapter_entries = {}
    chapter_number = None
    html_files = []

    with zipfile.ZipFile(epub_path) as epub:
        for filename in epub.namelist():
            if re.search(r"1549-h-\d+\.htm\.xhtml$", filename):
                html_files.append(filename)

        for filename in html_files:
            parser = EpubParagraphParser()
            parser.feed(epub.read(filename).decode("utf-8", errors="replace"))

            for tag, text in parser.elements:
                heading_match = CHAPTER_HEADING.fullmatch(text) if tag == "h2" else None
                if heading_match:
                    candidate = int(heading_match.group(1))
                    chapter_number = candidate if 1 <= candidate <= CHAPTERS else None
                    current_verses = []
                    if chapter_number is not None:
                        chapter_entries.setdefault(chapter_number, {})
                    continue

                if chapter_number is None or tag != "p" or not text:
                    continue

                verse_match = VERSE_HEADING.match(text)
                if verse_match:
                    verse_numbers = parse_verse_numbers(verse_match.group(1))
                    text = text[verse_match.end():].strip()
                    if verse_numbers:
                        current_verses = verse_numbers

                # Paragraphs before the first explicit verse label are chapter notes.
                add_commentary_text(
                    chapter_entries[chapter_number],
                    current_verses or [None],
                    text,
                )

    if not chapter_entries:
        raise ValueError(f"No Galatians chapter headings were found in {epub_path}")
    return chapter_entries


def make_commentary(epub_path):
    chapter_entries = extract_chapters(epub_path)
    books = [{
        "id": BOOK_ID,
        "commentaryId": "luther",
        "name": BOOK_NAME,
        "commonName": BOOK_NAME,
        "numberOfChapters": CHAPTERS,
    }]
    chapters = []

    for chapter_number in sorted(chapter_entries):
        content = []
        for verse_number, paragraphs in chapter_entries[chapter_number].items():
            if not paragraphs:
                continue
            content.append({
                "type": "verse" if verse_number is not None else "introduction",
                **({"number": verse_number} if verse_number is not None else {}),
                "content": ["\n\n".join(paragraphs)],
            })
        chapters.append({
            "book_id": BOOK_ID,
            "chapter": chapter_number,
            "data": {
                "commentary": {
                    "id": "luther",
                    "name": "Martin Luther Commentary on Galatians",
                },
                "book": {"id": BOOK_ID, "name": BOOK_NAME},
                "chapter": {
                    "number": chapter_number,
                    "content": content,
                },
            },
        })
    return {"books": books, "chapters": chapters}


def main():
    parser = argparse.ArgumentParser(
        description="Convert Luther's Galatians commentary EPUB to JSON.GZ."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"EPUB input (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON.GZ output (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"EPUB file not found: {args.input}")

    commentary = make_commentary(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8") as output_file:
        json.dump(commentary, output_file, ensure_ascii=False, separators=(",", ":"))

    total_entries = sum(
        len(chapter["data"]["chapter"]["content"])
        for chapter in commentary["chapters"]
    )
    print(
        f"Wrote {len(commentary['chapters'])} chapters and "
        f"{total_entries} commentary entries to {args.output}"
    )


if __name__ == "__main__":
    main()
