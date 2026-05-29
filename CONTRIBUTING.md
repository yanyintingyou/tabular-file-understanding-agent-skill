# Contributing

Thank you for improving `tabular-file-understanding`.

## Development principles

- Keep the core profiler usable with Python standard library only.
- Do not add mandatory dependencies without a strong reason and documentation update.
- Treat profiler output as structural evidence, not authoritative business meaning.
- Preserve read-only behavior for input files.
- Add regression tests for every bug fix or heuristic improvement.

## Local checks

Run these before opening a pull request:

```bash
python -m py_compile \
  skills/data-science/tabular-file-understanding/scripts/profile_tabular_file.py \
  tests/test_profile_examples.py

python tests/test_profile_examples.py
```

## Test fixtures

Examples under `examples/` should remain synthetic and small. Do not commit private data, licensed datasets, or large real-world files.

When adding a new fixture, document what failure mode it protects against in `tests/test_profile_examples.py`.

## Documentation

If a change affects CLI behavior, privacy behavior, output schema, or supported file types, update:

- `README.md`
- `README.zh-CN.md`
- `skills/data-science/tabular-file-understanding/SKILL.md`
- relevant files under `skills/data-science/tabular-file-understanding/references/`
- `CHANGELOG.md`
