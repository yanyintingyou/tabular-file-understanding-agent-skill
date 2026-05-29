# Privacy and Security Notes

This skill is designed to understand table structure, not to expose raw data.

## Recommended Defaults

- Keep `--output-policy auto` enabled so large files produce smaller artifacts automatically.
- Keep row samples small.
- Truncate long cell values.
- Do not print raw datasets into chat.
- Use `--redact-samples` when files may contain personal, financial, customer, employee, or confidential data.
- Use `--no-samples` when even small row samples and column-level value examples/top-values should not be written to profiling artifacts.

Example:

```bash
python skills/data-science/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --redact-samples \
  --max-cell-chars 80
```

Strict mode:

```bash
python skills/data-science/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input sensitive.csv \
  --out ./tabular-profile \
  --no-samples
```

## Spreadsheet Safety

Agents must not execute spreadsheet macros, external links, embedded scripts, or formulas. The bundled profiler reads static XML/cell values only and does not calculate formulas.

## Limitations of Redaction

The bundled redaction is deliberately lightweight and pattern-based. It catches common email-like, phone-like, and long-number values in samples. It is not a complete data-loss-prevention system. For highly sensitive files, prefer `--no-samples`; this removes row-level samples and column-level value examples/top-values and suppresses sample-derived locator values, but still retains structural metadata such as column names and inferred types.

## Redacted Numeric Summaries

When `--redact-samples` is enabled, the profiler suppresses numeric summaries for columns that appear to contain long identifier-like values such as account numbers, card numbers, phone numbers, or other long numeric identifiers. This prevents sensitive numbers from leaking through min/max/mean statistics.
