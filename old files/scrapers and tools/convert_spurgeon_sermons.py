import argparse
import gzip
import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = ROOT_DIR / "scrapers and tools" / "commentaries_json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "sermons"
AUTHOR = "Charles H. Spurgeon"
AUTHOR_LAST_NAME = "Spurgeon"
ARCHIVE_NAME = "spurgeon.json.gz"
REFERENCE_PREFIX = re.compile(
    r"^\s*See commentary on verse\s+(\d+)\s*(?:\r?\n|$)",
    re.IGNORECASE,
)
MONTH = (
    r"January|February|March|April|May|June|July|August|September|"
    r"October|November|December"
)
SERMON_DATE = re.compile(
    rf"\b(?:{MONTH})[,]?\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+\d{{4}}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTH})[,]?\s+\d{{4}}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)


def extract_title(text, fallback):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:5]:
        line = re.sub(
            r"\s+\*{0,3}\s*(?:A Sermon(?:\s+Delivered)?\b|"
            r"by\s+C\.?\s*H\.?\s*Spurgeon\b).*$",
            "",
            line,
            flags=re.IGNORECASE,
        )
        title = line.strip("*_# `")
        if (title and len(title) <= 180
                and "copyright" not in title.casefold()
                and "all rights reserved" not in title.casefold()):
            return title
    return fallback


def extract_date(text):
    match = SERMON_DATE.search(text[:2500])
    return match.group(0).strip() if match else "Date not recorded"


def transform_source(data, path):
    if isinstance(data, dict) and isinstance(data.get("sermons"), list):
        for sermon in data["sermons"]:
            if not isinstance(sermon, dict) or not isinstance(
                    sermon.get("text"), str):
                raise ValueError(f"Invalid normalized sermon record in {path}")
            references = sermon.get("references")
            if not isinstance(references, list) or not references:
                raise ValueError(f"Missing sermon references in {path}")
            first_reference = references[0]
            fallback = (
                f"{first_reference['book']} {first_reference['chapter']}:"
                f"{first_reference['verse']}"
            )
            title = extract_title(sermon["text"], fallback)
            sermon["title"] = f"{AUTHOR_LAST_NAME} - {title}"
            sermon["author"] = AUTHOR
            sermon["date_written"] = extract_date(sermon["text"])
        data["metadata"] = {
            "title": "Spurgeon Sermons",
            "author": AUTHOR,
            "date_written": "Individual dates are recorded per sermon",
        }
        return data
    if not isinstance(data, dict) or len(data) != 1:
        raise ValueError(f"Expected a single-book Spurgeon JSON file: {path}")

    book, chapters = next(iter(data.items()))
    if not isinstance(chapters, dict):
        raise ValueError(f"Invalid chapter map in {path}")

    sermon_by_text = {}
    location_to_sermon = {}
    aliases = {}

    for chapter_label, verses in chapters.items():
        if not str(chapter_label).isdigit() or not isinstance(verses, dict):
            raise ValueError(f"Invalid chapter record in {path}: {chapter_label}")
        chapter = int(chapter_label)
        for verse_label, raw_text in verses.items():
            if not str(verse_label).isdigit() or not isinstance(raw_text, str):
                raise ValueError(f"Invalid verse record in {path}: {verse_label}")
            verse = int(verse_label)
            location = (chapter, verse)
            text = raw_text.strip()
            if not text:
                continue

            reference = REFERENCE_PREFIX.match(text)
            body = text[reference.end():].strip() if reference else text
            if reference and not body:
                aliases[location] = (chapter, int(reference.group(1)))
                continue
            if not body:
                continue

            sermon = sermon_by_text.get(body)
            if sermon is None:
                fallback_title = f"{book} {chapter}:{verse}"
                title = extract_title(body, fallback_title)
                sermon = {
                    "title": f"{AUTHOR_LAST_NAME} - {title}",
                    "author": AUTHOR,
                    "date_written": extract_date(body),
                    "text": body,
                    "references": [],
                }
                sermon_by_text[body] = sermon
            sermon["references"].append({
                "book": book,
                "chapter": chapter,
                "verse": verse,
            })
            location_to_sermon[location] = sermon

    for location, target in aliases.items():
        visited = set()
        while target in aliases:
            if target in visited:
                raise ValueError(f"Cyclic sermon reference in {path}: {location}")
            visited.add(target)
            target = aliases[target]
        sermon = location_to_sermon.get(target)
        if sermon is None:
            raise ValueError(
                f"Missing target sermon in {path}: {location} -> {target}"
            )
        chapter, verse = location
        sermon["references"].append({
            "book": book,
            "chapter": chapter,
            "verse": verse,
        })

    sermons = list(sermon_by_text.values())
    for sermon in sermons:
        sermon["references"].sort(
            key=lambda ref: (ref["chapter"], ref["verse"])
        )
    return {
        "metadata": {
            "title": "Spurgeon Sermons",
            "author": AUTHOR,
            "date_written": "Individual dates are recorded per sermon",
        },
        "sermons": sermons,
    }


def normalize_source(path):
    with path.open(encoding="utf-8") as source_file:
        data = json.load(source_file)
    normalized = transform_source(data, path)
    serialized = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
    path.write_text(serialized, encoding="utf-8", newline="\n")
    return normalized


def main():
    parser = argparse.ArgumentParser(
        description="Normalize and compress Spurgeon sermon JSON files."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing spurgeon_*.json (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for the compressed archive (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    source_files = sorted(args.input_dir.glob("spurgeon*.json"))
    if not source_files:
        parser.error(f"No spurgeon*.json files found in {args.input_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    combined_sermons = []
    for path in source_files:
        normalized = normalize_source(path)
        combined_sermons.extend(normalized["sermons"])

    archive = {
        "metadata": {
            "title": "Spurgeon Sermons",
            "author": AUTHOR,
            "date_written": "Individual dates are recorded per sermon",
        },
        "sermons": combined_sermons,
    }
    output_path = args.output_dir / ARCHIVE_NAME
    with gzip.open(output_path, "wt", encoding="utf-8", newline="") as output_file:
        json.dump(archive, output_file, ensure_ascii=False, separators=(",", ":"))

    with gzip.open(output_path, "rt", encoding="utf-8") as archive_file:
        verified = json.load(archive_file)
    if (verified.get("metadata") != archive["metadata"]
            or len(verified.get("sermons", [])) != len(combined_sermons)):
        raise ValueError(f"Archive verification failed: {output_path}")

    removed_archives = []
    for source_path in source_files:
        old_archive = args.output_dir / f"{source_path.stem}.json.gz"
        if old_archive == output_path or not old_archive.is_file():
            continue
        old_archive.unlink()
        removed_archives.append(old_archive.name)

    print(
        f"Converted {len(combined_sermons)} sermons from {len(source_files)} "
        f"files into {output_path}."
    )
    if removed_archives:
        print(f"Removed {len(removed_archives)} prior per-book archives.")


if __name__ == "__main__":
    main()
