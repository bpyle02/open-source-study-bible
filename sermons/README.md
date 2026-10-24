# Sermon archives

Each `*.json.gz` file is a gzip-compressed UTF-8 JSON document. The current
Spurgeon archive, `spurgeon.json.gz`, combines sermons from multiple Bible
books:

```json
{
  "metadata": {
    "title": "Spurgeon Sermons",
    "author": "Charles H. Spurgeon",
    "date_written": "Individual dates are recorded per sermon"
  },
  "sermons": []
}
```

Each item in `sermons` represents one sermon and has this shape:

```json
{
  "title": "Spurgeon - Sermon Title",
  "author": "Charles H. Spurgeon",
  "date_written": "October 8th, 1865",
  "text": "The sermon body...",
  "references": [
    {"book": "2 Kings", "chapter": 2, "verse": 11},
    {"book": "2 Kings", "chapter": 2, "verse": 12}
  ]
}
```

- `title`, `author`, `date_written`, and `text` are strings. A sermon date that
  is absent from the source is recorded as `"Date not recorded"`.
- `references` is a non-empty array of Bible passage locations. Store the
  sermon text once and list every verse where that same sermon should appear;
  do not duplicate the body for each verse.
- The archive-level `metadata` describes the combined source; individual
  sermon dates and titles belong on each sermon record.

The app discovers `*.json.gz` files in this directory and displays a sermon
when a selected passage matches one of its references.
