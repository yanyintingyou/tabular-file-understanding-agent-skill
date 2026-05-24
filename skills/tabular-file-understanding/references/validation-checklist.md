# Validation Checklist

Use this checklist before publishing or after modifying the skill.

## Skill Structure

- [ ] `skills/tabular-file-understanding/SKILL.md` exists.
- [ ] The `name` field is `tabular-file-understanding` and matches the directory name.
- [ ] The description explains both what the skill does and when to use it.
- [ ] Supporting details are in `references/` rather than bloating `SKILL.md`.
- [ ] The Python script is in `scripts/` and is executable where supported.

## Python Script Smoke Tests

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py --check-deps
```

Create and profile a tiny CSV:

```bash
printf 'country,date,flow\nUS,2024-01-01,1.2\nCN,2024-01-02,3.4\n' > /tmp/tfu-smoke.csv
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input /tmp/tfu-smoke.csv \
  --out /tmp/tfu-smoke-profile
ls /tmp/tfu-smoke-profile/table_manifest.json \
   /tmp/tfu-smoke-profile/table_profile.json \
   /tmp/tfu-smoke-profile/table_digest.md \
   /tmp/tfu-smoke-profile/ambiguities.md
```

## Expected Behavior

- [ ] Large raw table contents are not printed to stdout.
- [ ] The command prints only a compact JSON status object.
- [ ] The digest is small enough to load into LLM context.
- [ ] Warnings distinguish sampled estimates from exact counts.
- [ ] PDF outputs are conservative and do not claim full table extraction.
- [ ] Missing optional dependencies do not cause failure.

## Privacy Tests

```bash
printf 'email,phone,value\na@example.com,+1 555 123 4567,42\n' > /tmp/tfu-sensitive.csv
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input /tmp/tfu-sensitive.csv \
  --out /tmp/tfu-sensitive-profile \
  --redact-samples
```

Check that sample/example values are redacted in JSON/Markdown outputs where applicable.


## Adaptive Output Policy Test

```bash
python skills/tabular-file-understanding/scripts/profile_tabular_file.py \
  --input /tmp/tfu-smoke.csv \
  --out /tmp/tfu-compact-profile \
  --output-policy compact
```

Check that `table_manifest.json` contains `output_control.policy = "compact"` and that the digest reports the selected JSON output policy.
