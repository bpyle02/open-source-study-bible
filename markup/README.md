# Saved verse markup

`verse-markup.json.gz` is a gzip-compressed UTF-8 JSON file written by the
app. The top-level structure is:

```json
{
  "version": 1,
  "verses": {
    "BSB|GEN|1|26": {
      "highlight": "#fff2a8",
      "underline": "#b9d9f5",
      "bracket": "#f5c2df"
    }
  }
}
```

- `version` identifies the storage format.
- Each key in `verses` is `TRANSLATION_ID|BOOK_ID|CHAPTER|VERSE`, so markup
  belongs to one specific verse in one translation.
- Each verse value is an object containing any combination of `highlight`,
  `underline`, and `bracket`. Each value is a six-digit hexadecimal color in
  `#RRGGBB` format.
- An empty or removed verse markup is omitted from `verses`.

The app reads this file when a passage loads and writes updates when markup is
applied or removed. Keep the version and key format intact when editing it
manually.
