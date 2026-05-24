# Tabular File Understanding Agent Skill

[简体中文](README.zh-CN.md) | English

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-purple)
![Large CSV](https://img.shields.io/badge/Large%20CSV-ready-green)
![LLM Context](https://img.shields.io/badge/No%20raw%20table%20in%20LLM%20context-orange)
![IMF BOP/PIP](https://img.shields.io/badge/IMF%20BOP%2FPIP-tested-brightgreen)
![Stdlib](https://img.shields.io/badge/Core-Python%20stdlib-lightgrey)

**Understand large and messy tabular files before asking an LLM to analyze them.**

A portable, Python-only agent skill that helps LLM agents understand large, messy, or structurally complex CSV, TSV, Excel, and PDF table files **without loading the full table into the context window**.

Author: [yanyintingyou](https://github.com/yanyintingyou)  
License: MIT

---

## What is this?

`tabular-file-understanding` is an Agent Skills-compatible toolkit for the first and most fragile step in data work: understanding what a tabular file actually contains.

Instead of asking an LLM to read a huge spreadsheet directly, the skill instructs the agent to run a bounded Python profiler and produce compact, auditable artifacts:

- file-level metadata;
- detected tables, sheets, and candidate data regions;
- column names and normalized names;
- inferred column types;
- representative examples;
- sample-based missingness and lightweight statistics;
- structural warnings and ambiguity notes;
- domain-aware data locator metadata for macro/SDMX-like datasets.

The result is a small set of JSON and Markdown files that an LLM can reason over safely.

---

## Why this matters

Large tables are not good LLM context.

A multi-megabyte or multi-gigabyte CSV/Excel file can exceed context limits, flood the conversation with raw rows, and make the model miss the actual structure. This skill solves the first step:

> It gives the agent a reliable structural understanding layer before analysis, cleaning, visualization, modeling, querying, or reporting.

This skill intentionally **does not** perform final data analysis. It profiles structure, records uncertainty, and tells downstream agents where the data lives.

---

## Quick demo with synthetic examples

This repository includes small synthetic files under `examples/` so users can test the skill without downloading real large datasets:

```text
examples/simple_fred.csv
examples/wide_time_imf_mock.csv
examples/wide_measure_epu_mock.xlsx
examples/report_style_worldbank_mock.xlsx
```

Run the regression demo suite:

```bash
python tests/test_profile_examples.py
```

These examples intentionally mirror the shapes that often break naive LLM table-reading workflows: simple FRED time series, IMF BOP/PIP wide time columns, EPU wide measure columns, and World Bank-style report worksheets.

---

## What it can understand by default

The bundled profiler is intentionally conservative, but it already handles a wide range of practical table shapes.

| Table shape | Default understanding | Typical examples |
|---|---|---|
| Simple long time series | Detects time column, value column, row count, date range, and observation key | FRED single-series CSV: `observation_date, IRLTLT01JPM156N` |
| Generic long/panel tables | Detects entity/id columns, date/time columns, categorical columns, measure columns, and likely row grain | `country × date × flow`, survey exports, transaction logs |
| Macro / SDMX-style long data | Infers entity, indicator, counterpart, frequency, time, value, unit/scale/status roles | SDMX CSV, IMF-style country-indicator-time exports |
| IMF BOP/PIP wide-time CSV | Detects descriptor columns plus hundreds of period columns such as `1948`, `1997-S1`, `2025-Q4`; recommends reshaping | Very large IMF BOP/PIP web CSV exports, including multi-GB files |
| Wide measure-column tables | Keeps `Year`/`Month` or `Date` as keys and treats country/index/series columns as parallel value columns | EPU `All_Country_Data.xlsx`: `Year, Month, GEPU_current, GEPU_ppp, Australia, Brazil, ...` |
| Report-style Excel workbooks | Searches for real header/data-start rows instead of assuming row 1; flags notes, merged cells, and title blocks | World Bank historical classification workbooks such as `OGHIST_*.xlsx` |
| Lookup / classification tables | Recognizes code-label/category mapping tables rather than forcing them into numeric time-series form | World Bank `CLASS_*.xlsx`, country-code dictionaries, group membership tables |
| Matrix / cross-tab tables | Flags when both rows and columns carry dimensions and asks for confirmation before analysis | Pivot tables, cross-tab summaries, dense numeric matrices |
| PDF table files | Metadata-first by default; avoids false claims when table extraction is unsupported | PDF reports requiring optional extraction/OCR workflows |

For unknown or hybrid layouts, the skill tells the agent to treat profiler labels as hypotheses, inspect bounded samples, explain uncertainty, and improve heuristics when the pattern is reusable.

---

## Proven stress-test examples

This repository is designed to look good on small CSVs, but its real target is the ugly spreadsheet/data-export world that breaks naive LLM workflows.

### IMF BOP / PIP: huge, wide, and domain-heavy

Large IMF Data Portal CSV exports can be **multi-GB** and may contain descriptor columns plus many wide period columns:

```text
COUNTRY.ID | INDICATOR.ID | COUNTERPART_COUNTRY.ID | FREQUENCY.ID | SCALE.ID | 1948 | 1948-Q1 | ... | 2025-Q4
```

The profiler detects:

```text
value_layout: wide_time_columns
recommended_key: COUNTRY.ID × INDICATOR.ID × COUNTERPART_COUNTRY.ID × FREQUENCY.ID × <time_period_column>
required_preprocessing: reshape_wide_time_columns_to_long
```

It also avoids common mistakes such as treating `PUBLICATION_DATE` as observation time or `SCALE.ID` as the value column.

### World Bank historical classification workbooks

World Bank workbooks often contain title rows, notes, thresholds, legends, merged cells, and real tables that start in the middle of a sheet. The skill searches for actual header rows and data-start rows, so sheets like:

```text
Code | Economy | FY89 | FY90 | FY91 | ...
```

can be understood as wide historical classification tables rather than as broken row-1 spreadsheets.

### EPU all-country workbook

The EPU workbook shape:

```text
Year | Month | GEPU_current | GEPU_ppp | Australia | Brazil | Canada | China | US | ...
```

is classified as:

```text
value_layout: wide_measure_columns
recommended_key: Year × Month
value_columns: GEPU_current, GEPU_ppp, Australia, Brazil, Canada, ...
```

If a tidy panel is needed, the recommended reshape is:

```text
Year × Month × series_or_country → value
```

---

## Supported file types

| Format | Support level | Notes |
|---|---:|---|
| CSV / TSV / delimited text | Strong | Streaming, sample-bounded profiling using Python standard library; supports optional full scan |
| Excel `.xlsx` / `.xlsm` | Best-effort but practical | Reads workbook XML; detects sheets, used ranges, merged cells, header candidates, report-style layouts; does not execute formulas or macros |
| PDF | Metadata-first | Conservative file-level profiling unless enhanced by optional Python libraries |
| Other files | Limited | Reports unsupported/unknown format clearly |

The bundled reference profiler uses **only the Python standard library**. Optional libraries may be used by an agent for deeper inspection, but the core workflow does not require them.

---

## What it produces

Running the profiler creates these core artifacts:

```text
<output_dir>/
├── table_manifest.json
├── table_profile.json
├── table_digest.md
├── ambiguities.md
├── data_locator_spec.json
└── data_locator_guide.md
```

Optional outputs include:

```text
downstream_schema_hint.json
domain_indicator_catalog.json
domain_indicator_catalog.csv
domain_indicator_catalog.md
```

### Artifact roles

- `table_manifest.json` — file inventory, detected table candidates, capability level, output policy, warnings.
- `table_profile.json` — bounded column profiles, inferred types, samples, missingness, lightweight statistics.
- `table_digest.md` — compact LLM-readable structural summary.
- `ambiguities.md` — issues that need confirmation before serious analysis.
- `data_locator_spec.json` — machine-readable locator for entities, indicators, time coverage, observation keys, values, units, statuses, and preprocessing needs.
- `data_locator_guide.md` — compact human/LLM-readable guide for downstream automated extraction.

---

## Quick start

Check optional dependency status:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py --check-deps
```

Profile a file:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile
```

Then read:

```text
./tabular-profile/table_digest.md
./tabular-profile/ambiguities.md
./tabular-profile/data_locator_guide.md
```

For a deeper but slower CSV scan:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile \
  --full-scan
```

---

## Domain-aware data locator for macro / SDMX files

For IMF BOP-style exports, SDMX CSV files, and macroeconomic country-indicator-time panels, the profiler can infer a data locator layer:

- entity/object column, such as country or economy;
- indicator/series column;
- counterpart/partner column when present;
- frequency and time columns;
- observation value column or value-bearing wide columns;
- unit/scaling/status attributes;
- recommended observation key for downstream extraction.

Example for an IMF BOP-like file:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input bop.csv \
  --out ./tabular-profile \
  --domain-preset imf-bop
```

Available domain presets:

- `auto` default;
- `generic`;
- `macro-timeseries`;
- `sdmx`;
- `imf-bop`.

If you have codelists, pass them as CSV files:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input bop.csv \
  --out ./tabular-profile \
  --domain-preset sdmx \
  --indicator-mapping indicators.csv \
  --entity-mapping areas.csv
```

Mapping files should use columns like `code,label,description`. Without mappings, the profiler reports codes and marks that external codelists are required.

### Full indicator catalog for IMF BOP/PIP

For variable discovery in very large IMF BOP/PIP files, add `--domain-full-scan`:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input bop.csv \
  --out ./bop-profile \
  --domain-preset imf-bop \
  --domain-full-scan
```

This creates `domain_indicator_catalog.json`, `.csv`, and `.md`, including indicator coverage, period range, units/scales, accounting-entry samples, and transparent rule-based capital-flow classification.

---

## Adaptive output control

By default, the profiler uses:

```bash
--output-policy auto
```

This keeps output artifacts small without changing the original input file.

| Input scale | Auto policy | What happens |
|---|---:|---|
| Small files / normal-width tables | `full` | Keeps full profiling detail in JSON artifacts |
| Medium files or moderately wide tables | `balanced` | Keeps samples, but reduces examples/top values |
| Large files or wide tables | `compact` | Omits row samples and limits some per-column detail |
| Very large files or extremely wide tables | `very-compact` | Strongly limits examples and detailed column profiles |

Default thresholds:

- small-file threshold: 10 MB;
- large-file threshold: 100 MB;
- huge-file threshold: 1 GB;
- medium-width threshold: 200 columns;
- large-width threshold: 1,000 columns;
- huge-width threshold: 5,000 columns.

Manual override:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile \
  --output-policy compact
```

---

## Privacy options

For sensitive files, use lightweight sample redaction:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --redact-samples
```

For stricter schema-only profiling without row samples:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --no-samples
```

You can also limit retained cell length:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --redact-samples \
  --max-cell-chars 80
```

---

## Optional downstream hints

This skill stops at structural understanding, but it can write a small optional hint file for downstream workflows:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile \
  --schema-preset generic
```

Available presets:

- `generic`
- `rag`
- `sql`
- `none` default

---

## Repository layout

```text
.
├── AGENTS.md
├── CLAUDE.md
├── LICENSE
├── README.md
├── README.zh-CN.md
├── .gitignore
├── .cursor/
│   └── rules/
│       └── tabular-file-understanding.mdc
├── examples/
│   ├── README.md
│   ├── report_style_worldbank_mock.xlsx
│   ├── simple_fred.csv
│   ├── wide_measure_epu_mock.xlsx
│   └── wide_time_imf_mock.csv
├── tests/
│   ├── README.md
│   └── test_profile_examples.py
└── skills/
    └── tabular-file-understanding/
        ├── SKILL.md
        ├── scripts/
        │   └── profile_tabular_file.py
        └── references/
            ├── adaptive-output-policy.md
            ├── compatibility-notes.md
            ├── dependency-policy.md
            ├── domain-aware-data-locator.md
            ├── downstream-schema-hints.md
            ├── output-schema.md
            ├── privacy-and-security.md
            ├── table-structure-patterns.md
            └── validation-checklist.md
```

---

## Agent compatibility

This repository is designed to work across multiple agent ecosystems:

- Agent Skills / Hermes / OpenClaw: use `skills/tabular-file-understanding/SKILL.md`.
- OpenAI Codex-compatible agents: use `AGENTS.md`.
- Claude Code-compatible agents: use `CLAUDE.md`.
- Cursor: use `.cursor/rules/tabular-file-understanding.mdc`.

---

## Installation examples

Clone the repository:

```bash
git clone https://github.com/yanyintingyou/tabular-file-understanding-agent-skill.git
cd tabular-file-understanding-agent-skill
```

Use directly:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input your_file.csv \
  --out ./tabular-profile
```

For Agent Skills-compatible systems, copy or reference:

```text
skills/tabular-file-understanding/
```

---

## Design principles

1. **Do not load raw large tables into LLM context.**
2. **Use Python only.**
3. **Use the standard library by default.**
4. **Control generated JSON size adaptively for large or wide files.**
5. **For macro/SDMX-like data, generate a locator rather than loading raw observations into context.**
6. **Never auto-install dependencies without user approval.**
7. **Never overwrite the original file.**
8. **Separate structural facts from semantic guesses.**
9. **Treat profiler labels as hypotheses, not an oracle.**
10. **Prefer compact artifacts over verbose chat output.**

---

## Known limitations

- The bundled script is conservative and standard-library only.
- CSV profiling is sample-bounded by default, though `--full-scan` improves row/width checks.
- For large or very wide files, JSON artifacts may be intentionally reduced by the adaptive output policy.
- Excel support reads `.xlsx` XML and does not execute formulas, macros, external links, or the Excel calculation engine.
- PDF support is metadata-first unless enhanced by optional Python libraries.
- Redaction is lightweight and pattern-based; it is not a full DLP system.
- The data locator is heuristic. Official DSD/codelists remain authoritative for SDMX/IMF datasets.
- Complex multi-row headers, stacked subtables, formulas, nested data packages, scanned PDFs, and domain-specific conventions may still require custom extractors.
- The skill creates structural understanding, not final analysis.

---

## Validation

Run a basic smoke test:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py --check-deps
```

Create a small CSV and profile it:

```bash
printf 'country,date,flow\nUS,2024-01-01,1.2\nCN,2024-01-02,3.4\n' > /tmp/tfu-smoke.csv

python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input /tmp/tfu-smoke.csv \
  --out /tmp/tfu-smoke-profile
```

Expected files:

```text
/tmp/tfu-smoke-profile/table_manifest.json
/tmp/tfu-smoke-profile/table_profile.json
/tmp/tfu-smoke-profile/table_digest.md
/tmp/tfu-smoke-profile/ambiguities.md
/tmp/tfu-smoke-profile/data_locator_spec.json
/tmp/tfu-smoke-profile/data_locator_guide.md
```

For the full checklist, see:

```text
skills/tabular-file-understanding/references/validation-checklist.md
```

---

## License

MIT License. See [LICENSE](LICENSE).

---

## Author

Created by [yanyintingyou](https://github.com/yanyintingyou).
