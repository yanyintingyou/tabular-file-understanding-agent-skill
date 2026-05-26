---
name: tabular-file-understanding
description: Extracts structure, schemas, samples, and warnings from large CSV, Excel, and PDF table files using Python-only profiling. Use before asking an LLM to reason about tabular files.
license: MIT
compatibility: Python 3.9+. Bundled profiler uses only the Python standard library. Compatible with Agent Skills, Claude Code, OpenClaw, Codex via agent instruction file, and Cursor via rules.
metadata: {"author":"yanyintingyou","homepage":"https://github.com/yanyintingyou","version":"1.1.1","category":"data-understanding","tags":"csv,xlsx,pdf,spreadsheet,table,profiling,llm-context"}
---

# Tabular File Understanding

## Purpose

Use this skill when a user provides or references a large CSV, Excel workbook, or PDF table file and the agent needs to understand the table's structure before doing any downstream task. The goal is not to analyze the user's substantive question yet. The goal is to create a compact, reliable, LLM-readable structural digest of the file.

This skill converts a potentially huge tabular file into a small set of artifacts:

- `table_manifest.json` — file-level and table-level inventory.
- `table_profile.json` — schema, inferred types, examples, and lightweight statistics.
- `table_digest.md` — concise human/LLM-readable structural summary.
- `ambiguities.md` — issues that need user confirmation before serious analysis.
- `data_locator_spec.json` — optional-but-default domain-aware locator metadata for macro/SDMX-like files.
- `data_locator_guide.md` — human/LLM-readable guide for finding indicators, entities, time ranges, and observation values.

## Core Rule

Never paste a large table directly into the model context. Use Python to inspect, sample, and summarize it. Return only the compact digest and ambiguity list to the user unless they explicitly ask for raw samples or full outputs.

## Tool Policy

