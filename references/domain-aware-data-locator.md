# Domain-Aware Data Locator

The data locator layer helps an agent answer: *where is the observation I need?* It is designed for long-format macroeconomic datasets such as IMF BOP exports, SDMX-style CSV files, and country-indicator-time panels.

## What It Adds

The reference profiler writes two additional files by default:

- `data_locator_spec.json` — machine-readable locator metadata.
- `data_locator_guide.md` — compact guide for humans and LLM context.

It also writes a `domain_profile` block into `table_manifest.json`.

## Supported Presets

- `auto`: infer from column names.
- `generic`: avoid strong domain assumptions.
- `macro-timeseries`: generic country/indicator/time/value panels.
- `sdmx`: SDMX-like naming such as `REF_AREA`, `FREQUENCY`, `TIME_PERIOD`, `OBS_VALUE`.
- `imf-bop`: IMF Balance of Payments-style long-format exports.

## Role Inference

The profiler looks for common role aliases:

- entity/object: `REF_AREA`, `COUNTRY`, `ECONOMY`, `LOCATION`, `GEO`;
- indicator/series: `INDICATOR`, `BOP_ITEM`, `SERIES_CODE`, `CONCEPT`, `MEASURE`;
- counterpart: `COUNTERPART_AREA`, `PARTNER_AREA`;
- frequency: `FREQUENCY`, `FREQ`;
- time: `TIME_PERIOD`, `TIME`, `DATE`, `YEAR`;
- value: `OBS_VALUE`, `VALUE`, `AMOUNT`;
- attributes: `UNIT_MULT`, `UNIT`, `OBS_STATUS`, `STATUS`.

These are heuristics. For official SDMX datasets, the DSD and codelists are authoritative.

## Codelist Mapping

Optional mapping CSVs can be supplied:

```bash
python skills/data-science/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input bop.csv \
  --out ./profile \
  --domain-preset imf-bop \
  --indicator-mapping indicators.csv \
  --entity-mapping areas.csv
```

Mapping CSVs should contain a code column and preferably `label` and `description` columns. Accepted names include `code`, `id`, `key`, `label`, `name`, `title`, and `description`.

## Domain Full Scan Indicator Catalog

For variable discovery, `--domain-full-scan` performs a read-only streaming pass and creates `domain_indicator_catalog.json`, `domain_indicator_catalog.csv`, and `domain_indicator_catalog.md`. The catalog records indicator code/label, observed coverage, first/last period with data, frequency/unit/scale samples, accounting-entry samples, and rule-based BOP capital-flow groups. The classifier is deliberately transparent: it uses indicator label/code prefixes plus accounting-entry labels; it avoids broad matching on descriptions because that can create false positives across direct, portfolio, and other investment categories.

## Output Interpretation

Use the locator as a navigation map, not as final analytical truth. Before downstream automation:

1. Confirm the inferred roles.
2. Check whether `mapping_required` is true.
3. Check unit/scaling attributes before comparing values.
4. Filter frequency before time-series work if mixed frequencies are detected.
5. Check observation status before treating data as final.
6. Verify `recommended_key` uniqueness if exact extraction matters.

## Wide Time-Column IMF CSV Exports

The profiler explicitly supports IMF web CSV files where observation values are stored in period columns such as `1948`, `1948-Q1`, `1997-S1`, or `2025-Q4`. In this case the locator reports:

- `value_layout: wide_time_columns`;
- `wide_time_value_columns`: detected period columns and sample missingness;
- `time_coverage.layout: wide_time_columns`;
- a recommended key ending with `<time_period_column>`;
- required preprocessing: `reshape_wide_time_columns_to_long`.

For this layout, do not use metadata columns such as `PUBLICATION_DATE`, `UPDATE_DATE`, or `BPM6_BASIS_START_DATE` as observation time. Also do not treat `SCALE.ID` as the value column; it is an attribute used to interpret the numeric cells.

## Known Weak Spots

The locator is less reliable for:

- wide/pivoted files where indicators are columns;
- multi-header spreadsheets and merged-cell reports;
- stacked tables with repeated headers;
- nested SDMX-ML/XML/JSON packages;
- datasets where dimension semantics only exist in separate DSD files;
- PDFs and scanned reports;
- formula-driven Excel models;
- multi-file packages with separate metadata dictionaries.
