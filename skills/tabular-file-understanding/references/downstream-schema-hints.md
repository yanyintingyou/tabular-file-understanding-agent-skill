# Optional Downstream Schema Hints

This skill intentionally stops at structural understanding. However, some agents benefit from a small hint file that explains how the digest may be reused by downstream workflows.

The reference profiler supports:

```bash
--schema-preset none
--schema-preset generic
--schema-preset rag
--schema-preset sql
```

When a non-`none` preset is selected, the profiler writes:

```text
downstream_schema_hint.json
```

## Presets

### `generic`

Lists the canonical artifacts and states that they are structural-understanding outputs, not validation contracts.

### `rag`

Reminds agents that RAG should index the digest and column profiles, not the full raw table. Numeric aggregation should be handled by SQL/DataFrame tools, not semantic retrieval.

### `sql`

Reminds agents to use normalized column names, inferred types, primary table guesses, and row-grain guesses when building a later SQL ingestion/query workflow. The profiler itself does not create a database.

## Important Boundary

These schema hints do not change the core skill contract. The four canonical outputs remain:

- `table_manifest.json`
- `table_profile.json`
- `table_digest.md`
- `ambiguities.md`