Use Python only. Do not require external command-line tools such as DuckDB CLI, LibreOffice, Java, Ghostscript, `xlsx2csv`, `tabula`, shell pipelines, or database servers. If the host agent exposes a shell-like tool, use it only to run Python, for example:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py --input /path/to/file.csv --out /path/to/output
```

The bundled reference script uses only the Python standard library. Agents may write additional Python code if needed, but should preserve the same output contract. For sensitive files, run with `--redact-samples` or `--no-samples`. If a downstream workflow needs a routing hint, add `--schema-preset generic`, `--schema-preset rag`, or `--schema-preset sql`. For macroeconomic or SDMX-style time-series files, use `--domain-preset auto|macro-timeseries|sdmx|imf-bop` and optional `--indicator-mapping` / `--entity-mapping` CSV codelists to generate a data locator.

## When to Use

Use this skill when the user:

- uploads or points to a large CSV, TSV, Excel `.xlsx`, or PDF table file;
- asks what is inside a spreadsheet or tabular dataset;
- wants an LLM to understand a table before analysis, cleaning, querying, modeling, visualization, reporting, or summarization;
- says the file is too large for context;
- asks for schema discovery, table structure, field descriptions, sheet inventory, sample rows, or ambiguity detection.

Do not use this skill for:

- final statistical modeling or econometric inference;
- business conclusions from the data;
- irreversible data cleaning;
- editing the original spreadsheet;
- OCR-heavy scanned PDFs unless the user has provided an OCR text/table layer or explicitly asks for best-effort metadata only.

## Standard Workflow

1. **Locate the file.** Determine the exact local path or ask the user to provide/upload it.
2. **Do not read the whole file into context.** Avoid `cat`, massive dataframe prints, or full worksheet dumps.
3. **Run the profiler.** Use the bundled Python script or equivalent Python-only code:

   ```bash
   python <skill_dir>/scripts/profile_tabular_file.py --input <file> --out <output_dir>
   ```

   For a deeper but slower scan of large CSV files:

   ```bash
   python <skill_dir>/scripts/profile_tabular_file.py --input <file> --out <output_dir> --full-scan
   ```

4. **Let adaptive output control protect storage/context size.** By default, `--output-policy auto` keeps full JSON detail for small files, reduces examples for medium files, omits row samples for large files, and limits detailed column profiles for very large or extremely wide tables. Override with `--output-policy full|balanced|compact|very-compact` only when needed.
5. **For sensitive files, protect samples.** Use `--redact-samples` for lightweight masking or `--no-samples` when row-level samples and column-level value examples/top-values should not be written.
6. **Apply the profiler flexibly rather than mechanically.** Real-world tables are open-ended; the known patterns are heuristics, not a closed taxonomy. If the profiler's `shape_type`, `value_column`, `recommended_key`, or primary-table guess conflicts with sampled evidence, treat the profiler output as a hypothesis, inspect a small bounded slice, override the interpretation in your report, and improve the heuristic when the fix is durable.
7. **Read only the compact outputs:**
   - `table_digest.md`
   - `ambiguities.md`
   - for macro/SDMX-like data, `data_locator_guide.md`
   - optionally `table_manifest.json`, `data_locator_spec.json`, and selected parts of `table_profile.json`
8. **For macro/SDMX-like files, inspect the locator.** Confirm inferred roles such as entity, indicator, counterpart, frequency, time, value, unit, and status before automated extraction.
9. **Report capability and output policy.** State whether profiling was `basic`, `standard`, or `limited`, whether row counts/statistics are sampled or complete, and whether JSON output was `full`, `balanced`, `compact`, or `very-compact`.
10. **State ambiguities before proceeding.** If table boundaries, header rows, units, date columns, primary tables, or reduced output artifacts are uncertain, ask the user to confirm or clearly label assumptions.
11. **Use the digest as context for downstream work.** Subsequent analysis should be driven by the user's actual goal, not by this skill.

## Flexible Agent Reasoning Prompt

Use this prompt whenever the profiler output is ambiguous or the table does not fit a known template:

> Treat the profiler output as structured evidence, not as an oracle. First separate file mechanics from domain meaning: locate sheets/tables, real header rows, data-start rows, metadata/title/note areas, keys, time fields, and value-bearing cells. Then infer the likely observation grain. Ask “what does one row represent?” and, for wide tables, “what does one value-bearing column or cell represent?” Real-world tables may be long panels, wide time series, wide measure matrices, cross-tabs, lookup tables, stacked sub-tables, report-style sheets, code-label dictionaries, sparse matrices, or hybrids. If mechanical labels conflict with samples, explain the corrected interpretation, mark uncertainty, and, when broadly useful, patch the heuristic and rerun.

Classify understanding quality as:

- `well understood` — table boundaries, header, row grain, keys, time, values/categories, and reshape needs are clear;
- `partially understood` — broad structure is clear but semantic meaning, multi-header reconstruction, formulas, or subtable boundaries remain uncertain;
- `not well understood` — the profiler cannot reliably locate headers, values, or observation grain.

Do not use domain priors as a shortcut. A variable/column is useful only when the file evidence and the user's stated goal support that interpretation.

## Output Contract

Every run should produce the canonical files below. If a format cannot be fully profiled, still produce all core files with clear limitations. The data locator files are generated by the bundled profiler by default and are especially useful for macro/SDMX-style datasets.

### `table_manifest.json`

File-level inventory and detected table candidates. Must include source path, file type, size, profiling mode, capability level, warnings, and table identifiers.

### `table_profile.json`

Detailed but bounded table structure. Must include fields/columns, inferred data types, examples, missingness estimates, categorical top values, numeric ranges when available, and confidence notes.

### `table_digest.md`

A concise Markdown summary meant to be loaded into LLM context. It should answer:

- What kind of file is this?
- How many candidate tables/sheets were found?
- Which table appears primary?
- What does one row likely represent?
- What are the key columns?
- Which fields appear to be identifiers, dates, categories, quantities, percentages, or text?
- What warnings should the user know before analysis?

### `ambiguities.md`

A user-facing list of unresolved issues, such as multiple candidate tables, uncertain headers, mixed date formats, suspicious units, formula-heavy sheets, sampled-only statistics, or unsupported PDF extraction.

### `data_locator_spec.json`

A compact domain-aware locator specification. It records the inferred dataset type, column roles, indicator index, entity/object index, time coverage, recommended observation key, value column, attribute columns, and preprocessing warnings. For IMF BOP / SDMX-style files, this is the main artifact for downstream automation.

### `data_locator_guide.md`

A readable guide explaining how to locate observations, e.g. filter by entity/country code, indicator code, frequency, and time period, then read the value column with units/status checks.

For the exact schema, see `references/output-schema.md`.


## Domain-Aware Data Locator

For macroeconomic long-format panels, SDMX exports, and IMF BOP-like files, the profiler now creates a data locator layer in addition to generic table profiling. Use it when the user needs to know:

- which column represents the object/entity, such as country or economy;
- which column represents the indicator or series code;
- which column represents time and frequency;
- where numeric observations are stored;
- which unit, scaling, status, or counterpart columns must be checked;
- how to form a stable key for automated downstream extraction.

Recommended command for IMF BOP-style files:

```bash
python <skill_dir>/scripts/profile_tabular_file.py \
  --input <file.csv> \
  --out <output_dir> \
  --domain-preset imf-bop
