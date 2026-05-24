# Table Structure Patterns

Use these patterns to describe table structure in `table_digest.md`. Always label them as structural guesses unless the evidence is strong.

## Long Table

A long table has one observation per row and variables in columns. It often has identifier columns, time columns, category columns, and measure columns.

Signals:

- One or more date-like columns.
- Repeated entity identifiers.
- Moderate number of columns.
- Numeric measure columns.

Example digest language:

> This appears to be a long-format panel table. One row likely represents an entity-time observation.

## Wide Time-Series Table

A wide table stores time periods as columns.

Signals:

- Many columns named like years, months, quarters, or dates.
- First few columns are entity descriptors.
- Numeric values spread across many period columns.

Example digest language:

> This appears to be a wide time-series table where columns from 2000 to 2025 likely represent periods.

IMF-specific wide signal:

> IMF web CSV exports may combine descriptor columns (`COUNTRY.ID`, `INDICATOR.ID`, `FREQUENCY.ID`, `SCALE.ID`, `UNIT.ID`) with hundreds of period columns (`1948-Q1`, `2024`, `2025-Q4`). The period columns are the value-bearing observation columns and should be reshaped to long format before analysis.

## Matrix / Cross-Tab

A matrix table has both row and column headers carrying meaning.

Signals:

- First column contains categories.
- Column names are also categories or periods.
- Few free-text columns.
- Dense numeric interior.

Example digest language:

> This may be a cross-tab or matrix table. Both row labels and column labels appear to encode dimensions.

## Report Layout

A report layout is not a clean dataset. It may include titles, notes, subtotal rows, blank separators, and multiple blocks.

Signals:

- Many blank rows or columns.
- Repeated section headings.
- Subtotal or total rows.
- Multiple candidate header rows.
- Merged cells in Excel.

Example digest language:

> This looks like a report-style worksheet rather than a clean rectangular dataset. Further user confirmation is needed before analysis.

## Multi-Table Sheet

A worksheet or PDF page may contain several separate table blocks.

Signals:

- Non-contiguous populated regions.
- Repeated header-like rows.
- Large blank gaps.
- Different row widths in different regions.

Example digest language:

> The sheet may contain multiple table blocks. The profiler selected the largest block as the primary candidate, but the user should confirm.

## Common Semantic Guesses

Column names may suggest semantic roles:

- `id`, `code`, `ticker`, `cusip`, `isin`: identifier
- `date`, `year`, `month`, `quarter`, `time`: time
- `country`, `region`, `sector`, `category`, `asset_class`: category
- `amount`, `value`, `flow`, `sales`, `revenue`, `aum`: measure
- `rate`, `ratio`, `pct`, `percent`, `%`: percentage
- `currency`, `ccy`, `usd`, `eur`, `cny`: currency-related

These are guesses. Do not treat them as confirmed business definitions.
