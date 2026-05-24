# Dependency Policy

This skill is designed for broad agent compatibility and should not assume a rich Python environment.

## Required Dependency Level

The bundled profiler requires only:

- Python 3.9+
- Python standard library modules such as `csv`, `json`, `zipfile`, `xml.etree.ElementTree`, `statistics`, `datetime`, `argparse`, and `pathlib`

No external Python package is required for the reference implementation.

## Optional Enhancements

Agents may use optional Python libraries only if they are already installed or the user explicitly approves installation.

Useful optional libraries include:

- `pandas` for richer CSV/Excel profiling
- `openpyxl` or `python-calamine` for better Excel handling
- `duckdb` or `polars` for faster large-file scans
- `pyarrow` for Parquet outputs
- `pdfplumber` or `pymupdf` for PDF text/table extraction

These are optional. Missing libraries must not cause total failure.

## Required Agent Behavior When a Library Is Missing

1. Detect the missing library.
2. Continue with the best available Python-only fallback.
3. Mark the run as `limited` or `basic` if needed.
4. List skipped capabilities in `features_unavailable`.
5. Explain the limitation in `ambiguities.md`.
6. Do not install anything unless the user explicitly approves.

## Installation Guidance

If the user asks for better profiling quality, recommend an isolated environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install pandas openpyxl duckdb pyarrow charset-normalizer
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install pandas openpyxl duckdb pyarrow charset-normalizer
```

Do not put installation commands into the default workflow. Treat installation as an explicit user-authorized upgrade path.
