# Tests

This directory contains lightweight regression tests for the synthetic examples.

The tests use only Python's standard library. They run the bundled profiler and
assert that previously fixed table-shape mistakes do not regress:

- FRED-style CSV: `observation_date` is the time column and the series column is the value column.
- IMF BOP/PIP-style wide CSV: `SCALE.ID` is an attribute, not the value column.
- EPU-style wide XLSX: `Year` and `Month` are keys, not value columns.
- World Bank-style report XLSX: title/note rows do not become the table header.

Run:

```bash
python tests/test_profile_examples.py
```