```

With local codelists:

```bash
python <skill_dir>/scripts/profile_tabular_file.py \
  --input <file.csv> \
  --out <output_dir> \
  --domain-preset sdmx \
  --indicator-mapping indicators.csv \
  --entity-mapping areas.csv
```

The mapping files should be CSV files with columns such as `code,label,description`. If mappings are absent, the locator reports codes only and explicitly marks that external codelists are needed.

Supported domain presets:

- `auto` — default; infer generic vs macro/SDMX-like structure from column names.
- `generic` — force generic handling and avoid strong domain claims.
- `macro-timeseries` — generic macro panel/time-series layout.
- `sdmx` — SDMX-like column naming such as `REF_AREA`, `TIME_PERIOD`, `OBS_VALUE`.
- `imf-bop` — IMF Balance of Payments-style long-format exports.



### Domain full scan for indicator discovery

When the user asks which variables/indicators are available in a very large IMF BOP/PIP file, run the profiler with:

```bash
python <skill_dir>/scripts/profile_tabular_file.py \
  --input <bop_or_pip.csv> \
  --out <output_dir> \
  --domain-preset imf-bop \
  --domain-full-scan
```

This streams the file read-only and writes:

- `domain_indicator_catalog.json`
- `domain_indicator_catalog.csv`
- `domain_indicator_catalog.md`

The catalog groups indicators using transparent prefix/accounting-entry rules and marks likely BOP financial-flow transaction series with `is_bop_financial_flow_transaction`. Use this catalog before answering substantive questions about which variables are suitable for cross-border capital-flow research.

### IMF Web CSV wide-time exports

Some IMF Data Portal CSV exports, including large BOP/PIP files, are not classic long SDMX tables. They often contain many descriptor/dimension columns followed by wide observation columns named like `1948`, `1948-Q1`, `1997-S1`, or `2025-Q4`. In that layout:

- `PUBLICATION_DATE`, `UPDATE_DATE`, and `BPM6_BASIS_START_DATE` are metadata, not observation time.
- `OBS_MEASURE` may say `OBS_VALUE`, but the actual values are stored in year/quarter/semester columns.
- Stable automation should use code columns such as `COUNTRY.ID`, `INDICATOR.ID`, `COUNTERPART_COUNTRY.ID`, `FREQUENCY.ID`, plus a selected `<time_period_column>`.
- Downstream extraction should first reshape wide time columns into long form.

The bundled profiler detects this as `value_layout: wide_time_columns` and records `wide_time_value_columns` in `data_locator_spec.json`.

## File-Type Guidance

### CSV / TSV / delimited text

Use streaming Python processing. Detect dialect, delimiter, quote behavior, header confidence, row-width consistency, sample rows, inferred column types, empty-value patterns, top categories, date-like fields, and numeric ranges. Prefer sample-bounded scans by default. Use full scans only when the user requests exactness or the file is manageable.

### Excel `.xlsx`

Treat the workbook as a container. Identify sheets, dimensions, merged cells, formulas, hidden-like structure where detectable, candidate used ranges, header rows, and sample rows. With the standard-library reference script, `.xlsx` profiling is best-effort and XML-based. It can inspect workbook structure and sample cell values, but it is not a full Excel calculation engine.

### PDF

PDF support is metadata-first and conservative. Without dedicated PDF table extraction or OCR libraries, the Python-only reference script reports file-level metadata and crude page-count signals only. It must not claim authoritative table extraction from PDFs. If the PDF appears scanned or table extraction is unsupported, say so explicitly.

## Dependency Policy

The skill must remain useful even when third-party Python libraries are missing. The bundled script uses only the Python standard library. If an agent writes its own Python helper with optional libraries, it must:

1. Check import availability first.
2. Fall back to standard-library profiling where possible.
3. Mark unsupported features in `table_manifest.json` and `ambiguities.md`.
4. Never auto-install packages without explicit user approval.
5. Never fail the entire task if a partial structural digest can still be produced.

See `references/dependency-policy.md`.

## Safety and Privacy

- Treat input files as untrusted.
- Do not execute formulas, macros, embedded objects, scripts, or links from spreadsheets.
- Do not overwrite the original file.
- Write outputs to a separate directory.
- Do not print large samples or raw datasets into chat.
- Avoid exposing sensitive row-level or column-level sample values unless the user asks for samples.
- Make clear when statistics are sample-based rather than complete.
- Make clear when adaptive output control reduced `table_profile.json`.
- Use `--redact-samples` or `--no-samples` for sensitive files. `--no-samples` removes row samples and column-level `examples` / `top_values_sample`, and suppresses sample-derived locator indexes/frequency samples/key checks/value summaries, but it is still structural profiling, not a full DLP system.

## Interpretation Rules

The digest may include structural guesses, but they must be labeled as guesses. Use wording such as:

- "likely a long-format panel table"
- "appears to be a date column"
- "may represent units or currency"
- "requires user confirmation"

Do not infer business meaning beyond what column names, sample values, and file metadata support.

## Known Limitations

- The standard-library profiler is intentionally conservative. It improves LLM understanding but does not guarantee semantic correctness.
- The data locator is role inference, not authoritative metadata. For SDMX/IMF files, official DSD/codelist files remain the source of truth.
- Locator indexes are sample-based unless the workflow is extended with a full domain scan; rare indicators/entities may be absent from the displayed top values.
- Complex structures such as multi-header spreadsheets, cross-tab matrices, nested JSON/XML, hierarchical SDMX dimensions, pivoted time columns, ragged report layouts, multi-table PDFs, merged-cell workbooks, and formula-driven Excel models may require custom parsing beyond this skill.
- CSV `--full-scan` gives a more complete row count and row-width check; column profiles remain bounded by sampled rows unless an agent writes an enhanced Python backend.
- `.xlsx` support is XML-based and does not calculate formulas, evaluate macros, parse old `.xls`, resolve Excel style-based date serials, or fully reconstruct complex Excel UI state.
- PDF support is metadata-first unless the user provides extracted tables or approves optional Python PDF libraries.
- Pattern-based sample redaction is not a complete DLP system. For highly sensitive files, use `--no-samples`.
- Adaptive output control reduces generated JSON artifacts only; it never modifies the original data file.

## Quick Response Template

After running the profiler, respond with:

```markdown
## Tabular structure digest created

- Source file: ...
- File type: ...
- Profiling mode: sampled/full/limited
- Tables or sheets detected: ...
- Primary table guess: ...
- Approximate rows/columns: ...
- Key structural interpretation: ...
- Main warnings: ...
- Ambiguities requiring confirmation: ...

Artifacts written to: <output_dir>
```

Then ask or proceed according to the user's original downstream request.

## References

- Output schema: `references/output-schema.md`
- Dependency policy: `references/dependency-policy.md`
- Table structure patterns: `references/table-structure-patterns.md`
- Cross-agent compatibility notes: `references/compatibility-notes.md`
- Privacy and security notes: `references/privacy-and-security.md`
- Validation checklist: `references/validation-checklist.md`
- Optional downstream schema hints: `references/downstream-schema-hints.md`
- Adaptive JSON output policy: `references/adaptive-output-policy.md`
- Domain-aware data locator: `references/domain-aware-data-locator.md`
