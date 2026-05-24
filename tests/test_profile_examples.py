#!/usr/bin/env python3
"""Regression tests for tabular-file-understanding examples.

These tests intentionally use only Python's standard library so they can run in
minimal agent environments. They protect the table-shape regressions that this
skill is meant to avoid:

- FRED simple time-series CSV: date is time, series column is value.
- IMF BOP/PIP wide-time CSV: SCALE.ID is an attribute, not a value column.
- EPU wide-measure XLSX: Year/Month are keys, not value columns.
- World Bank report-style XLSX: title/note rows should not become the header.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "tabular-file-understanding" / "scripts" / "profile_tabular_file.py"
EXAMPLES = ROOT / "examples"


def run_profiler(example_name: str, *extra_args: str) -> tuple[dict, dict, dict, Path]:
    """Run the profiler on an example file and return manifest/profile/locator."""
    source = EXAMPLES / example_name
    assert source.exists(), f"missing example: {source}"
    out = Path(tempfile.mkdtemp(prefix=f"tfu-{source.stem}-"))
    cmd = [sys.executable, str(SCRIPT), "--input", str(source), "--out", str(out), *extra_args]
    try:
        subprocess.run(cmd, cwd=str(ROOT), check=True, text=True, capture_output=True)
        manifest = json.loads((out / "table_manifest.json").read_text(encoding="utf-8"))
        profile = json.loads((out / "table_profile.json").read_text(encoding="utf-8"))
        locator = json.loads((out / "data_locator_spec.json").read_text(encoding="utf-8"))
        return manifest, profile, locator, out
    except subprocess.CalledProcessError as exc:
        print(exc.stdout)
        print(exc.stderr, file=sys.stderr)
        raise


def run_profiler_on_path(source: Path, *extra_args: str) -> tuple[dict, dict, dict, Path]:
    """Run the profiler on an arbitrary file path and return manifest/profile/locator."""
    out = Path(tempfile.mkdtemp(prefix=f"tfu-{source.stem}-"))
    cmd = [sys.executable, str(SCRIPT), "--input", str(source), "--out", str(out), *extra_args]
    try:
        subprocess.run(cmd, cwd=str(ROOT), check=True, text=True, capture_output=True)
        manifest = json.loads((out / "table_manifest.json").read_text(encoding="utf-8"))
        profile = json.loads((out / "table_profile.json").read_text(encoding="utf-8"))
        locator = json.loads((out / "data_locator_spec.json").read_text(encoding="utf-8"))
        return manifest, profile, locator, out
    except subprocess.CalledProcessError as exc:
        print(exc.stdout)
        print(exc.stderr, file=sys.stderr)
        raise


def cleanup(out: Path) -> None:
    shutil.rmtree(out, ignore_errors=True)


def observation_key(locator: dict) -> list[str]:
    return locator["observation_locator"]["recommended_key"]


def first_profile(profile: dict) -> dict:
    return profile["profiles"][0]


def test_fred_simple_long_time_series() -> None:
    manifest, profile, locator, out = run_profiler("simple_fred.csv")
    try:
        roles = locator["column_roles"]
        assert locator["value_layout"] == "long_value_column"
        assert roles["time_column"] == "observation_date"
        assert roles["value_column"] == "IRLTLT01JPM156N"
        assert "observation_date" in observation_key(locator)
        assert manifest["file_type"] == "csv"
    finally:
        cleanup(out)


def test_imf_wide_time_columns_do_not_use_scale_as_value() -> None:
    manifest, profile, locator, out = run_profiler("wide_time_imf_mock.csv", "--domain-preset", "imf-bop")
    try:
        roles = locator["column_roles"]
        wide_cols = {item["column"] for item in locator["wide_time_value_columns"]}
        assert locator["value_layout"] == "wide_time_columns"
        assert roles["scale_column"] == "SCALE.ID"
        assert roles["value_column"] is None
        assert "SCALE.ID" not in wide_cols
        assert {"1997", "1998", "1999", "2024-Q1", "2024-Q2"}.issubset(wide_cols)
        assert "reshape_wide_time_columns_to_long" in locator["required_preprocessing"]
        assert "<time_period_column>" in observation_key(locator)
    finally:
        cleanup(out)


def test_epu_year_month_are_keys_not_value_columns() -> None:
    manifest, profile, locator, out = run_profiler("wide_measure_epu_mock.xlsx")
    try:
        obs = locator["observation_locator"]
        value_cols = set(obs.get("value_columns") or [])
        roles = locator["column_roles"]
        # The fixture is intentionally tiny, so generic heuristics may not force
        # wide_measure_columns. The regression we must protect is that Year and
        # Month are not treated as value columns.
        assert roles["time_column"] in {"Year", "Month"}
        assert roles["value_column"] not in {"Year", "Month"}
        assert "Year" in observation_key(locator)
        assert "Year" not in value_cols
        assert "Month" not in value_cols
        columns = {c["name"] for c in first_profile(profile)["columns"]}
        assert {"GEPU_current", "GEPU_ppp", "Australia", "Brazil", "Canada", "China", "US"}.issubset(columns)
    finally:
        cleanup(out)


def test_worldbank_report_style_header_detection() -> None:
    manifest, profile, locator, out = run_profiler("report_style_worldbank_mock.xlsx")
    try:
        tables = manifest["tables"]
        assert tables, "expected at least one table"
        primary = tables[0]
        profile0 = first_profile(profile)
        columns = [c["name"] for c in profile0["columns"]]
        assert {"Code", "Economy", "FY89", "FY90", "FY91", "FY92"}.issubset(set(columns))
        assert "World Bank Historical Classification Mock" not in columns
        structure = profile0["structure_guess"]
        assert structure.get("header_rows")
        assert structure.get("data_start_row_sample") is not None
        assert structure["header_rows"][0] < structure["data_start_row_sample"]
        assert locator["value_layout"] == "wide_time_columns"
    finally:
        cleanup(out)

def test_no_samples_removes_row_and_column_value_samples() -> None:
    manifest, profile, locator, out = run_profiler("simple_fred.csv", "--no-samples")
    try:
        prof = first_profile(profile)
        assert prof["samples"] == {"head_rows": [], "representative_rows": []}
        for col in prof["columns"]:
            assert col.get("examples", []) == []
            assert col.get("top_values_sample", []) == []
        assert locator["sample_values_suppressed"] is True
        assert locator["indicator_index"]["top_values"] == []
        assert locator["entity_index"]["top_values"] == []
        assert manifest["profiling_options"]["no_samples"] is True
    finally:
        cleanup(out)


def test_csv_duplicate_headers_are_made_unique() -> None:
    with tempfile.TemporaryDirectory(prefix="tfu-dup-") as td:
        source = Path(td) / "duplicate_headers.csv"
        source.write_text("id,value,value\n1,10,100\n2,20,200\n", encoding="utf-8")
        manifest, profile, locator, out = run_profiler_on_path(source)
        try:
            names = [c["name"] for c in first_profile(profile)["columns"]]
            assert names == ["id", "value", "value_2"]
        finally:
            cleanup(out)


def test_short_code_header_candidate_is_marked_ambiguous() -> None:
    with tempfile.TemporaryDirectory(prefix="tfu-header-") as td:
        source = Path(td) / "code_matrix.csv"
        source.write_text("US,JP,CN\n1.1,2.2,3.3\n4.4,5.5,6.6\n", encoding="utf-8")
        manifest, profile, locator, out = run_profiler_on_path(source)
        try:
            structure = first_profile(profile)["structure_guess"]
            ambiguities = (out / "ambiguities.md").read_text(encoding="utf-8").lower()
            assert structure["header_confidence"] == "medium"
            assert "first row may be either a header or a data row" in ambiguities
        finally:
            cleanup(out)


def test_invalid_xlsx_reports_not_well_understood() -> None:
    with tempfile.TemporaryDirectory(prefix="tfu-badxlsx-") as td:
        source = Path(td) / "bad.xlsx"
        import zipfile
        with zipfile.ZipFile(source, "w") as zf:
            zf.writestr("not_a_workbook.txt", "hello")
        manifest, profile, locator, out = run_profiler_on_path(source)
        try:
            assert manifest["tables"] == []
            assert manifest["understanding_quality"] == "not well understood"
            assert manifest["profiling_success"] is False
        finally:
            cleanup(out)


def test_compact_policy_preserves_semantic_columns_at_tail() -> None:
    with tempfile.TemporaryDirectory(prefix="tfu-wide-") as td:
        source = Path(td) / "wide_tail_roles.csv"
        filler = [f"c{i}" for i in range(1, 1006)]
        header = filler + ["COUNTRY.ID", "TIME_PERIOD", "OBS_VALUE"]
        row = ["" for _ in filler] + ["US", "2024", "123.4"]
        source.write_text(",".join(header) + "\n" + ",".join(row) + "\n", encoding="utf-8")
        manifest, profile, locator, out = run_profiler_on_path(
            source,
            "--output-policy", "compact",
            "--compact-max-profile-columns", "1000",
        )
        try:
            names = {c["name"] for c in first_profile(profile)["columns"]}
            assert {"COUNTRY.ID", "TIME_PERIOD", "OBS_VALUE"}.issubset(names)
            assert first_profile(profile)["columns_omitted_by_output_policy"] == 8
        finally:
            cleanup(out)


def main() -> int:
    tests = [
        test_fred_simple_long_time_series,
        test_imf_wide_time_columns_do_not_use_scale_as_value,
        test_epu_year_month_are_keys_not_value_columns,
        test_worldbank_report_style_header_detection,
        test_no_samples_removes_row_and_column_value_samples,
        test_csv_duplicate_headers_are_made_unique,
        test_short_code_header_candidate_is_marked_ambiguous,
        test_invalid_xlsx_reports_not_well_understood,
        test_compact_policy_preserves_semantic_columns_at_tail,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - stdlib-only tiny runner
            failed += 1
            print(f"FAIL {test.__name__}: {exc}", file=sys.stderr)
    if failed:
        print(f"{failed} test(s) failed", file=sys.stderr)
        return 1
    print(f"All {len(tests)} regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
