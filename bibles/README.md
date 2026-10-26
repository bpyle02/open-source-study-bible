# Bible translation archives

Each `*_translation.json.gz` file is a gzip-compressed UTF-8 JSON document. The
JSON object has this top-level shape:

```json
{
  "translation_id": "BSB",
  "books": [],
  "chapters": []
}
```

- `translation_id` identifies the translation and is used in the archive
  filename (for example, `BSB` in `bsb_translation.json.gz`).
- `books` is an ordered array of book records. Records include an OSIS-style
  `id` such as `GEN`, a display `name`, `translationId`, and
  `numberOfChapters`. Other source fields may also be present.
- `chapters` is an array of chapter records. Each has `book_id`, an integer
  `chapter`, and a `data` object containing the source chapter information.
  The nested `data.chapter.content` array holds headings, verses, and other
  content blocks. Some translations include footnotes in
  `data.chapter.footnotes`; BSB footnotes are stored separately in
  `footnotes/bsb_footnotes.json.gz`.

## Book record

A book record identifies the book and its position and chapter count within
the translation. The source may include additional metadata, such as hashes,
chapter links, and verse totals.

```json
{
  "id": "GEN",
  "translationId": "BSB",
  "name": "Genesis",
  "commonName": "Genesis",
  "title": "Genesis",
  "order": 1,
  "numberOfChapters": 50
}
```

## Chapter record

Each item in the top-level `chapters` array identifies a book and chapter.
`data` retains the source chapter metadata, with the actual passage content
under `data.chapter.content`.

```json
{
  "book_id": "GEN",
  "chapter": 1,
  "data": {
    "book": {"id": "GEN", "name": "Genesis"},
    "chapter": {
      "number": 1,
      "content": [
        {
          "type": "heading",
          "content": ["The Creation"]
        },
        {
          "type": "verse",
          "number": 1,
          "content": ["In the beginning God created the heavens and the earth."]
        },
        {
          "type": "verse",
          "number": 3,
          "content": [
            "And God said, \"Let there be light,\"",
            {"noteId": 0},
            "and there was light."
          ]
        }
      ],
      "footnotes": [
        {
          "noteId": 0,
          "caller": "+",
          "text": "Cited in 2 Corinthians 4:6",
          "reference": {"chapter": 1, "verse": 3}
        }
      ]
    }
  }
}
```

Content blocks are source-defined. In particular, `heading` blocks have text
in `content`, while `verse` blocks also have an integer `number`. Verse
`content` can mix plain strings with objects such as `{"noteId": 0}`; that
object refers to an item in the chapter's `footnotes` array where the source
keeps footnotes embedded. BSB retains its note markers in verse content, with
the corresponding notes stored separately in `footnotes/`.

The app reads these files at startup to build its local database. Keep the
translation ID, book IDs, and chapter numbers consistent throughout an
archive.
