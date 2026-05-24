# AGENTS.md — Tabular File Understanding

This repository contains a portable agent skill at:

```text
skills/tabular-file-understanding/SKILL.md
```

When the user asks an agent to understand a large CSV, TSV, Excel `.xlsx`, or PDF table file, use that skill before downstream analysis.

Core rules:

1. Use Python only.
2. Do not paste large tables into the model context.
3. Run the Python profiler or write equivalent Python-only profiling code.
4. Produce `table_manifest.json`, `table_profile.json`, `table_digest.md`, `ambiguities.md`, plus `data_locator_spec.json` and `data_locator_guide.md` when using the bundled profiler.
5. Read only the compact digest and ambiguity list into the chat unless the user asks for more.
6. Do not auto-install Python packages without explicit user approval.
7. Do not edit or overwrite the original file.
8. For sensitive files, use `--redact-samples` or `--no-samples`.
9. For macro/SDMX/IMF-BOP-like data, inspect `data_locator_guide.md` before automated extraction.

Default command:

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py --input <file> --out <output_dir>
```

Then use:

```text
<output_dir>/table_digest.md
<output_dir>/ambiguities.md
<output_dir>/data_locator_guide.md
```

Author: yanyintingyou — https://github.com/yanyintingyou
