# CLAUDE.md — Tabular File Understanding

This repository contains an Agent Skills-compatible skill at:

```text
skills/tabular-file-understanding/SKILL.md
```

When a task involves understanding a large CSV, TSV, Excel `.xlsx`, or PDF table file, first follow that skill. Use Python only, generate the four canonical artifacts, and load only `table_digest.md` plus `ambiguities.md` into the conversation unless the user asks for raw samples.

For sensitive files, prefer `--redact-samples` or `--no-samples`.

Author: yanyintingyou — https://github.com/yanyintingyou
