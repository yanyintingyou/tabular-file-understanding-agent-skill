# Security Policy

## Supported versions

This repository is currently a lightweight Agent Skill. Security fixes are applied to the latest version on the `main` branch.

## Data handling model

The bundled profiler is designed for local, read-only structural inspection:

- It does not upload input files to external services.
- It does not execute spreadsheet formulas, macros, embedded objects, scripts, or links.
- It does not modify or overwrite the source file.
- It writes profiling artifacts to the explicit output directory passed by `--out`.
- It uses only the Python standard library by default.

## Sensitive data caveat

Profiling artifacts may contain bounded examples and top values unless sample suppression/redaction is enabled.

For sensitive files, use one of these modes:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --redact-samples
```

or, for stricter suppression:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --no-samples
```

`--redact-samples` is pattern based and is not a full DLP system. `--no-samples` removes row-level samples and column-level examples/top-values from `table_profile.json`, and suppresses sample-derived locator indexes/frequency samples/key checks/value summaries from locator artifacts. Structural metadata such as column names, inferred types, and locator column-role names remain.

## Reporting vulnerabilities

Please open a GitHub issue with a minimal reproduction that does not include real secrets or private data. If the report includes sensitive information, contact the repository owner privately before sharing details publicly.
