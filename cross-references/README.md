# Cross-reference sources

Place one `.json.gz` source file per cross-reference dataset in this folder. Each file should contain a JSON object with a `source` id, an optional `label`, and a `references` array. Each reference can be an object like `{ "source": "GEN.1.1", "target": "GEN.1.2", "votes": 10 }`. Targets may be a single verse or a verse range, such as `GEN.1.2-GEN.1.4`. Source and target references use `BOOK.CHAPTER.VERSE`, where `BOOK` is a Bible book ID from the translation archives.

The application loads every source and displays a separate toggle for each in
Settings. Included sources are OpenBible and the Treasury of Scripture
Knowledge (TSK); additional `.json.gz` files using the same format are
discovered automatically.

A source may also include a `notes` array for formatted source text associated
with each source verse. Each note has a `source` reference and Markdown `text`,
for example `{ "source": "GEN.1.1", "text": "**God:** Psalms 33:6" }`.
The reader preserves this Markdown and makes recognized scripture references
clickable in the popup.
