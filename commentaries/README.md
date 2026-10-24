# Commentary archives

Each `*.json.gz` file is a gzip-compressed UTF-8 JSON document containing one
commentary source. The app requires this top-level shape:

```json
{
  "metadata": {
    "title": "Commentary title",
    "author": "Author name",
    "date_written": "Date or date range"
  },
  "books": [],
  "chapters": []
}
```

- `metadata.title`, `metadata.author`, and `metadata.date_written` are
  non-empty strings displayed in the UI. Use a clear date or date range; if
  exact dates are unknown, state that rather than inventing precision.
- `books` is an array of records with a book `id` and a `name` and/or
  `commonName`. The ID should match the corresponding chapter records.
- `chapters` may be an array of records with `book_id`, integer `chapter`, and
  `data`, or an object keyed by `"BOOK_ID chapter"` (for example, `"GEN 1"`).
  Each record contains a `chapter` object with a `content` array. Content
  items use `number` for the verse when applicable and `content` for their
  text. Text can be a string or an array of strings.

The app discovers `*.json.gz` files in this directory and imports their
metadata and chapter content when building its local database. Keep the
filename stable as the source ID and use the same book IDs in `books` and
`chapters`.

## Book record

Use one record for each book covered by the commentary. `id` must match the
`book_id` used by its chapter records. `name` and/or `commonName` provide the
book name used to associate commentary with a passage.

```json
{
  "id": "GEN",
  "commentaryId": "barnes",
  "name": "Genesis",
  "commonName": "Genesis",
  "numberOfChapters": 50
}
```

## Chapter records

### Array form

In array form, each item has a `book_id`, integer `chapter`, and a `data`
object. The app reads commentary text from `data.chapter.content`.

```json
{
  "chapters": [
    {
      "book_id": "GEN",
      "chapter": 1,
      "data": {
        "commentary": {"id": "barnes", "name": "Barnes' Notes on the Bible"},
        "book": {"id": "GEN", "name": "Genesis"},
        "chapter": {
          "number": 1,
          "content": [
            {
              "type": "verse",
              "number": 1,
              "content": [
                "Commentary text for Genesis 1:1."
              ]
            },
            {
              "type": "introduction",
              "content": ["Commentary on the chapter as a whole."]
            }
          ]
        }
      }
    }
  ]
}
```

Each content item has a `type` and `content`. Use an integer `number` for a
verse-specific item; omit it for an introduction or chapter-level note. The
`content` value may be a string or an array of strings. The app joins string
arrays into a single displayed entry.

### Object/map form

Some sources store chapters as an object keyed by `"BOOK_ID chapter"` instead
of an array. For this form, each value is the chapter record directly (not
wrapped in the array form's `data` object):

```json
{
  "chapters": {
    "GEN 1": {
      "number": 1,
      "content": [
        {
          "type": "verse",
          "number": 1,
          "content": [
            "Commentary text for Genesis 1:1."
          ]
        },
        {
          "type": "verse",
          "number": 2,
          "content": "Commentary text for Genesis 1:2."
        }
      ]
    }
  }
}
```

The map key supplies the book ID and chapter number. Both the array and map
forms become the same displayed chapter content after import.
