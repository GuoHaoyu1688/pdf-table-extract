# Extraction semantics

The JSON document is schema version 1 and is checked against the packaged Draft
2020-12 JSON Schema before it is returned. Coordinates use PDF points with the
top-left origin; pixels from rendering are scaled separately.

Each table contains `id`, `pages`, `headers`, `rows`, `raw_rows`, `bbox`, `engine`,
`page_regions`, and `quality`. `bbox` is the first contributing page's table box.
`page_regions` retains every source page and its cell rectangles. `raw_rows` keeps
the cleaned source spelling before numeric conversion; merged results also retain
the repeated raw header, while final `rows` excludes each page's header.

Quality fields:

- `row_count` and `column_count` describe final data, excluding headers.
- `empty_cell_ratio` counts null and empty-string cells in final rows.
- `numeric_columns` lists zero-based column indexes whose nonempty cells all parse
  as supported decimal values. Normalization uses Decimal and outputs strings.
- `ocr_mean_confidence` is mean recognizer confidence, or null for text engines.
- `notes` records heuristic decisions and review requirements; no metric is a
  ground-truth accuracy guarantee.

Numeric parsing accepts plain decimal numbers, correctly grouped thousands commas,
parenthesized negatives and percentages. For example `1,200.50` becomes `1200.50`,
`(25.00)` becomes `-25.00`, and `12.5%` becomes `0.125`. It preserves leading-zero
identifiers, unsupported currencies, locale-specific decimal commas, and mixed
columns as source text. `--keep-numbers` bypasses normalization entirely.

The default engine first checks ruled lines, then aligned text if no qualifying
ruled table is found. Therefore a page containing both a ruled table and a separate
borderless table may need separate area extractions. Text-mode rows with fewer than
two populated cells are excluded as likely headings/footers. Adjacent unnamed
header fragments are joined to the preceding named column, with a quality note.
Explicit boundaries override that heuristic.

Merged-cell fill applies only to absent cells (null), not empty strings. Downward
fill stays within one extracted page; cross-page merged labels are not invented.
Multi-row headers combine distinct nonempty labels with `/` and propagate missing
parent labels to the right. Duplicate column names are retained in arrays rather
than overwritten in a dictionary.

Cross-page merging requires immediately consecutive page numbers, equal column
counts, header similarity at least 0.85, and left/right extents within 6 PDF points.
The first page's headers are canonical. This is a heuristic for repeated report
tables, not semantic proof that tables belong together. Check `pages`, regions,
raw rows and notes before using combined results.

OCR uses RapidOCR's bundled models against a pypdfium2 render at 2.5 pixels per
point. Text boxes are clustered by vertical center, then assigned to inferred or
explicit column centers. Single-box rows are omitted. This supports simple aligned
tables but can mis-handle multiline cells, missing values, rotated or skewed text,
and multiple tables in one area. Always review OCR output against the source.

Camelot's lattice and stream modes are optional. `--compare` returns both engines'
raw tables and a literal agreement flag. A disagreement is surfaced rather than
hidden by a chosen result. A confidence/accuracy score belongs to the engine's
internal parsing logic and is not externally validated accuracy.

No extraction cache is enabled. `cache.sqlite` stores reusable templates only.
Template snapshots are independent from extraction JSON. Export filenames are
stable and overwrite existing files at the chosen output directory; use a new
directory to preserve earlier runs. An empty extraction is accompanied by warnings.
