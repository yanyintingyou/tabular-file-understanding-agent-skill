# Changelog

All notable changes to this project are documented here.

## 1.1.1 — 2026-05-24

### Fixed

- Made `--no-samples` remove both row-level samples and column-level value samples (`examples` and `top_values_sample`) from `table_profile.json`, and suppress sample-derived values in locator artifacts.
- Made duplicate or blank CSV headers unique for stable downstream JSON/profile handling.
- Marked short-code first rows such as `US,JP,CN` as medium-confidence/ambiguous headers instead of high-confidence headers.
- Added explicit `profiling_success` and `understanding_quality` fields so invalid/empty workbooks are not mistaken for successful profiling.
- Removed duplicate unreachable logic in `guess_shape_type()`.
- Passed the pre-policy manifest into `build_data_locator()` instead of an empty placeholder.

### Improved

- Compact/very-compact output policy now prioritizes inferred entity/indicator/time/value/unit/scale/status columns and wide period columns instead of blindly keeping only the first N columns.
- Output-policy redaction now propagates the `--redact-samples` setting during secondary truncation.
- Added regression coverage for privacy, duplicate headers, ambiguous header rows, invalid XLSX files, and wide files with important columns near the tail.
- Added GitHub Actions CI for Python 3.9–3.12.
- Expanded README documentation on installation, output examples, and Excel/PDF/privacy limits.

## 1.1.0 — Initial public release

- Python-standard-library profiler for CSV/TSV, `.xlsx`/`.xlsm`, and metadata-first PDF profiling.
- Agent Skills-compatible layout under `skills/tabular-file-understanding/`.
- Domain-aware locator for macro/SDMX/IMF BOP-like files.
- Adaptive output policies for large and wide files.
- Synthetic examples and regression tests for FRED, IMF wide-time, EPU wide-measure, and World Bank report-style layouts.
