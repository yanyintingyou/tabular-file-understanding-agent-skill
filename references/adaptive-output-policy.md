# Adaptive JSON Output Policy

The profiler writes compact structural artifacts rather than copying the original dataset. However, very large or very wide tables can still make `table_profile.json` grow because column profiles scale with the number of fields.

To control artifact size, the profiler uses an adaptive JSON output policy by default:

```bash
--output-policy auto
```

## Policy Levels

### `full`

Used for small files and normal-width tables.

Behavior:

- keeps row samples;
- keeps up to 5 examples per column;
- keeps up to 5 top values per column;
- keeps detailed profiles for all detected columns.

Default auto conditions:

- file size below `--small-file-mb`, default 10 MB;
- column count below `--medium-column-threshold`, default 200.

### `balanced`

Used for medium files or moderately wide tables.

Behavior:

- keeps row samples;
- reduces examples/top values to 3 each;
- caps retained cell text length more aggressively;
- keeps detailed profiles for all detected columns.

Default auto conditions:

- file size at or above 10 MB, but below 100 MB; or
- column count at or above 200, but below 1000.

### `compact`

Used for large files or wide tables.

Behavior:

- omits row-level samples from `table_profile.json`;
- reduces examples/top values to 2 each;
- caps retained cell text length;
- keeps detailed profiles for at most `--compact-max-profile-columns`, default 1000;
- writes a preview of omitted column names when columns are omitted.

Default auto conditions:

- file size at or above 100 MB, but below 1 GB; or
- column count at or above 1000, but below 5000.

### `very-compact`

Used for very large files or extremely wide tables.

Behavior:

- omits row-level samples;
- keeps only 1 example/top value per retained column;
- caps retained cell text length strongly;
- keeps detailed profiles for at most `--very-compact-max-profile-columns`, default 300;
- writes a preview of omitted column names when columns are omitted.

Default auto conditions:

- file size at or above 1 GB; or
- column count at or above 5000.

## Manual Override

Users can override the policy explicitly:

```bash
--output-policy full
--output-policy balanced
--output-policy compact
--output-policy very-compact
```

Use `--output-policy full` only when complete profiling artifacts are needed and storage/context size is acceptable.

## Metadata

The selected policy is recorded in:

```json
{
  "output_control": {
    "policy": "...",
    "requested_policy": "...",
    "reason": "...",
    "thresholds": {},
    "controls": {},
    "notes": []
  }
}
```

This appears in `table_manifest.json` and is summarized in `table_digest.md`.

## Important Boundary

The adaptive policy only reduces profiling artifacts. It never edits, truncates, or modifies the original input file.
