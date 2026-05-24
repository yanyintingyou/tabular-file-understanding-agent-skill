#!/usr/bin/env python3
"""Python-only structural profiler for large tabular files.

Outputs:
  - table_manifest.json
  - table_profile.json
  - table_digest.md
  - ambiguities.md

This script intentionally uses only the Python standard library.
It is a conservative profiler, not a full data-analysis engine.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import math
import re
import sys
import zipfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

VERSION = "1.1.1"
EMPTY_MARKERS = {"", "na", "n/a", "null", "none", "nan", ".", "-", "--"}
DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"),
    re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$"),
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$"),
    re.compile(r"^\d{4}-\d{1,2}$"),
    re.compile(r"^\d{4}Q[1-4]$", re.I),
    re.compile(r"^\d{4}-Q[1-4]$", re.I),
    re.compile(r"^\d{4}-S[12]$", re.I),
    re.compile(r"^\d{4}S[12]$", re.I),
    re.compile(r"^\d{4}$"),
]


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\-\s().]{7,}\d)(?!\d)")
LONG_DIGIT_RE = re.compile(r"(?<!\d)\d{12,}(?!\d)")


def safe_cell(value: Any, max_chars: int = 120, redact: bool = False) -> str:
    """Return a bounded display value for JSON/Markdown samples.

    The profiler should reveal structure, not leak full row-level sensitive data.
    """
    s = "" if value is None else str(value)
    s = s.replace("\x00", "").replace("\r", " ").replace("\n", " ")
    if redact:
        s = EMAIL_RE.sub("[REDACTED_EMAIL]", s)
        s = PHONE_RE.sub("[REDACTED_PHONE]", s)
        s = LONG_DIGIT_RE.sub("[REDACTED_LONG_NUMBER]", s)
    if max_chars and len(s) > max_chars:
        return s[: max_chars - 1] + "…"
    return s


def safe_row(row: List[Any], max_chars: int = 120, redact: bool = False, max_cols: int = 80) -> List[str]:
    row = row[:max_cols]
    return [safe_cell(v, max_chars=max_chars, redact=redact) for v in row]


def strip_column_value_samples(profiles: List[Dict[str, Any]]) -> None:
    """Remove all retained row-level and column-level value samples in-place."""
    for prof in profiles:
        if not isinstance(prof, dict):
            continue
        prof["samples"] = {"head_rows": [], "representative_rows": []}
        for col in prof.get("columns", []) or []:
            if isinstance(col, dict):
                col["examples"] = []
                col["top_values_sample"] = []


def strip_locator_value_samples(locator: Dict[str, Any]) -> None:
    """Remove sample-derived values/counts from the domain locator in-place."""
    locator["sample_values_suppressed"] = True
    locator.setdefault("warnings", []).append("--no-samples suppressed sample-derived locator indexes, frequency samples, key checks, and value summaries.")
    for key in ["indicator_index", "entity_index"]:
        idx = locator.get(key)
        if isinstance(idx, dict):
            idx["unique_count_sample"] = None
            idx["top_values"] = []
            idx["mapping_required"] = False
            idx["sample_values_suppressed"] = True
    tc = locator.get("time_coverage")
    if isinstance(tc, dict):
        for k in ["overall_min_sample", "overall_max_sample", "frequencies_detected_sample", "by_frequency_sample", "mixed_frequency_sample"]:
            if k in tc:
                tc[k] = [] if k.endswith("_sample") and isinstance(tc.get(k), list) else None
        tc["sample_values_suppressed"] = True
    for item in locator.get("wide_time_value_columns", []) or []:
        if isinstance(item, dict):
            for k in ["missing_rate_sample", "non_empty_sample_count", "numeric_summary_sample", "date_summary_sample", "top_values_sample", "examples"]:
                item.pop(k, None)
            item["sample_values_suppressed"] = True
    obs = locator.get("observation_locator")
    if isinstance(obs, dict):
        key_check = obs.get("key_uniqueness_check")
        if isinstance(key_check, dict):
            key_cols = key_check.get("key_columns", [])
            obs["key_uniqueness_check"] = {
                "tested_on_rows": 0,
                "key_columns": key_cols,
                "duplicate_key_count_sample": None,
                "is_unique_in_sample": None,
                "sample_values_suppressed": True,
            }



def suppress_numeric_summary_for_sensitive_values(values: List[str], name: str, redact: bool) -> bool:
    """Avoid leaking long account/card/id-like numbers via numeric summaries."""
    if not redact:
        return False
    n = norm_name(name)
    if re.search(r"account|acct|card|phone|mobile|tel|ssn|tax|passport|license|identity|id|code|number|num", n):
        return True
    for v in values[:100]:
        raw = str(v).strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 12:
            return True
    return False


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def norm_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s\-./\\]+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unnamed"


def is_empty(v: Any) -> bool:
    if v is None:
        return True
    return str(v).strip().lower() in EMPTY_MARKERS


def try_float(v: str) -> Optional[float]:
    s = str(v).strip()
    if is_empty(s):
        return None
    s = s.replace(",", "")
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        x = float(s)
        if math.isfinite(x):
            return x
    except Exception:
        return None
    return None


def looks_date(v: str) -> bool:
    s = str(v).strip()
    if is_empty(s):
        return False
    if any(p.match(s) for p in DATE_PATTERNS):
        return True
    # Excel serial date: plausible but ambiguous; do not treat pure small integers as dates.
    return False


def semantic_guess(name: str, inferred_type: str) -> str:
    n = norm_name(name)
    if re.search(r"(^|_)(id|code|key|ticker|symbol|isin|cusip|sedol|permno|gvkey)($|_)", n):
        return "identifier"
    if re.search(r"date|time|year|month|quarter|period|fomc", n):
        return "time"
    if re.search(r"country|region|sector|industry|category|class|type|name|group", n):
        return "category"
    if re.search(r"pct|percent|percentage|ratio|rate|yield|margin", n) or "%" in name:
        return "percentage"
    if re.search(r"currency|ccy|usd|eur|gbp|cny|jpy|hkd", n):
        return "currency"
    if re.search(r"amount|value|flow|sales|revenue|income|cost|price|aum|asset|liability|volume|qty|quantity|balance", n):
        return "measure"
    if inferred_type in {"integer", "float"}:
        return "measure"
    if inferred_type in {"date"}:
        return "time"
    if inferred_type in {"category"}:
        return "category"
    if inferred_type in {"text"}:
        return "text"
    return "unknown"


def infer_column(values: List[str], name: str, total_rows: int, max_cell_chars: int = 120, redact: bool = False) -> Dict[str, Any]:
    non_empty = [str(v).strip() for v in values if not is_empty(v)]
    missing = max(total_rows - len(non_empty), 0)
    unique = Counter(non_empty)
    examples = []
    for v in non_empty:
        display_v = safe_cell(v, max_chars=max_cell_chars, redact=redact)
        if display_v not in examples:
            examples.append(display_v)
        if len(examples) >= 5:
            break

    numeric_vals = [try_float(v) for v in non_empty]
    numeric_clean = [x for x in numeric_vals if x is not None]
    date_vals = [v for v in non_empty if looks_date(v)]
    lower_vals = {v.lower() for v in non_empty[:100]}
    bool_like = bool(non_empty) and lower_vals.issubset({"true", "false", "yes", "no", "y", "n", "0", "1"})

    if not non_empty:
        typ = "empty"
    elif bool_like:
        typ = "boolean"
    elif len(numeric_clean) / max(len(non_empty), 1) >= 0.9:
        int_like = all(abs(x - int(x)) < 1e-9 for x in numeric_clean[:1000])
        typ = "integer" if int_like else "float"
    elif len(date_vals) / max(len(non_empty), 1) >= 0.75:
        typ = "date"
    elif len(unique) <= max(20, int(0.05 * max(len(non_empty), 1))):
        typ = "category"
    elif sum(len(v) for v in non_empty) / max(len(non_empty), 1) > 40:
        typ = "text"
    else:
        typ = "mixed"

    numeric_summary = {"min": None, "max": None, "mean": None}
    suppress_numeric_summary = suppress_numeric_summary_for_sensitive_values(non_empty, name, redact)
    if numeric_clean and not suppress_numeric_summary:
        numeric_summary = {
            "min": min(numeric_clean),
            "max": max(numeric_clean),
            "mean": sum(numeric_clean) / len(numeric_clean),
        }
    date_summary = {"min": None, "max": None}
    if date_vals:
        date_summary = {"min": min(date_vals), "max": max(date_vals)}

    warnings = []
    if total_rows and missing / total_rows > 0.5:
        warnings.append("High missingness in sampled rows")
    if typ == "mixed":
        warnings.append("Mixed or weakly inferred type")
    if suppress_numeric_summary:
        warnings.append("Numeric summary suppressed because redaction detected potentially sensitive long numeric identifiers")

    return {
        "name": name,
        "normalized_name": norm_name(name),
        "inferred_type": typ,
        "semantic_guess": semantic_guess(name, typ),
        "missing_rate_sample": round(missing / max(total_rows, 1), 6),
        "non_empty_sample_count": len(non_empty),
        "unique_count_sample": len(unique),
        "examples": examples,
        "top_values_sample": [{"value": safe_cell(k, max_chars=max_cell_chars, redact=redact), "count": v} for k, v in unique.most_common(5)],
        "numeric_summary_sample": numeric_summary,
        "date_summary_sample": date_summary,
        "warnings": warnings,
    }


def detect_file_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".csv"}:
        return "csv"
    if ext in {".tsv", ".tab"}:
        return "tsv"
    if ext in {".xlsx", ".xlsm"}:
        return "xlsx"
    if ext == ".pdf":
        return "pdf"
    if ext in {".txt", ".dat"}:
        return "csv"
    return "unknown"


def decode_sample(raw: bytes) -> Tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1-replace"


def detect_dialect(sample_text: str, file_type: str) -> Tuple[csv.Dialect, List[str]]:
    warnings = []
    if file_type == "tsv":
        class TSV(csv.excel):
            delimiter = "\t"
        return TSV, warnings
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=[",", "\t", ";", "|", ":"])
        return dialect, warnings
    except Exception:
        warnings.append("Could not reliably detect CSV dialect; defaulting to comma delimiter")
        return csv.excel, warnings


def looks_short_code_header_candidate(row: List[str]) -> bool:
    """Return True for rows that could be either headers or data labels.

    Examples such as ``US,JP,CN`` are common in matrix-like data where the
    first row may be dimension values rather than authoritative field names.
    Treating such rows as a high-confidence header makes downstream agents too
    certain, so callers should mark the header interpretation as ambiguous.
    """
    vals = [str(x).strip() for x in row if not is_empty(x)]
    if len(vals) < 2:
        return False
    if any(re.search(r"date|time|year|month|quarter|period|value|amount|country|indicator|series|code|id|name", norm_name(v)) for v in vals):
        return False
    code_like = 0
    for v in vals:
        token = re.sub(r"[^A-Za-z0-9]", "", v)
        if 1 <= len(token) <= 4 and token.upper() == token and re.search(r"[A-Z]", token):
            code_like += 1
    return code_like / max(len(vals), 1) >= 0.8


def header_confidence(first_row: List[str], second_row: Optional[List[str]]) -> Tuple[bool, str]:
    if not first_row:
        return False, "low"
    first_nonnum = sum(1 for x in first_row if try_float(x) is None)
    first_nonempty = sum(1 for x in first_row if not is_empty(x))
    if second_row:
        second_num = sum(1 for x in second_row if try_float(x) is not None)
        second_nonempty = sum(1 for x in second_row if not is_empty(x))
    else:
        second_num = 0
        second_nonempty = 0
    if first_nonempty and first_nonnum / first_nonempty >= 0.7 and second_nonempty and second_num / second_nonempty >= 0.3:
        if looks_short_code_header_candidate(first_row):
            return True, "medium"
        return True, "high"
    if first_nonempty and first_nonnum / first_nonempty >= 0.6:
        return True, "medium"
    return False, "low"


def looks_iso3_code(v: Any) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", str(v or "").strip()))


def looks_fiscal_year_token(v: Any) -> bool:
    return bool(re.fullmatch(r"FY\d{2,4}", str(v or "").strip(), re.I))


def looks_year_token(v: Any) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}", str(v or "").strip()))


def is_worldbank_wide_history_header(row: List[str]) -> bool:
    """Detect World-Bank-style report headers where time is spread across columns."""
    if len(row) < 5:
        return False
    label = str(row[1] if len(row) > 1 else "").strip().lower()
    fy_count = sum(1 for x in row[2:] if looks_fiscal_year_token(x))
    year_count = sum(1 for x in row[2:] if looks_year_token(x))
    return ("fiscal" in label and fy_count >= 3) or (label.startswith("year") and year_count >= 3)


def make_unique_headers(header: List[str]) -> List[str]:
    seen = Counter()
    out = []
    for i, raw in enumerate(header):
        name = str(raw or "").strip() or f"column_{i+1}"
        seen[name] += 1
        if seen[name] > 1:
            name = f"{name}_{seen[name]}"
        out.append(name)
    return out


def infer_xlsx_table_layout(rows: List[List[str]], sheet_name: str) -> Tuple[List[str], List[List[str]], bool, str, int, int, List[str]]:
    """Infer a worksheet's header row and data start from sampled XML rows.

    This keeps the skill Python-stdlib-only but fixes official report-style
    workbooks where row 1 is a title/metadata line rather than the real header.
    """
    notes: List[str] = []
    if not rows:
        return [], [], False, "low", -1, 0, notes
    max_scan = min(len(rows), 25)
    best_idx = 0
    best_score = -1.0
    best_kind = "ordinary"
    for i in range(max_scan):
        row = rows[i]
        nonempty = [str(x).strip() for x in row if not is_empty(x)]
        if not nonempty:
            continue
        lower_join = " ".join(x.lower() for x in nonempty)
        first_nonnum = sum(1 for x in row if try_float(x) is None)
        first_nonempty = sum(1 for x in row if not is_empty(x))
        next_row = rows[i + 1] if i + 1 < len(rows) else []
        has_header, hconf = header_confidence(row, next_row)
        score = 0.0
        if has_header:
            score += 5.0 if hconf == "high" else 3.0
        if i == 0 and first_nonempty and first_nonnum / first_nonempty >= 0.6:
            score += 5.0
        score += min(len(nonempty), 12) * 0.25
        if any(x.lower() in {"country", "economy", "code", "region", "income group", "lending category", "fiscal year", "from", "to"} for x in nonempty):
            score += 4.0
        if is_worldbank_wide_history_header(row):
            score += 7.0
        if i == 0:
            score += 0.5
        if len(nonempty) <= 2 and re.search(r"world bank|guidelines|notes|presented in|methodology|document|date", lower_join):
            score -= 3.0
        if i > 0 and len(nonempty) == 2 and best_score >= 5.0:
            score -= 2.0
        if score > best_score:
            best_score = score
            best_idx = i
            best_kind = "wide_history" if is_worldbank_wide_history_header(row) else "ordinary"

    header_row = rows[best_idx]
    data_start = best_idx + 1
    if best_kind == "wide_history":
        for j in range(best_idx + 1, len(rows)):
            if len(rows[j]) >= 2 and looks_iso3_code(rows[j][0]) and not is_empty(rows[j][1]):
                data_start = j
                break
        header = list(header_row)
        if len(header) >= 1 and is_empty(header[0]):
            header[0] = "Code"
        if len(header) >= 2:
            header[1] = "Economy"
        notes.append("Detected report-style wide country history table; skipped title/threshold rows before the first ISO3 country-code row.")
        hconf = "high"
        has_header = True
    else:
        has_header, hconf = header_confidence(header_row, rows[best_idx + 1] if best_idx + 1 < len(rows) else None)
        if not has_header and best_score >= 4.0:
            has_header, hconf = True, "medium"
        header = list(header_row) if has_header else [f"column_{i+1}" for i in range(max([len(r) for r in rows], default=0))]

    max_cols = max([len(r) for r in rows], default=len(header))
    if len(header) < max_cols:
        header += [f"column_{i+1}" for i in range(len(header), max_cols)]
    header = make_unique_headers(header[:max_cols])
    data_rows = rows[data_start:] if has_header else rows
    if best_idx > 0:
        notes.append(f"Header row inferred at sampled row {best_idx + 1}, not worksheet row 1; earlier rows look like titles/notes/report metadata.")
    return header, data_rows, has_header, hconf, best_idx, data_start, notes


def profile_csv(path: Path, args) -> Tuple[Dict[str, Any], Dict[str, Any], List[str], List[str]]:
    warnings = []
    ambiguities = []
    with path.open("rb") as f:
        raw = f.read(args.sample_bytes)
    sample_text, encoding = decode_sample(raw)
    dialect, dw = detect_dialect(sample_text, detect_file_type(path))
    warnings.extend(dw)

    rows = []
    widths = Counter()
    scanned = 0
    limit = None if args.full_scan else args.scan_limit_rows
    with path.open("r", encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f, dialect)
        for row in reader:
            scanned += 1
            widths[len(row)] += 1
            if len(rows) < args.sample_rows:
                rows.append(row)
            if limit and scanned >= limit:
                break

    if not rows:
        warnings.append("No rows could be read from the delimited file")
        header = []
        data_rows = []
        has_header = False
        hconf = "low"
    else:
        has_header, hconf = header_confidence(rows[0], rows[1] if len(rows) > 1 else None)
        if has_header:
            raw_header = [c.strip() or f"column_{i+1}" for i, c in enumerate(rows[0])]
            header = make_unique_headers(raw_header)
            data_rows = rows[1:]
            if hconf == "medium" and looks_short_code_header_candidate(rows[0]):
                ambiguities.append("The first row may be either a header or a data row with short code-like values; confirm whether it should be treated as column names.")
            if header != raw_header:
                warnings.append("Duplicate or blank CSV header names were made unique for stable downstream JSON/profile handling.")
        else:
            maxw = widths.most_common(1)[0][0] if widths else len(rows[0])
            header = [f"column_{i+1}" for i in range(maxw)]
            data_rows = rows
            ambiguities.append("Header row could not be identified with high confidence; generic column names were assigned.")

    max_cols = max([len(r) for r in rows], default=len(header))
    if len(header) < max_cols:
        header += [f"column_{i+1}" for i in range(len(header), max_cols)]
    elif len(header) > max_cols:
        max_cols = len(header)

    col_values = [[] for _ in range(max_cols)]
    for r in data_rows:
        for i in range(max_cols):
            col_values[i].append(r[i] if i < len(r) else "")

    columns = []
    for i in range(max_cols):
        cp = infer_column(col_values[i], header[i] if i < len(header) else f"column_{i+1}", len(data_rows), args.max_cell_chars, args.redact_samples)
        cp["index"] = i
        columns.append(cp)

    if len(widths) > 1:
        warnings.append(f"Rows have inconsistent column counts in scanned rows: {dict(widths.most_common(5))}")
        ambiguities.append("The delimited file has inconsistent row widths; table boundaries or quoting may need confirmation.")
    if not args.full_scan and scanned >= args.scan_limit_rows:
        warnings.append(f"CSV profiling used a bounded scan of {scanned} rows; row count and statistics may be estimates.")
        ambiguities.append("CSV statistics are sample/bounded-scan based, not guaranteed complete. Use --full-scan for exact row count if needed.")
    if args.full_scan and scanned > len(rows):
        warnings.append(f"CSV row count and row-width checks scanned the full file ({scanned} rows), but column profiles are based on the first {len(data_rows)} data rows retained by --sample-rows.")

    shape_type = guess_shape_type(columns)
    grain = guess_grain(columns)
    table_id = "csv:table:0"
    table = {
        "table_id": table_id,
        "kind": "csv_table",
        "name": path.name,
        "location": "file",
        "rows_estimate": max(scanned - (1 if has_header else 0), 0),
        "columns_estimate": max_cols,
        "rows_exact": bool(args.full_scan or (limit and scanned < limit)),
        "columns_exact": False,
        "confidence": "high" if hconf in {"high", "medium"} else "medium",
        "warnings": warnings[:],
        "csv": {
            "encoding_guess": encoding,
            "delimiter": getattr(dialect, "delimiter", ","),
            "quotechar": getattr(dialect, "quotechar", '"'),
            "header_detected": has_header,
            "header_confidence": hconf,
            "scanned_rows": scanned,
            "row_widths_seen": dict(widths.most_common(10)),
        },
    }
    profile = {
        "table_id": table_id,
        "shape": {
            "rows_estimate": table["rows_estimate"],
            "columns_estimate": max_cols,
            "scanned_rows": scanned,
            "sampled": not bool(args.full_scan),
        },
        "structure_guess": {
            "shape_type": shape_type,
            "grain_guess": grain,
            "header_confidence": hconf,
            "header_rows": [1] if has_header else [],
        },
        "columns": columns,
        "samples": {
            "head_rows": [safe_row(r, args.max_cell_chars, args.redact_samples) for r in rows[: min(len(rows), 5)]],
            "representative_rows": [safe_row(r, args.max_cell_chars, args.redact_samples) for r in data_rows[: min(len(data_rows), 5)]],
        },
        "warnings": warnings[:],
    }
    return table, profile, warnings, ambiguities


def col_letters_to_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref.upper())
    if not letters:
        return 0
    n = 0
    for ch in letters.group(0):
        n = n * 26 + (ord(ch) - ord('A') + 1)
    return n - 1


def parse_xlsx_shared_strings(z: zipfile.ZipFile, max_strings: int = 200000) -> List[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    out = []
    try:
        for event, elem in ET.iterparse(z.open("xl/sharedStrings.xml"), events=("end",)):
            if elem.tag.endswith("}si") or elem.tag == "si":
                texts = []
                for t in elem.iter():
                    if t.tag.endswith("}t") or t.tag == "t":
                        texts.append(t.text or "")
                out.append("".join(texts))
                elem.clear()
                if len(out) >= max_strings:
                    break
    except Exception:
        return out
    return out


def xlsx_sheet_map(z: zipfile.ZipFile) -> List[Tuple[str, str]]:
    # Returns [(sheet_name, worksheet_path)] best effort.
    names = []
    try:
        root = ET.parse(z.open("xl/workbook.xml")).getroot()
        ns_rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        for sheet in root.iter():
            if sheet.tag.endswith("}sheet") or sheet.tag == "sheet":
                names.append((sheet.attrib.get("name", f"Sheet{len(names)+1}"), sheet.attrib.get(ns_rel, "")))
    except Exception:
        pass
    rels = {}
    try:
        root = ET.parse(z.open("xl/_rels/workbook.xml.rels")).getroot()
        for rel in root:
            rid = rel.attrib.get("Id")
            target = rel.attrib.get("Target", "")
            if rid and "worksheet" in target:
                rels[rid] = str(Path("xl") / target).replace("\\", "/") if not target.startswith("xl/") else target
    except Exception:
        pass
    result = []
    for idx, (name, rid) in enumerate(names):
        path = rels.get(rid, f"xl/worksheets/sheet{idx+1}.xml")
        if path in z.namelist():
            result.append((name, path))
    if not result:
        sheets = sorted([n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])
        result = [(f"Sheet{i+1}", p) for i, p in enumerate(sheets)]
    return result


def parse_sheet_sample(z: zipfile.ZipFile, sheet_path: str, shared: List[str], max_rows: int) -> Tuple[List[List[str]], Dict[str, Any]]:
    rows = []
    info = {"dimension": None, "merged_cells_count": 0, "formulas_in_sample": 0}
    try:
        for event, elem in ET.iterparse(z.open(sheet_path), events=("end",)):
            tag = elem.tag.split('}')[-1]
            if tag == "dimension":
                info["dimension"] = elem.attrib.get("ref")
            elif tag == "mergeCell":
                info["merged_cells_count"] += 1
            elif tag == "row":
                row_cells = {}
                for c in list(elem):
                    ctag = c.tag.split('}')[-1]
                    if ctag != "c":
                        continue
                    ref = c.attrib.get("r", "")
                    idx = col_letters_to_index(ref)
                    typ = c.attrib.get("t")
                    val = ""
                    for child in list(c):
                        childtag = child.tag.split('}')[-1]
                        if childtag == "f":
                            info["formulas_in_sample"] += 1
                        if childtag == "v":
                            val = child.text or ""
                        if childtag == "is":
                            texts = []
                            for t in child.iter():
                                if t.tag.split('}')[-1] == "t":
                                    texts.append(t.text or "")
                            val = "".join(texts)
                    if typ == "s":
                        try:
                            val = shared[int(val)]
                        except Exception:
                            pass
                    row_cells[idx] = val
                if row_cells:
                    width = max(row_cells) + 1
                    rows.append([row_cells.get(i, "") for i in range(width)])
                    if len(rows) >= max_rows:
                        break
                elem.clear()
    except Exception as e:
        info["parse_error"] = str(e)
    return rows, info


def dimension_to_shape(dim: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    if not dim:
        return None, None
    try:
        if ":" in dim:
            start, end = dim.split(":", 1)
        else:
            start = end = dim
        end_col = col_letters_to_index(end)
        end_row_m = re.search(r"\d+", end)
        rows = int(end_row_m.group(0)) if end_row_m else None
        cols = end_col + 1
        return rows, cols
    except Exception:
        return None, None


def profile_xlsx(path: Path, args) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], List[str]]:
    warnings = []
    ambiguities = []
    tables = []
    profiles = []
    try:
        with zipfile.ZipFile(path) as z:
            shared = parse_xlsx_shared_strings(z)
            sheets = xlsx_sheet_map(z)
            if not sheets:
                warnings.append("No worksheet XML files found in workbook")
                ambiguities.append("Workbook structure could not be inspected as a normal .xlsx file.")
            for si, (sheet_name, sheet_path) in enumerate(sheets[: args.max_sheets]):
                rows, sinfo = parse_sheet_sample(z, sheet_path, shared, args.sample_rows)
                header, data_rows, has_header, hconf, header_idx, data_start_idx, layout_notes = infer_xlsx_table_layout(rows, sheet_name)
                if not has_header and rows:
                    ambiguities.append(f"Header row for sheet '{sheet_name}' could not be identified with high confidence.")
                max_cols = max([len(r) for r in rows], default=len(header))
                if len(header) < max_cols:
                    header += [f"column_{i+1}" for i in range(len(header), max_cols)]
                header = make_unique_headers(header[:max_cols])
                col_values = [[] for _ in range(max_cols)]
                for r in data_rows:
                    for i in range(max_cols):
                        col_values[i].append(r[i] if i < len(r) else "")
                columns = []
                for i in range(max_cols):
                    cp = infer_column(col_values[i], header[i] if i < len(header) else f"column_{i+1}", len(data_rows), args.max_cell_chars, args.redact_samples)
                    cp["index"] = i
                    columns.append(cp)
                dim_rows, dim_cols = dimension_to_shape(sinfo.get("dimension"))
                sheet_warnings = []
                sheet_warnings.extend(layout_notes)
                if sinfo.get("merged_cells_count", 0):
                    sheet_warnings.append(f"Detected {sinfo.get('merged_cells_count')} merged-cell declarations; report-style or multi-level headers may exist.")
                if sinfo.get("formulas_in_sample", 0):
                    sheet_warnings.append(f"Detected {sinfo.get('formulas_in_sample')} formulas in sampled rows; formulas were not executed.")
                if sinfo.get("parse_error"):
                    sheet_warnings.append("Worksheet XML parse error: " + sinfo["parse_error"])
                table_id = f"xlsx:sheet:{si}"
                tables.append({
                    "table_id": table_id,
                    "kind": "excel_sheet",
                    "name": sheet_name,
                    "location": sheet_path,
                    "rows_estimate": dim_rows if dim_rows is not None else len(rows),
                    "columns_estimate": dim_cols if dim_cols is not None else max_cols,
                    "rows_exact": dim_rows is not None,
                    "columns_exact": dim_cols is not None,
                    "confidence": "medium" if rows else "low",
                    "warnings": sheet_warnings,
                    "excel": {
                        "dimension_ref": sinfo.get("dimension"),
                        "sampled_rows": len(rows),
                        "merged_cells_count": sinfo.get("merged_cells_count", 0),
                        "formulas_in_sample": sinfo.get("formulas_in_sample", 0),
                    },
                })
                profiles.append({
                    "table_id": table_id,
                    "shape": {
                        "rows_estimate": dim_rows if dim_rows is not None else len(rows),
                        "columns_estimate": dim_cols if dim_cols is not None else max_cols,
                        "scanned_rows": len(rows),
                        "sampled": True,
                    },
                    "structure_guess": {
                        "shape_type": guess_shape_type(columns),
                        "grain_guess": guess_grain(columns),
                        "header_confidence": hconf,
                        "header_rows": [header_idx + 1] if has_header and header_idx >= 0 else [],
                        "data_start_row_sample": data_start_idx + 1 if has_header else None,
                    },
                    "columns": columns,
                    "samples": {
                        "head_rows": rows[: min(len(rows), 5)],
                        "representative_rows": data_rows[: min(len(data_rows), 5)],
                    },
                    "warnings": sheet_warnings,
                })
            if len(sheets) > args.max_sheets:
                warnings.append(f"Workbook has {len(sheets)} sheets; only first {args.max_sheets} were sampled.")
                ambiguities.append("Not all workbook sheets were profiled due to max-sheets limit.")
    except zipfile.BadZipFile:
        warnings.append("File is not a valid .xlsx ZIP container")
        ambiguities.append("Excel workbook could not be opened as .xlsx; it may be encrypted, corrupt, or an older .xls file.")
    return tables, profiles, warnings, ambiguities


def profile_pdf(path: Path, args) -> Tuple[Dict[str, Any], Dict[str, Any], List[str], List[str]]:
    warnings = ["PDF table extraction is not available in the standard-library profiler"]
    ambiguities = ["Only PDF file-level metadata was inspected. Table structure cannot be considered understood without a PDF extraction/OCR backend or user-provided table export."]
    raw = path.read_bytes()[: min(args.sample_bytes, path.stat().st_size)]
    header = raw[:20].decode("latin-1", errors="replace")
    # Crude page signal; not authoritative.
    page_markers = raw.count(b"/Type /Page")
    table_id = "pdf:document:0"
    table = {
        "table_id": table_id,
        "kind": "pdf_document",
        "name": path.name,
        "location": "file",
        "rows_estimate": None,
        "columns_estimate": None,
        "rows_exact": False,
        "columns_exact": False,
        "confidence": "low",
        "warnings": warnings[:],
        "pdf": {"header": header, "page_markers_in_sample": page_markers},
    }
    profile = {
        "table_id": table_id,
        "shape": {"rows_estimate": None, "columns_estimate": None, "scanned_rows": 0, "sampled": True},
        "structure_guess": {"shape_type": "unknown", "grain_guess": None, "header_confidence": "low", "header_rows": []},
        "columns": [],
        "samples": {"head_rows": [], "representative_rows": []},
        "warnings": warnings[:],
    }
    return table, profile, warnings, ambiguities


def guess_shape_type(columns: List[Dict[str, Any]]) -> str:
    if not columns:
        return "unknown"
    n = len(columns)
    names = [c.get("name", "") for c in columns]
    norm = [norm_name(x) for x in names]
    year_cols = sum(1 for x in norm if re.fullmatch(r"(19|20)\d{2}", x))
    fiscal_year_cols = sum(1 for x in names if looks_fiscal_year_token(x))
    period_cols = year_cols + fiscal_year_cols
    date_sem = sum(1 for c in columns if c.get("semantic_guess") == "time")
    measure_cols = sum(1 for c in columns if c.get("semantic_guess") in {"measure", "percentage", "currency"})
    cat_cols = sum(1 for c in columns if c.get("semantic_guess") in {"category", "identifier"})
    if n > 30 and period_cols == 0 and measure_cols / max(n, 1) > 0.6:
        return "wide_measure_columns"
    if n >= 12 and period_cols >= max(3, n // 3):
        return "wide_time_series_table"
    if len(detect_wide_time_value_columns(columns)) >= 3:
        return "wide_time_series_table"
    if any(canonical_col_name(c.get("name")) == "FISCAL_YEAR" for c in columns) and measure_cols >= 1 and cat_cols >= 1:
        return "long_table"
    if date_sem >= 1 and measure_cols >= 1 and cat_cols >= 1:
        return "long_table"
    return "unknown"


def guess_grain(columns: List[Dict[str, Any]]) -> Optional[str]:
    sem = defaultdict(list)
    for c in columns:
        sem[c.get("semantic_guess", "unknown")].append(c.get("name"))
    parts = []
    id_names = [str(x) for x in sem.get("identifier", [])]
    for preferred in ["COUNTRY.ID", "INDICATOR.ID", "SERIES_CODE", "Code", "WB_Country_Code", "WB_Group_Code"]:
        if preferred in id_names:
            parts.append(preferred)
            break
    if "WB_Country_Code" in id_names and "WB_Group_Code" in id_names:
        parts = ["WB_Group_Code", "WB_Country_Code"]
    if not parts and id_names:
        parts.append(id_names[0])
    wide_cols = detect_wide_time_value_columns([{"name": x} for x in id_names + [str(x) for x in sem.get("time", [])] + [str(x) for x in sem.get("measure", [])]])
    if sem.get("time") and not wide_cols:
        time_names = [str(x) for x in sem.get("time", [])]
        non_metadata = [x for x in time_names if canonical_col_name(x) not in METADATA_TIME_COLUMNS]
        if non_metadata:
            parts.append(non_metadata[0])
    if sem.get("category"):
        cat_names = [str(x) for x in sem.get("category", [])]
        for preferred in ["FREQUENCY.ID", "COUNTRY", "INDICATOR", "Economy", "Region", "Income group"]:
            if preferred in cat_names and preferred not in parts:
                parts.append(preferred)
                break
        if len(parts) < 2 and cat_names:
            parts.append(cat_names[0])
    if len(parts) >= 2:
        return "one row may represent a " + "-".join(parts) + " observation"
    return None




def estimate_profile_columns(profiles: List[Dict[str, Any]]) -> int:
    return max((len(p.get("columns", [])) for p in profiles if isinstance(p, dict)), default=0)


def choose_output_policy(args, file_size_bytes: int, profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Choose how much detail to keep in JSON artifacts.

    The policy controls artifact size only. It does not change the original file.
    """
    max_cols = estimate_profile_columns(profiles)
    file_mb = file_size_bytes / (1024 * 1024)
    requested = args.output_policy

    def make(level: str, reason: str, max_examples: int, max_top_values: int, keep_row_samples: bool, max_profile_columns: Optional[int], max_cell_chars_cap: Optional[int]) -> Dict[str, Any]:
        return {
            "policy": level,
            "requested_policy": requested,
            "reason": reason,
            "file_size_mb": round(file_mb, 3),
            "max_columns_seen": max_cols,
            "thresholds": {
                "small_file_mb": args.small_file_mb,
                "large_file_mb": args.large_file_mb,
                "huge_file_mb": args.huge_file_mb,
                "medium_column_threshold": args.medium_column_threshold,
                "large_column_threshold": args.large_column_threshold,
                "huge_column_threshold": args.huge_column_threshold,
            },
            "controls": {
                "max_examples_per_column": max_examples,
                "max_top_values_per_column": max_top_values,
                "keep_row_samples": keep_row_samples,
                "max_profile_columns": max_profile_columns,
                "max_cell_chars_cap": max_cell_chars_cap,
            },
            "notes": [],
        }

    if requested != "auto":
        if requested == "full":
            return make("full", "User requested full output detail.", 5, 5, True, None, None)
        if requested == "balanced":
            return make("balanced", "User requested balanced output detail.", 3, 3, True, None, 100)
        if requested == "compact":
            return make("compact", "User requested compact output detail.", 2, 2, False, args.compact_max_profile_columns, 80)
        if requested == "very-compact":
            return make("very-compact", "User requested very compact output detail.", 1, 1, False, args.very_compact_max_profile_columns, 60)

    if file_mb >= args.huge_file_mb or max_cols >= args.huge_column_threshold:
        return make("very-compact", "Auto policy selected very-compact because the file or table appears very large/wide.", 1, 1, False, args.very_compact_max_profile_columns, 60)
    if file_mb >= args.large_file_mb or max_cols >= args.large_column_threshold:
        return make("compact", "Auto policy selected compact because the file or table appears large/wide.", 2, 2, False, args.compact_max_profile_columns, 80)
    if file_mb >= args.small_file_mb or max_cols >= args.medium_column_threshold:
        return make("balanced", "Auto policy selected balanced because the file or table is above the small-file threshold.", 3, 3, True, None, 100)
    return make("full", "Auto policy selected full because the file/table is below size and width thresholds.", 5, 5, True, None, None)


def column_priority_for_output(col: Dict[str, Any], roles: Optional[Dict[str, Any]] = None) -> int:
    """Higher priority columns survive compact output-policy truncation."""
    name = col.get("name")
    canon = canonical_col_name(name)
    roles = roles or {}
    role_names = {canonical_col_name(v) for v in roles.values() if isinstance(v, str) and v}
    if canon in role_names:
        return 1000
    if is_time_period_column_name(str(name)):
        return 900
    if canon in {"COUNTRY_ID", "REF_AREA", "INDICATOR_ID", "FREQ", "FREQUENCY_ID", "TIME_PERIOD", "OBS_VALUE", "UNIT_MEASURE", "UNIT_ID", "SCALE_ID", "UNIT_MULT", "OBS_STATUS"}:
        return 850
    sem = col.get("semantic_guess")
    if sem in {"time", "identifier"}:
        return 700
    if sem in {"measure", "percentage", "currency"}:
        return 600
    if sem == "category":
        return 500
    return 0


def select_columns_for_output_policy(cols: List[Dict[str, Any]], max_profile_columns: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if len(cols) <= max_profile_columns:
        return cols, []
    roles = infer_macro_roles(cols)
    indexed = list(enumerate(cols))
    selected_idx = set()

    # Keep highest-priority semantic/domain columns regardless of where they occur.
    for idx, col in sorted(indexed, key=lambda item: (-column_priority_for_output(item[1], roles), item[0])):
        if column_priority_for_output(col, roles) <= 0:
            break
        selected_idx.add(idx)
        if len(selected_idx) >= max_profile_columns:
            break

    # Preserve edge period columns so wide-time tables keep visible coverage hints.
    period_idx = [idx for idx, col in indexed if is_time_period_column_name(str(col.get("name", "")))]
    for idx in period_idx[:10] + period_idx[-10:]:
        if len(selected_idx) >= max_profile_columns:
            break
        selected_idx.add(idx)

    # Fill remaining slots in original order for stable, readable artifacts.
    for idx, _col in indexed:
        if len(selected_idx) >= max_profile_columns:
            break
        selected_idx.add(idx)

    selected = [col for idx, col in indexed if idx in selected_idx]
    omitted = [col for idx, col in indexed if idx not in selected_idx]
    return selected, omitted


def apply_output_policy(profiles: List[Dict[str, Any]], policy: Dict[str, Any], redact: bool = False) -> List[str]:
    """Reduce JSON artifact size according to the selected output policy."""
    warnings: List[str] = []
    controls = policy.get("controls", {})
    max_examples = controls.get("max_examples_per_column", 5)
    max_top = controls.get("max_top_values_per_column", 5)
    keep_samples = controls.get("keep_row_samples", True)
    max_profile_columns = controls.get("max_profile_columns")
    max_cell_chars_cap = controls.get("max_cell_chars_cap")
    level = policy.get("policy", "full")

    for prof in profiles:
        if not isinstance(prof, dict):
            continue
        cols = prof.get("columns", [])
        original_cols = len(cols)
        if max_profile_columns is not None and original_cols > max_profile_columns:
            selected, omitted = select_columns_for_output_policy(cols, max_profile_columns)
            prof["columns"] = selected
            prof["columns_omitted_by_output_policy"] = original_cols - len(selected)
            prof["output_policy_original_column_count"] = original_cols
            prof["omitted_column_names_preview"] = [c.get("name") for c in omitted[:50]]
            warnings.append(f"Output policy '{level}' retained detailed profiles for {len(selected)} of {original_cols} columns, prioritizing inferred role/time/value columns; omitted column names preview is stored in table_profile.json.")
            cols = prof["columns"]
        else:
            prof["columns_omitted_by_output_policy"] = 0
            prof["output_policy_original_column_count"] = original_cols
            prof.setdefault("omitted_column_names_preview", [])

        for col in cols:
            if "examples" in col:
                col["examples"] = [safe_cell(v, max_chars=max_cell_chars_cap or 10_000, redact=redact) for v in col.get("examples", [])[:max_examples]]
            if "top_values_sample" in col:
                new_top = []
                for item in col.get("top_values_sample", [])[:max_top]:
                    item = dict(item)
                    if "value" in item:
                        item["value"] = safe_cell(item["value"], max_chars=max_cell_chars_cap or 10_000, redact=redact)
                    new_top.append(item)
                col["top_values_sample"] = new_top

        if not keep_samples and "samples" in prof:
            prof["samples"] = {"head_rows": [], "representative_rows": []}
            warnings.append(f"Output policy '{level}' omitted row-level samples from table_profile.json to control artifact size.")
        elif max_cell_chars_cap and "samples" in prof:
            samples = prof.get("samples") or {}
            prof["samples"] = {
                "head_rows": [[safe_cell(v, max_chars=max_cell_chars_cap, redact=redact) for v in row] for row in samples.get("head_rows", [])],
                "representative_rows": [[safe_cell(v, max_chars=max_cell_chars_cap, redact=redact) for v in row] for row in samples.get("representative_rows", [])],
            }

        prof.setdefault("warnings", [])
        if level != "full":
            prof["warnings"].append(f"JSON output detail was reduced by adaptive output policy: {level}.")

    if level != "full":
        warnings.append(f"Adaptive JSON output policy is '{level}'. Some examples, top values, row samples, or detailed column profiles may be reduced to control storage and context size.")
    return sorted(set(warnings))



TIME_PERIOD_COLUMN_RE = re.compile(r"^(?:19|20)\d{2}(?:$|[-_]?(?:Q[1-4]|S[12]|M(?:0?[1-9]|1[0-2])))$", re.I)
FISCAL_YEAR_COLUMN_RE = re.compile(r"^FY\d{2,4}$", re.I)
METADATA_TIME_COLUMNS = {
    "PUBLICATION_DATE", "UPDATE_DATE", "BPM6_BASIS_START_DATE", "FILING_DATE",
    "CREATED_AT", "UPDATED_AT", "LAST_UPDATE", "LAST_UPDATED"
}


def is_time_period_column_name(name: str) -> bool:
    raw = str(name).strip()
    canon = canonical_col_name(name)
    return (
        bool(TIME_PERIOD_COLUMN_RE.match(canon.replace("_", "-")))
        or bool(TIME_PERIOD_COLUMN_RE.match(raw))
        or bool(FISCAL_YEAR_COLUMN_RE.match(raw))
    )


def normalize_time_period_column(name: str) -> str:
    s = str(name).strip().upper().replace("_", "-")
    fy = re.match(r"^FY(\d{2}|\d{4})$", s)
    if fy:
        return "FY" + fy.group(1)
    m = re.match(r"^((?:19|20)\d{2})(?:-?([QSM].*))?$", s)
    if not m:
        return s
    year, suffix = m.group(1), m.group(2)
    if not suffix:
        return year
    suffix = suffix.replace("M", "M")
    return f"{year}-{suffix}"


def find_column_by_alias(columns: List[Dict[str, Any]], aliases: List[str], prefer_id: bool = False, avoid_metadata_time: bool = False) -> Optional[str]:
    candidates = []
    alias_set = {canonical_col_name(a) for a in aliases}
    for c in columns:
        name = c.get("name")
        canon = canonical_col_name(name)
        if canon in alias_set:
            if avoid_metadata_time and canon in METADATA_TIME_COLUMNS:
                continue
            candidates.append(str(name))
    if not candidates:
        return None
    if prefer_id:
        for cand in candidates:
            cc = canonical_col_name(cand)
            if cc.endswith("_ID") or cc in {"REF_AREA", "FREQ", "UNIT_MEASURE"}:
                return cand
    return candidates[0]


def detect_wide_time_value_columns(columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for c in columns:
        name = c.get("name", "")
        if is_time_period_column_name(str(name)):
            out.append({
                "column": str(name),
                "time_period": normalize_time_period_column(str(name)),
                "inferred_type": c.get("inferred_type"),
                "missing_rate_sample": c.get("missing_rate_sample"),
                "non_empty_sample_count": c.get("non_empty_sample_count"),
                "numeric_summary_sample": c.get("numeric_summary_sample"),
            })
    return out


MACRO_ROLE_ALIASES = {
    "entity_column": ["REF_AREA", "REPORTING_AREA", "COUNTRY.ID", "COUNTRY_ID", "COUNTRY", "COUNTRY_CODE", "ECONOMY.ID", "ECONOMY_CODE", "ECONOMY", "LOCATION", "GEO", "AREA", "CODE"],
    "indicator_column": ["INDICATOR.ID", "INDICATOR_ID", "BOP_ITEM", "BOP_ITEM.ID", "SERIES_CODE", "INDICATOR", "CONCEPT", "MEASURE", "ITEM", "VARIABLE", "SUBJECT", "TOPIC"],
    "counterpart_column": ["COUNTERPART_COUNTRY.ID", "COUNTERPART_COUNTRY_ID", "COUNTERPART_AREA", "COUNTERPART", "COUNTERPARTY", "PARTNER", "PARTNER_AREA", "CP_AREA"],
    "frequency_column": ["FREQUENCY.ID", "FREQUENCY_ID", "FREQ", "FREQUENCY"],
    "time_column": ["TIME_PERIOD", "OBS_TIME", "TIME", "PERIOD", "DATE", "YEAR", "FISCAL_YEAR", "FISCAL YEAR"],
    "value_column": ["OBS_VALUE", "VALUE", "OBS", "AMOUNT", "DATA_VALUE"],
    "unit_column": ["UNIT.ID", "UNIT_ID", "UNIT_MEASURE", "UNIT", "CURRENCY", "UNIT_MULT", "UNIT_MULTIPLIER"],
    "scale_column": ["SCALE.ID", "SCALE_ID", "SCALE", "UNIT_MULT", "UNIT_MULTIPLIER"],
    "status_column": ["OBS_STATUS", "STATUS", "OBS_CONF", "CONF_STATUS", "OBSERVATION_STATUS"],
}


def canonical_col_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(name or "").upper()).strip("_")


def infer_macro_roles(columns: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    roles: Dict[str, Optional[str]] = {k: None for k in MACRO_ROLE_ALIASES}
    wide_time_cols = detect_wide_time_value_columns(columns)
    wide_layout = len(wide_time_cols) >= 3

    # Prefer stable code/ID columns over human-readable label columns for automation.
    roles["entity_column"] = find_column_by_alias(columns, MACRO_ROLE_ALIASES["entity_column"], prefer_id=True)
    roles["indicator_column"] = find_column_by_alias(columns, MACRO_ROLE_ALIASES["indicator_column"], prefer_id=True)
    roles["counterpart_column"] = find_column_by_alias(columns, MACRO_ROLE_ALIASES["counterpart_column"], prefer_id=True)
    roles["frequency_column"] = find_column_by_alias(columns, MACRO_ROLE_ALIASES["frequency_column"], prefer_id=True)
    roles["unit_column"] = find_column_by_alias(columns, MACRO_ROLE_ALIASES["unit_column"], prefer_id=True)
    roles["scale_column"] = find_column_by_alias(columns, MACRO_ROLE_ALIASES["scale_column"], prefer_id=True)
    roles["status_column"] = find_column_by_alias(columns, MACRO_ROLE_ALIASES["status_column"], prefer_id=True)

    if wide_layout:
        # IMF web CSV exports often encode observations as wide year/quarter columns.
        # In that layout PUBLICATION_DATE / UPDATE_DATE are metadata, not observation time.
        roles["time_column"] = None
        roles["value_column"] = None
    else:
        roles["time_column"] = find_column_by_alias(columns, MACRO_ROLE_ALIASES["time_column"], prefer_id=False, avoid_metadata_time=True)
        # Do not let a time key such as Year/Month become the value column in wide-measure tables.
        value_aliases = MACRO_ROLE_ALIASES["value_column"]
        time_like_names = {canonical_col_name(c.get("name")) for c in columns if c.get("semantic_guess") == "time"}
        if roles.get("time_column"):
            time_like_names.add(canonical_col_name(roles.get("time_column")))
        value_aliases = [a for a in value_aliases if canonical_col_name(a) not in time_like_names]
        roles["value_column"] = find_column_by_alias(columns, value_aliases, prefer_id=False)

    # Heuristic fallbacks by semantic type/name if exact aliases fail.
    if not roles.get("time_column") and not wide_layout:
        for c in columns:
            if c.get("semantic_guess") == "time" and canonical_col_name(c.get("name")) not in METADATA_TIME_COLUMNS:
                roles["time_column"] = c.get("name"); break
    if not roles.get("entity_column"):
        code_like = [c for c in columns if c.get("semantic_guess") == "identifier" and re.search(r"(^|_)(code|country_code|economy_code)($|_)", norm_name(c.get("name", "")))]
        if code_like:
            roles["entity_column"] = code_like[0].get("name")
    if not roles.get("value_column") and not wide_layout:
        time_like_names = {canonical_col_name(c.get("name")) for c in columns if c.get("semantic_guess") == "time"}
        numeric = [c for c in columns if c.get("inferred_type") in {"integer", "float"} and canonical_col_name(c.get("name")) not in {"SCALE_ID", "DECIMALS_DISPLAYED_ID", canonical_col_name(roles.get("time_column")), *time_like_names}]
        if numeric:
            roles["value_column"] = numeric[0].get("name")
    return roles


def domain_guess_from_roles(path: Path, roles: Dict[str, Optional[str]], columns: List[Dict[str, Any]], preset: str) -> Dict[str, Any]:
    canon = {canonical_col_name(c.get("name")) for c in columns}
    score = sum(1 for k in ["entity_column", "indicator_column", "time_column", "value_column"] if roles.get(k))
    sdmx_score = sum(1 for x in ["REF_AREA", "COUNTRY_ID", "INDICATOR_ID", "INDICATOR", "TIME_PERIOD", "OBS_VALUE", "FREQ", "FREQUENCY", "FREQUENCY_ID"] if x in canon)
    fname = path.name.upper()
    if preset == "generic":
        return {"domain_guess": "generic_table", "confidence": "low", "score": score, "sdmx_score": sdmx_score}
    if preset == "imf-bop":
        return {"domain_guess": "imf_bop_like", "confidence": "high", "score": score, "sdmx_score": sdmx_score}
    if preset == "sdmx":
        return {"domain_guess": "sdmx_macro_timeseries", "confidence": "high", "score": score, "sdmx_score": sdmx_score}
    if preset == "macro-timeseries":
        return {"domain_guess": "macro_timeseries", "confidence": "high", "score": score, "sdmx_score": sdmx_score}
    # auto
    if ("BOP" in fname or "BALANCE_OF_PAYMENTS" in fname) and sdmx_score >= 3:
        return {"domain_guess": "imf_bop_like", "confidence": "medium", "score": score, "sdmx_score": sdmx_score}
    if sdmx_score >= 4:
        return {"domain_guess": "sdmx_macro_timeseries", "confidence": "medium", "score": score, "sdmx_score": sdmx_score}
    if score >= 4:
        return {"domain_guess": "macro_timeseries", "confidence": "medium", "score": score, "sdmx_score": sdmx_score}
    return {"domain_guess": "generic_table", "confidence": "low", "score": score, "sdmx_score": sdmx_score}


def load_mapping(path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    if not path:
        return {}
    if not path.exists():
        return {}
    raw = path.read_bytes()[:1024*1024]
    text, enc = decode_sample(raw)
    dialect, _ = detect_dialect(text, "csv")
    mapping: Dict[str, Dict[str, str]] = {}
    with path.open("r", encoding=enc, errors="replace", newline="") as f:
        reader = csv.DictReader(f, dialect=dialect)
        if not reader.fieldnames:
            return mapping
        fields = {canonical_col_name(x): x for x in reader.fieldnames}
        code_field = fields.get("CODE") or fields.get("ID") or fields.get("KEY") or reader.fieldnames[0]
        label_field = fields.get("LABEL") or fields.get("NAME") or fields.get("TITLE") or fields.get("DESCRIPTION")
        desc_field = fields.get("DESCRIPTION") or fields.get("DESC")
        for row in reader:
            code = safe_cell(row.get(code_field, ""), 120, False).strip()
            if not code:
                continue
            mapping[code] = {
                "label": safe_cell(row.get(label_field, ""), 160, False) if label_field else "",
                "description": safe_cell(row.get(desc_field, ""), 240, False) if desc_field else "",
            }
    return mapping


def row_to_dict(header: List[str], row: List[Any]) -> Dict[str, str]:
    return {header[i]: (str(row[i]) if i < len(row) else "") for i in range(len(header))}


def extract_rows_for_locator(profile: Dict[str, Any]) -> List[Dict[str, str]]:
    cols = [c.get("name") for c in profile.get("columns", [])]
    rows = []
    for r in (profile.get("samples", {}) or {}).get("representative_rows", []):
        rows.append(row_to_dict(cols, r))
    return rows


def infer_rows_from_profile_samples(profile: Dict[str, Any]) -> Tuple[List[str], List[List[str]]]:
    cols = [c.get("name") for c in profile.get("columns", [])]
    reps = (profile.get("samples", {}) or {}).get("representative_rows", [])
    return cols, reps


def summarize_dimension(rows: List[Dict[str, str]], column: Optional[str], mapping: Dict[str, Dict[str, str]], limit: int = 25) -> Dict[str, Any]:
    if not column:
        return {"column": None, "available": False, "unique_count_sample": 0, "top_values": [], "mapping_required": False}
    vals = [r.get(column, "") for r in rows if not is_empty(r.get(column, ""))]
    cnt = Counter(vals)
    top = []
    for code, n in cnt.most_common(limit):
        mapped = mapping.get(code, {})
        top.append({"code": code, "label": mapped.get("label") or None, "description": mapped.get("description") or None, "sample_count": n})
    return {
        "column": column,
        "available": True,
        "unique_count_sample": len(cnt),
        "top_values": top,
        "mapping_required": bool(cnt and not mapping),
        "mapping_applied": bool(mapping),
    }


def time_sort_key(x: str) -> str:
    return str(x).replace("Q", "-").replace("M", "-")


def build_time_coverage(rows: List[Dict[str, str]], time_col: Optional[str], freq_col: Optional[str]) -> Dict[str, Any]:
    vals = [r.get(time_col, "") for r in rows if time_col and not is_empty(r.get(time_col, ""))]
    freqs = [r.get(freq_col, "") for r in rows if freq_col and not is_empty(r.get(freq_col, ""))]
    freq_counts = Counter(freqs)
    by_freq = []
    if time_col and freq_col:
        grouped: Dict[str, List[str]] = defaultdict(list)
        for r in rows:
            f = r.get(freq_col, "")
            t = r.get(time_col, "")
            if f and t:
                grouped[f].append(t)
        for f, tv in sorted(grouped.items()):
            by_freq.append({"frequency": f, "time_min_sample": min(tv, key=time_sort_key), "time_max_sample": max(tv, key=time_sort_key), "observation_count_sample": len(tv)})
    return {
        "time_column": time_col,
        "frequency_column": freq_col,
        "overall_min_sample": min(vals, key=time_sort_key) if vals else None,
        "overall_max_sample": max(vals, key=time_sort_key) if vals else None,
        "frequencies_detected_sample": [{"frequency": k, "count": v} for k, v in freq_counts.most_common(20)],
        "by_frequency_sample": by_freq,
        "mixed_frequency_sample": len(freq_counts) > 1,
    }


def build_key_check(rows: List[Dict[str, str]], key_cols: List[str]) -> Dict[str, Any]:
    if not key_cols:
        return {"tested_on_rows": len(rows), "key_columns": [], "duplicate_key_count_sample": None, "is_unique_in_sample": None}
    seen = set(); dup = 0
    for r in rows:
        key = tuple(r.get(c, "") for c in key_cols)
        if key in seen:
            dup += 1
        else:
            seen.add(key)
    return {"tested_on_rows": len(rows), "key_columns": key_cols, "duplicate_key_count_sample": dup, "is_unique_in_sample": dup == 0}


def build_data_locator(path: Path, manifest: Dict[str, Any], profile_doc: Dict[str, Any], args) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    profiles = profile_doc.get("profiles", [])
    primary = profiles[0] if profiles else {}
    columns = primary.get("columns", []) if isinstance(primary, dict) else []
    roles = infer_macro_roles(columns)
    wide_time_value_columns = detect_wide_time_value_columns(columns)
    value_layout = "wide_time_columns" if len(wide_time_value_columns) >= 1 else "long_value_column"
    guess = domain_guess_from_roles(path, roles, columns, args.domain_preset)
    header, sample_rows = infer_rows_from_profile_samples(primary) if isinstance(primary, dict) else ([], [])
    rows = [row_to_dict(header, r) for r in sample_rows]
    indicator_mapping = load_mapping(args.indicator_mapping)
    entity_mapping = load_mapping(args.entity_mapping)
    shape_guess = primary.get("structure_guess", {}).get("shape_type") if isinstance(primary, dict) else None
    time_columns = [c.get("name") for c in columns if c.get("semantic_guess") == "time" and canonical_col_name(c.get("name")) not in METADATA_TIME_COLUMNS]
    wide_measure_columns = []
    if shape_guess == "wide_measure_columns":
        time_role_names = {roles.get("time_column")}
        wide_measure_columns = [c.get("name") for c in columns if c.get("semantic_guess") in {"measure", "percentage", "currency"} and c.get("name") not in time_role_names]
        roles["value_column"] = None
    indicator_index = summarize_dimension(rows, roles.get("indicator_column"), indicator_mapping)
    entity_index = summarize_dimension(rows, roles.get("entity_column"), entity_mapping)

    if value_layout == "wide_time_columns":
        periods = [x["time_period"] for x in wide_time_value_columns]
        freqs = [r.get(roles.get("frequency_column"), "") for r in rows if roles.get("frequency_column") and not is_empty(r.get(roles.get("frequency_column"), ""))]
        time_coverage = {
            "layout": "wide_time_columns",
            "time_column": None,
            "frequency_column": roles.get("frequency_column"),
            "overall_min_sample": min(periods, key=time_sort_key) if periods else None,
            "overall_max_sample": max(periods, key=time_sort_key) if periods else None,
            "time_value_column_count": len(wide_time_value_columns),
            "time_value_columns_preview": wide_time_value_columns[:40],
            "frequencies_detected_sample": [{"frequency": k, "count": v} for k, v in Counter(freqs).most_common(20)],
            "mixed_frequency_sample": len(Counter(freqs)) > 1,
        }
        key_cols = [roles.get(k) for k in ["entity_column", "indicator_column", "counterpart_column", "frequency_column"] if roles.get(k)]
        warnings.append("Detected wide time-series layout: observation values are stored across year/period columns, not in a single OBS_VALUE column. Downstream extraction should reshape time columns to long format.")
    elif shape_guess == "wide_measure_columns" and wide_measure_columns:
        time_coverage = build_time_coverage(rows, roles.get("time_column"), roles.get("frequency_column"))
        key_cols = [roles.get(k) for k in ["entity_column", "indicator_column", "counterpart_column", "frequency_column", "time_column"] if roles.get(k)]
        for tc in time_columns:
            if tc not in key_cols:
                key_cols.append(tc)
        warnings.append("Detected wide-measure layout: multiple measure/indicator series are stored as separate columns. Downstream extraction may reshape measure columns to long format if a tidy panel is needed.")
    else:
        time_coverage = build_time_coverage(rows, roles.get("time_column"), roles.get("frequency_column"))
        key_cols = [roles.get(k) for k in ["entity_column", "indicator_column", "counterpart_column", "frequency_column", "time_column"] if roles.get(k)]

    key_check = build_key_check(rows, key_cols)
    if roles.get("unit_column") or roles.get("scale_column"):
        warnings.append("Interpret values together with unit and scale columns before comparing values across series.")
    if roles.get("status_column"):
        warnings.append("Check the observation status column before treating observations as final or fully comparable.")
    if indicator_index.get("mapping_required"):
        warnings.append("Only indicator codes were detected. Semantic indicator labels require an external codelist/DSD mapping or adjacent label column.")
    if entity_index.get("mapping_required"):
        warnings.append("Only entity/object codes were detected. Country/economy names require an external area codelist mapping or adjacent label column.")
    if time_coverage.get("mixed_frequency_sample"):
        warnings.append("Multiple frequencies were detected in the sample. Filter frequency before time-series analysis.")
    value_column = roles.get("value_column") if value_layout == "long_value_column" and shape_guess != "wide_measure_columns" else None
    locator = {
        "schema_version": "1.1",
        "source_file": str(path.resolve()),
        "primary_table_id": primary.get("table_id") if isinstance(primary, dict) else None,
        "dataset_type": guess.get("domain_guess"),
        "confidence": guess.get("confidence"),
        "domain_preset": args.domain_preset,
        "value_layout": "wide_measure_columns" if shape_guess == "wide_measure_columns" and wide_measure_columns else value_layout,
        "column_roles": roles,
        "wide_time_value_columns": wide_time_value_columns,
        "wide_measure_columns": wide_measure_columns,
        "indicator_index": indicator_index,
        "entity_index": entity_index,
        "time_coverage": time_coverage,
        "observation_locator": {
            "recommended_key": key_cols + (["<time_period_column>"] if value_layout == "wide_time_columns" else []),
            "value_column": value_column,
            "value_columns": [x["column"] for x in wide_time_value_columns] if value_layout == "wide_time_columns" else (wide_measure_columns if shape_guess == "wide_measure_columns" and wide_measure_columns else None),
            "attribute_columns": [x for x in [roles.get("unit_column"), roles.get("scale_column"), roles.get("status_column")] if x],
            "key_uniqueness_check": key_check,
            "locator_template": {
                "entity": f"{roles.get('entity_column')} == <entity_code>" if roles.get("entity_column") else None,
                "indicator": f"{roles.get('indicator_column')} == <indicator_code>" if roles.get("indicator_column") else None,
                "counterpart": f"{roles.get('counterpart_column')} == <counterpart_code>" if roles.get("counterpart_column") else None,
                "frequency": f"{roles.get('frequency_column')} == <frequency>" if roles.get("frequency_column") else None,
                "time": "select one of the wide time-period columns" if value_layout == "wide_time_columns" else (f"{roles.get('time_column')} between <start> and <end>" if roles.get("time_column") else None),
                "value": "cell at the selected time-period column" if value_layout == "wide_time_columns" else ("selected measure column" if shape_guess == "wide_measure_columns" and wide_measure_columns else roles.get("value_column")),
            },
        },
        "required_preprocessing": [],
        "warnings": warnings,
    }
    if value_layout == "wide_time_columns":
        locator["required_preprocessing"].append("reshape_wide_time_columns_to_long")
    if shape_guess == "wide_measure_columns" and wide_measure_columns:
        locator["required_preprocessing"].append("reshape_wide_measure_columns_to_long_if_tidy_panel_needed")
    if indicator_index.get("mapping_required"):
        locator["required_preprocessing"].append("map_indicator_codes_to_labels")
    if entity_index.get("mapping_required"):
        locator["required_preprocessing"].append("map_entity_codes_to_names")
    if roles.get("unit_column") or roles.get("scale_column"):
        locator["required_preprocessing"].append("apply_or_verify_unit_scaling_before_comparison")
    if roles.get("status_column"):
        locator["required_preprocessing"].append("check_observation_status_before_final_analysis")
    if time_coverage.get("mixed_frequency_sample"):
        locator["required_preprocessing"].append("filter_frequency_before_time_series_analysis")
    return locator, warnings


def build_locator_guide(locator: Dict[str, Any]) -> str:
    roles = locator.get("column_roles", {})
    obs = locator.get("observation_locator", {})
    layout = locator.get("value_layout", "long_value_column")
    lines = ["# Data Locator Guide", ""]
    lines.append("## Dataset Type")
    lines.append(f"- Domain guess: `{locator.get('dataset_type')}`")
    lines.append(f"- Confidence: `{locator.get('confidence')}`")
    lines.append(f"- Value layout: `{layout}`")
    lines.append("")
    lines.append("## Column Roles")
    for k, v in roles.items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## Recommended Observation Key")
    key = obs.get("recommended_key") or []
    lines.append(" × ".join(f"`{x}`" for x in key) if key else "No reliable observation key was inferred.")
    lines.append("")
    lines.append("## Value and Attributes")
    if layout == "wide_time_columns":
        value_cols = obs.get("value_columns") or []
        lines.append("- Value storage: one observation value per time-period column")
        lines.append(f"- Time/value columns detected: {len(value_cols)}")
        preview = locator.get("wide_time_value_columns", [])[:30]
        if preview:
            lines.append("- Time/value column preview:")
            for item in preview:
                lines.append(f"  - `{item.get('column')}` → time `{item.get('time_period')}`, non-empty sample rows: {item.get('non_empty_sample_count')}, missing≈{item.get('missing_rate_sample')}")
    else:
        lines.append(f"- Value column: `{obs.get('value_column')}`")
    attrs = obs.get("attribute_columns") or []
    lines.append(f"- Attribute columns: {', '.join('`'+a+'`' for a in attrs) if attrs else 'None detected'}")
    lines.append("")
    lines.append("## Indicator Index")
    ind = locator.get("indicator_index", {})
    lines.append(f"- Column: `{ind.get('column')}`")
    lines.append(f"- Unique values in sample: {ind.get('unique_count_sample')}")
    for item in ind.get("top_values", [])[:10]:
        label = f" — {item.get('label')}" if item.get("label") else ""
        lines.append(f"  - `{item.get('code')}`{label} (sample count: {item.get('sample_count')})")
    lines.append("")
    lines.append("## Entity/Object Index")
    ent = locator.get("entity_index", {})
    lines.append(f"- Column: `{ent.get('column')}`")
    lines.append(f"- Unique values in sample: {ent.get('unique_count_sample')}")
    for item in ent.get("top_values", [])[:10]:
        label = f" — {item.get('label')}" if item.get("label") else ""
        lines.append(f"  - `{item.get('code')}`{label} (sample count: {item.get('sample_count')})")
    lines.append("")
    lines.append("## Time Coverage")
    tc = locator.get("time_coverage", {})
    lines.append(f"- Layout: `{tc.get('layout', layout)}`")
    lines.append(f"- Time column: `{tc.get('time_column')}`")
    lines.append(f"- Overall sample range: {tc.get('overall_min_sample')} to {tc.get('overall_max_sample')}")
    if tc.get("time_value_column_count") is not None:
        lines.append(f"- Time/value column count: {tc.get('time_value_column_count')}")
    lines.append(f"- Mixed frequency in sample: {tc.get('mixed_frequency_sample')}")
    for f in tc.get("frequencies_detected_sample", [])[:10]:
        lines.append(f"  - `{f.get('frequency')}`: {f.get('count')} sample rows")
    lines.append("")
    lines.append("## Required Preprocessing Before Automation")
    req = locator.get("required_preprocessing", [])
    if req:
        for r in req:
            lines.append(f"- {r}")
    else:
        lines.append("- No domain-specific preprocessing requirement was inferred from the sample.")
    lines.append("")
    lines.append("## Warnings")
    for w in locator.get("warnings", []) or ["No domain-specific warnings were generated."]:
        lines.append(f"- {w}")
    return "\n".join(lines) + "\n"


def write_locator_outputs(out_dir: Path, locator: Dict[str, Any]) -> None:
    (out_dir / "data_locator_spec.json").write_text(json.dumps(locator, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "data_locator_guide.md").write_text(build_locator_guide(locator), encoding="utf-8")


def build_digest(manifest: Dict[str, Any], profile_doc: Dict[str, Any], ambiguities: List[str]) -> str:
    lines = []
    lines.append("# Table Digest")
    lines.append("")
    lines.append("## Source")
    lines.append(f"- File: `{manifest['file_name']}`")
    lines.append(f"- Type: `{manifest['file_type']}`")
    lines.append(f"- Size: {manifest['file_size_bytes']:,} bytes")
    lines.append(f"- Mode: `{manifest['mode']}`")
    lines.append(f"- Capability level: `{manifest['capability_level']}`")
    oc = manifest.get("output_control", {})
    if oc:
        lines.append(f"- JSON output policy: `{oc.get('policy')}` — {oc.get('reason')}")
    lines.append("")
    lines.append("## Detected Tables")
    for t in manifest.get("tables", []):
        lines.append(f"- `{t['table_id']}`: {t.get('name')} ({t.get('kind')}), rows≈{t.get('rows_estimate')}, cols≈{t.get('columns_estimate')}, confidence={t.get('confidence')}")
    lines.append("")
    dp = manifest.get("domain_profile") or {}
    if dp:
        lines.append("## Data Locator Summary")
        lines.append(f"- Dataset type guess: `{dp.get('dataset_type')}`")
        lines.append(f"- Confidence: `{dp.get('confidence')}`")
        if dp.get("value_layout"):
            lines.append(f"- Value layout: `{dp.get('value_layout')}`")
        roles = dp.get("column_roles") or {}
        for role in ["entity_column", "indicator_column", "counterpart_column", "time_column", "frequency_column", "value_column", "unit_column", "scale_column", "status_column"]:
            if roles.get(role):
                lines.append(f"- {role}: `{roles.get(role)}`")
        if dp.get("time_value_column_count") is not None:
            lines.append(f"- Time/value columns detected: {dp.get('time_value_column_count')}")
        lines.append("- Locator files: `data_locator_spec.json`, `data_locator_guide.md`")
        lines.append("")
    profiles = profile_doc.get("profiles", [])
    if profiles:
        primary = profiles[0]
        lines.append("## Primary Table Guess")
        lines.append(f"- Table ID: `{primary['table_id']}`")
        sg = primary.get("structure_guess", {})
        lines.append(f"- Shape type guess: `{sg.get('shape_type')}`")
        if sg.get("grain_guess"):
            lines.append(f"- Grain guess: {sg.get('grain_guess')}")
        if dp.get("value_layout") == "wide_time_columns":
            roles_for_grain = dp.get("column_roles") or {}
            grain_parts = [roles_for_grain.get(k) for k in ["entity_column", "indicator_column", "counterpart_column", "frequency_column"] if roles_for_grain.get(k)]
            if grain_parts:
                lines.append("- Wide-layout row grain: one row is likely a series defined by " + " × ".join(f"`{x}`" for x in grain_parts) + "; observations are stored in the year/period columns.")
        lines.append(f"- Header confidence: `{sg.get('header_confidence')}`")
        lines.append("")
        lines.append("## Key Columns")
        cols = primary.get("columns", [])
        for c in cols[:40]:
            extra = []
            if c.get("semantic_guess") != "unknown":
                extra.append(f"semantic={c.get('semantic_guess')}")
            if c.get("missing_rate_sample") is not None:
                extra.append(f"missing≈{c.get('missing_rate_sample')}")
            ex = c.get("examples", [])[:3]
            exs = ", ".join(repr(x) for x in ex)
            lines.append(f"- `{c.get('name')}`: {c.get('inferred_type')} ({'; '.join(extra)}); examples: {exs}")
        if len(cols) > 40:
            lines.append(f"- ... {len(cols) - 40} additional columns omitted from digest; see table_profile.json.")
        lines.append("")
    lines.append("## Warnings")
    ws = manifest.get("warnings", [])[:20]
    if not ws:
        lines.append("- No major file-level warnings from the profiler.")
    else:
        for w in ws:
            lines.append(f"- {w}")
    lines.append("")
    lines.append("## Ambiguities")
    if ambiguities:
        for a in ambiguities[:20]:
            lines.append(f"- {a}")
    else:
        lines.append("- No major structural ambiguities were detected in the sampled profile. This does not guarantee semantic correctness.")
    lines.append("")
    lines.append("## Recommended Next Questions")
    lines.append("- Which detected table should be treated as primary?")
    lines.append("- Do the inferred header row and column meanings look correct?")
    lines.append("- Should downstream work use sampled profiling only, or is an exact/full scan required?")
    return "\n".join(lines) + "\n"


def build_ambiguities_md(ambiguities: List[str]) -> str:
    lines = ["# Ambiguities Requiring Confirmation", ""]
    if not ambiguities:
        lines.append("No major structural ambiguities were detected in the sampled profile. This does not guarantee semantic correctness.")
    else:
        lines.append("## High Priority")
        for a in ambiguities:
            lines.append(f"- {a}")
    lines.append("")
    return "\n".join(lines)




def write_schema_preset(out_dir: Path, preset: str) -> None:
    """Write a lightweight downstream schema hint for common agent workflows."""
    if preset == "none":
        return
    if preset == "generic":
        content = {
            "purpose": "Optional downstream schema hint generated by tabular-file-understanding.",
            "note": "This is not a validation contract. It helps agents map the structural digest into common workflows.",
            "artifacts": ["table_manifest.json", "table_profile.json", "table_digest.md", "ambiguities.md"],
        }
    elif preset == "rag":
        content = {
            "purpose": "RAG-oriented table understanding hint",
            "recommended_index_units": ["table_digest.md", "column profiles", "ambiguities"],
            "avoid_indexing": ["full raw table", "large row samples", "sensitive cell values"],
            "retrieval_notes": "Use SQL/DataFrame tools for numeric aggregation; use RAG only for structural descriptions and text-like columns.",
        }
    elif preset == "sql":
        content = {
            "purpose": "SQL-oriented table understanding hint",
            "recommended_inputs": ["normalized column names", "inferred types", "primary table guess", "row grain guess"],
            "notes": "The profiler does not create a database. Use the digest to decide how to load the file into a SQL engine if the user requests querying.",
        }
    else:
        content = {"purpose": "unknown preset", "preset": preset}
    (out_dir / "downstream_schema_hint.json").write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def find_header_index(header: List[str], aliases: List[str]) -> Optional[int]:
    canon_map = {canonical_col_name(h): i for i, h in enumerate(header)}
    for a in aliases:
        ca = canonical_col_name(a)
        if ca in canon_map:
            return canon_map[ca]
    return None


def classify_bop_capital_flow_indicator(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Classify BOP indicators using the cataloged label/dimension fields.

    This is intentionally rule-based and transparent. It avoids matching broad
    words such as "investment" in descriptions, because that creates false
    positives across direct/portfolio/other investment categories.
    """
    label = str(rec.get("indicator_label") or "").strip().lower()
    code = str(rec.get("indicator_code") or "").strip().upper()
    acct = " ".join(sorted(rec.get("bop_accounting_labels", set()))).lower() if isinstance(rec.get("bop_accounting_labels"), set) else str(rec.get("bop_accounting_labels", "")).lower()
    groups = []
    if label.startswith("current account") or code in {"CAB", "CABXEF"}:
        groups.append("current_account_balance")
    if label.startswith("capital account") or code in {"KAB", "KAXRRI"}:
        groups.append("capital_account")
    if label.startswith("financial account balance") or code in {"FAB", "FABXRRI", "FAB_AFR"}:
        groups.append("financial_account_aggregate")
    if label.startswith("direct investment") or code.startswith("D_"):
        groups.append("direct_investment")
    if label.startswith("portfolio investment") or code.startswith("P_"):
        groups.append("portfolio_investment")
    if label.startswith("other investment") or code.startswith("O_"):
        groups.append("other_investment")
    if label.startswith("financial derivatives") or code.startswith("FD_"):
        groups.append("financial_derivatives")
    if label.startswith("reserve assets") or code.startswith("R_"):
        groups.append("reserve_assets")
    # Income series are useful for external-balance work but are not capital-flow
    # transaction indicators in the narrow sense.
    is_income = "investment income" in label or "income" in label
    is_transaction = any(x in acct for x in ["net acquisition of financial assets", "net incurrence of liabilities", "assets less liabilities", "transactions"])
    narrow_flow_groups = {"financial_account_aggregate", "direct_investment", "portfolio_investment", "other_investment", "financial_derivatives", "reserve_assets"}
    narrow_capital_flow = bool(set(groups) & narrow_flow_groups) and is_transaction and not is_income
    return {
        "capital_flow_groups": groups,
        "is_bop_financial_flow_transaction": narrow_capital_flow,
        "is_investment_income_series": is_income,
        "classification_rule": "prefix/code/accounting-entry rule; descriptions are not used for broad category matching",
    }


def scan_imf_wide_indicator_catalog(path: Path, args, out_dir: Path, max_rows: Optional[int] = None) -> Dict[str, Any]:
    """Full/large streaming scan for IMF web CSV wide-time exports.

    This does not modify the input file. It creates a compact indicator catalog so
    an agent can reason about which BOP/PIP variables are available without
    loading raw observations into context.
    """
    started = time.time()
    with path.open("rb") as f:
        raw = f.read(args.sample_bytes)
    sample_text, encoding = decode_sample(raw)
    dialect, _ = detect_dialect(sample_text, detect_file_type(path))

    catalog: Dict[str, Dict[str, Any]] = {}
    total_rows = 0
    with path.open("r", encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f, dialect)
        try:
            header = next(reader)
        except StopIteration:
            header = []
        time_cols = [(i, h, normalize_time_period_column(h)) for i, h in enumerate(header) if is_time_period_column_name(h)]
        idx = {
            "indicator_code": find_header_index(header, ["INDICATOR.ID", "INDICATOR_ID", "BOP_ITEM", "SERIES_CODE"]),
            "indicator_label": find_header_index(header, ["INDICATOR", "BOP_ITEM_LABEL"]),
            "indicator_desc": find_header_index(header, ["INDICATOR.Description", "INDICATOR_DESCRIPTION"]),
            "country": find_header_index(header, ["COUNTRY.ID", "COUNTRY_ID", "REF_AREA"]),
            "frequency": find_header_index(header, ["FREQUENCY.ID", "FREQUENCY_ID", "FREQ"]),
            "unit": find_header_index(header, ["UNIT.ID", "UNIT_ID", "UNIT_MEASURE"]),
            "scale": find_header_index(header, ["SCALE.ID", "SCALE_ID", "UNIT_MULT"]),
            "bop_accounting": find_header_index(header, ["BOP_ACCOUNTING_ENTRY.ID", "ACCOUNTING_ENTRY.ID"]),
            "bop_accounting_label": find_header_index(header, ["BOP_ACCOUNTING_ENTRY", "ACCOUNTING_ENTRY"]),
            "functional_cat": find_header_index(header, ["FUNCTIONAL_CAT.ID", "FUNCTIONAL_CAT_ID"]),
            "functional_cat_label": find_header_index(header, ["FUNCTIONAL_CAT"]),
            "flow_stock": find_header_index(header, ["FLOW_STOCK_ENTRY.ID", "FLOW_STOCK_ENTRY_ID"]),
            "flow_stock_label": find_header_index(header, ["FLOW_STOCK_ENTRY"]),
            "accounts": find_header_index(header, ["ACCOUNTS.ID", "ACCOUNTS_ID"]),
            "sector": find_header_index(header, ["SECTOR.ID", "SECTOR_ID"]),
        }
        def cell(row, k):
            i = idx.get(k)
            return row[i].strip() if i is not None and i < len(row) else ""
        for row in reader:
            total_rows += 1
            if max_rows and total_rows > max_rows:
                break
            code = cell(row, "indicator_code") or cell(row, "indicator_label") or "<missing>"
            rec = catalog.get(code)
            if rec is None:
                rec = {
                    "indicator_code": code,
                    "indicator_label": cell(row, "indicator_label"),
                    "indicator_description": safe_cell(cell(row, "indicator_desc"), 500),
                    "row_count": 0,
                    "non_empty_observation_cells": 0,
                    "first_period_with_data": None,
                    "last_period_with_data": None,
                    "countries": set(),
                    "frequencies": set(),
                    "units": set(),
                    "scales": set(),
                    "bop_accounting_entries": set(),
                    "bop_accounting_labels": set(),
                    "functional_categories": set(),
                    "functional_category_labels": set(),
                    "flow_stock_entries": set(),
                    "flow_stock_labels": set(),
                    "accounts": set(),
                    "sectors": set(),
                    "sample_series_codes": [],
                }
                catalog[code] = rec
            rec["row_count"] += 1
            for k, field in [("country", "countries"), ("frequency", "frequencies"), ("unit", "units"), ("scale", "scales"), ("bop_accounting", "bop_accounting_entries"), ("bop_accounting_label", "bop_accounting_labels"), ("functional_cat", "functional_categories"), ("functional_cat_label", "functional_category_labels"), ("flow_stock", "flow_stock_entries"), ("flow_stock_label", "flow_stock_labels"), ("accounts", "accounts"), ("sector", "sectors")]:
                v = cell(row, k)
                if v:
                    rec[field].add(v)
            sc = row[1].strip() if len(row) > 1 else ""
            if sc and len(rec["sample_series_codes"]) < 5 and sc not in rec["sample_series_codes"]:
                rec["sample_series_codes"].append(sc)
            for i, _name, period in time_cols:
                if i < len(row) and not is_empty(row[i]):
                    rec["non_empty_observation_cells"] += 1
                    if rec["first_period_with_data"] is None or time_sort_key(period) < time_sort_key(rec["first_period_with_data"]):
                        rec["first_period_with_data"] = period
                    if rec["last_period_with_data"] is None or time_sort_key(period) > time_sort_key(rec["last_period_with_data"]):
                        rec["last_period_with_data"] = period

    rows_out = []
    for rec in catalog.values():
        out = {}
        for k, v in rec.items():
            if isinstance(v, set):
                out[k + "_count"] = len(v)
                out[k + "_sample"] = sorted(v)[:20]
            else:
                out[k] = v
        label_blob = " ".join(str(out.get(x, "")) for x in ["indicator_code", "indicator_label", "indicator_description", "bop_accounting_labels_sample", "functional_category_labels_sample", "flow_stock_labels_sample"])
        lb = label_blob.lower()
        score = 0
        for term in ["financial account", "capital account", "current account", "direct investment", "portfolio investment", "other investment", "reserve assets", "financial derivatives", "assets", "liabilities", "net acquisition", "net incurrence", "balance"]:
            if term in lb:
                score += 1
        out["capital_flow_relevance_score"] = score
        out.update(classify_bop_capital_flow_indicator(rec))
        rows_out.append(out)
    rows_out.sort(key=lambda x: (x.get("capital_flow_relevance_score", 0), x.get("non_empty_observation_cells", 0), x.get("row_count", 0)), reverse=True)

    # JSON
    summary = {
        "schema_version": "1.0",
        "source_file": str(path.resolve()),
        "rows_scanned": total_rows,
        "indicator_count": len(rows_out),
        "time_value_column_count": len(time_cols),
        "time_value_range": [time_cols[0][2], time_cols[-1][2]] if time_cols else [None, None],
        "elapsed_seconds": round(time.time() - started, 3),
        "note": "Streaming indicator catalog for IMF wide-time CSV. Counts are exact for scanned rows; original file is read-only.",
        "indicators": rows_out,
    }
    (out_dir / "domain_indicator_catalog.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV compact
    csv_fields = ["indicator_code", "indicator_label", "row_count", "non_empty_observation_cells", "first_period_with_data", "last_period_with_data", "capital_flow_relevance_score", "capital_flow_groups", "is_bop_financial_flow_transaction", "is_investment_income_series", "frequencies_count", "frequencies_sample", "units_sample", "scales_sample", "bop_accounting_entries_sample", "bop_accounting_labels_sample", "functional_categories_sample", "functional_category_labels_sample", "flow_stock_entries_sample", "flow_stock_labels_sample", "countries_count", "sample_series_codes", "indicator_description"]
    with (out_dir / "domain_indicator_catalog.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        for r in rows_out:
            w.writerow({k: json.dumps(r.get(k), ensure_ascii=False) if isinstance(r.get(k), (list, dict)) else r.get(k, "") for k in csv_fields})

    # Markdown guide
    narrow = [r for r in rows_out if r.get("is_bop_financial_flow_transaction")]
    lines = ["# Domain Indicator Catalog", "", f"- Rows scanned: {total_rows:,}", f"- Indicator count: {len(rows_out):,}", f"- Narrow BOP financial-flow transaction indicators: {len(narrow):,}", f"- Time/value columns: {len(time_cols):,}", f"- Time range from columns: {summary['time_value_range'][0]} to {summary['time_value_range'][1]}", "", "## Top BOP financial-flow transaction indicators", ""]
    for r in narrow[:50]:
        lines.append(f"- `{r.get('indicator_code')}` — {r.get('indicator_label') or '(no label)'}")
        lines.append(f"  - observations: {r.get('non_empty_observation_cells'):,}; rows: {r.get('row_count'):,}; period: {r.get('first_period_with_data')} to {r.get('last_period_with_data')}; relevance_score: {r.get('capital_flow_relevance_score')}")
        cats = r.get("functional_category_labels_sample") or r.get("bop_accounting_labels_sample") or []
        if cats:
            lines.append(f"  - categories: {', '.join(str(x) for x in cats[:8])}")
    (out_dir / "domain_indicator_catalog.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {k: summary[k] for k in ["rows_scanned", "indicator_count", "time_value_column_count", "time_value_range", "elapsed_seconds"]}


def check_deps() -> None:
    import importlib.util
    optional = ["pandas", "openpyxl", "duckdb", "pyarrow", "polars", "pdfplumber", "fitz"]
    print("Dependency check for tabular-file-understanding")
    print(f"Python: {sys.version.split()[0]}")
    print("Core standard-library profiler: available")
    print("Optional Python libraries:")
    for name in optional:
        print(f"- {name}: {'available' if importlib.util.find_spec(name) else 'missing'}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Profile large tabular files into LLM-readable structural artifacts using Python stdlib only.")
    ap.add_argument("--input", "-i", type=Path, help="Input CSV/TSV/XLSX/PDF file")
    ap.add_argument("--out", "-o", type=Path, help="Output directory")
    ap.add_argument("--sample-rows", type=int, default=1000, help="Maximum rows to sample per table/sheet")
    ap.add_argument("--scan-limit-rows", type=int, default=100000, help="Maximum CSV rows to scan unless --full-scan is set")
    ap.add_argument("--sample-bytes", type=int, default=1024*1024, help="Bytes to read for encoding/dialect/PDF metadata sampling")
    ap.add_argument("--max-sheets", type=int, default=20, help="Maximum Excel sheets to sample")
    ap.add_argument("--full-scan", action="store_true", help="For CSV/TSV, scan the full file for row count and row-width checks; column profiles remain sample-bounded")
    ap.add_argument("--max-cell-chars", type=int, default=120, help="Maximum characters retained per sample/example cell")
    ap.add_argument("--redact-samples", action="store_true", help="Redact email-like, phone-like, and long-number values in examples and sample rows")
    ap.add_argument("--no-samples", action="store_true", help="Omit row samples and column-level examples/top-values from table_profile.json")
    ap.add_argument("--schema-preset", choices=["none", "generic", "rag", "sql"], default="none", help="Optionally write downstream_schema_hint.json for common downstream workflows")
    ap.add_argument("--domain-full-scan", action="store_true", help="For IMF/SDMX-style wide-time CSVs, stream the file to create domain_indicator_catalog.{json,csv,md} with indicator availability and coverage")
    ap.add_argument("--domain-scan-limit-rows", type=int, default=0, help="Optional row limit for --domain-full-scan; 0 means scan all rows")
    ap.add_argument("--domain-preset", choices=["auto", "generic", "macro-timeseries", "sdmx", "imf-bop"], default="auto", help="Infer domain-specific locator metadata for macro/SDMX/IMF-style time-series tables")
    ap.add_argument("--indicator-mapping", type=Path, default=None, help="Optional CSV mapping file for indicator codes with columns like code,label,description")
    ap.add_argument("--entity-mapping", type=Path, default=None, help="Optional CSV mapping file for entity/country codes with columns like code,label,description")
    ap.add_argument("--output-policy", choices=["auto", "full", "balanced", "compact", "very-compact"], default="auto", help="Control JSON output detail. auto keeps small files full, reduces larger/wider files.")
    ap.add_argument("--small-file-mb", type=float, default=10.0, help="Auto policy threshold: below this file size, keep full JSON detail if the table is not wide.")
    ap.add_argument("--large-file-mb", type=float, default=100.0, help="Auto policy threshold: at/above this file size, use compact JSON output.")
    ap.add_argument("--huge-file-mb", type=float, default=1024.0, help="Auto policy threshold: at/above this file size, use very-compact JSON output.")
    ap.add_argument("--medium-column-threshold", type=int, default=200, help="Auto policy threshold: at/above this column count, use balanced JSON output.")
    ap.add_argument("--large-column-threshold", type=int, default=1000, help="Auto policy threshold: at/above this column count, use compact JSON output.")
    ap.add_argument("--huge-column-threshold", type=int, default=5000, help="Auto policy threshold: at/above this column count, use very-compact JSON output.")
    ap.add_argument("--compact-max-profile-columns", type=int, default=1000, help="Maximum detailed column profiles retained by compact policy.")
    ap.add_argument("--very-compact-max-profile-columns", type=int, default=300, help="Maximum detailed column profiles retained by very-compact policy.")
    ap.add_argument("--check-deps", action="store_true", help="Print optional dependency availability and exit")
    args = ap.parse_args(argv)

    if args.check_deps:
        check_deps()
        return 0
    if not args.input or not args.out:
        ap.error("--input and --out are required unless --check-deps is used")
    path = args.input
    if not path.exists():
        raise SystemExit(f"Input file not found: {path}")
    args.out.mkdir(parents=True, exist_ok=True)

    ftype = detect_file_type(path)
    file_warnings = []
    ambiguities = []
    tables = []
    profiles = []
    mode = "sampled"
    capability = "basic"
    features_available = ["file metadata", "bounded sampling", "standard-library Python profiling"]
    features_unavailable = []

    if ftype in {"csv", "tsv"}:
        table, profile, w, a = profile_csv(path, args)
        tables.append(table); profiles.append(profile)
        file_warnings.extend(w); ambiguities.extend(a)
        if args.full_scan:
            mode = "full"
    elif ftype == "xlsx":
        ts, ps, w, a = profile_xlsx(path, args)
        tables.extend(ts); profiles.extend(ps)
        file_warnings.extend(w); ambiguities.extend(a)
        features_available.append("xlsx container and worksheet XML sampling")
        features_unavailable.append("Excel formula execution and macro evaluation")
    elif ftype == "pdf":
        table, profile, w, a = profile_pdf(path, args)
        tables.append(table); profiles.append(profile)
        file_warnings.extend(w); ambiguities.extend(a)
        mode = "limited"
        capability = "limited"
        features_unavailable.append("authoritative PDF table extraction without optional PDF/OCR libraries")
    else:
        mode = "limited"
        capability = "limited"
        file_warnings.append("Unknown or unsupported file type")
        ambiguities.append("The file type is not recognized as CSV, TSV, XLSX, or PDF by the reference profiler.")
        features_unavailable.append("format-specific profiling")

    # Build domain locator before sample stripping and adaptive output reduction so
    # row samples remain available for role/key inference.
    pre_policy_profile_doc = {"schema_version": "1.0", "source_file": str(path.resolve()), "profiles": json.loads(json.dumps(profiles, ensure_ascii=False))}
    pre_manifest = {"schema_version": "1.0", "source_file": str(path.resolve()), "file_type": ftype, "tables": tables}
    data_locator, locator_warnings = build_data_locator(path, pre_manifest, pre_policy_profile_doc, args)

    if args.no_samples:
        strip_column_value_samples(profiles)
        strip_locator_value_samples(data_locator)
        file_warnings.append("--no-samples removed row-level samples, column-level examples/top-values, and sample-derived locator values from generated artifacts.")

    output_policy = choose_output_policy(args, path.stat().st_size, profiles)
    policy_warnings = apply_output_policy(profiles, output_policy, redact=args.redact_samples)
    file_warnings.extend(policy_warnings)
    if output_policy.get("policy") in {"compact", "very-compact"}:
        ambiguities.append("JSON output detail was intentionally reduced by the adaptive output policy. Use --output-policy full if complete profiling artifacts are required and storage/context size is acceptable.")

    profile_by_id = {p.get("table_id"): p for p in profiles if isinstance(p, dict)}
    for t in tables:
        p_for_t = profile_by_id.get(t.get("table_id"), {})
        t["columns_omitted_by_output_policy"] = p_for_t.get("columns_omitted_by_output_policy", 0)
        if p_for_t.get("omitted_column_names_preview"):
            t["omitted_column_names_preview"] = p_for_t.get("omitted_column_names_preview")

    profiling_success = bool(tables and profiles)
    if profiling_success:
        understanding_quality = "well understood" if capability != "limited" and not any("Header row could not" in x for x in ambiguities) else "partially understood"
    else:
        understanding_quality = "not well understood"
        file_warnings.append("No table/profile could be produced; inspect warnings before treating this run as successful.")

    manifest = {
        "schema_version": "1.0",
        "source_file": str(path.resolve()),
        "file_name": path.name,
        "file_type": ftype,
        "file_size_bytes": path.stat().st_size,
        "created_at_utc": utc_now(),
        "profiler": {"name": "profile_tabular_file.py", "version": VERSION, "python_version": sys.version.split()[0]},
        "profiling_options": {"sample_rows": args.sample_rows, "scan_limit_rows": args.scan_limit_rows, "sample_bytes": args.sample_bytes, "max_cell_chars": args.max_cell_chars, "redact_samples": args.redact_samples, "no_samples": args.no_samples, "schema_preset": args.schema_preset, "output_policy": args.output_policy, "domain_preset": args.domain_preset, "indicator_mapping": str(args.indicator_mapping) if args.indicator_mapping else None, "entity_mapping": str(args.entity_mapping) if args.entity_mapping else None},
        "mode": mode,
        "capability_level": capability,
        "output_control": output_policy,
        "profiling_success": profiling_success,
        "understanding_quality": understanding_quality,
        "features_available": features_available,
        "features_unavailable": features_unavailable,
        "warnings": sorted(set(file_warnings)),
        "tables": tables,
    }
    profile_doc = {"schema_version": "1.0", "source_file": str(path.resolve()), "profiles": profiles}
    manifest["domain_profile"] = {
        "dataset_type": data_locator.get("dataset_type"),
        "confidence": data_locator.get("confidence"),
        "value_layout": data_locator.get("value_layout"),
        "time_value_column_count": len(data_locator.get("wide_time_value_columns") or []),
        "column_roles": data_locator.get("column_roles"),
        "locator_outputs": ["data_locator_spec.json", "data_locator_guide.md"],
    }
    if locator_warnings:
        manifest["warnings"] = sorted(set(manifest.get("warnings", []) + locator_warnings))

    (args.out / "table_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "table_profile.json").write_text(json.dumps(profile_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "table_digest.md").write_text(build_digest(manifest, profile_doc, ambiguities), encoding="utf-8")
    (args.out / "ambiguities.md").write_text(build_ambiguities_md(ambiguities), encoding="utf-8")
    write_locator_outputs(args.out, data_locator)
    write_schema_preset(args.out, args.schema_preset)
    domain_indicator_catalog_summary = None
    if args.domain_full_scan and ftype in {"csv", "tsv"}:
        domain_indicator_catalog_summary = scan_imf_wide_indicator_catalog(path, args, args.out, max_rows=(args.domain_scan_limit_rows or None))

    print(json.dumps({
        "ok": True,
        "output_dir": str(args.out.resolve()),
        "file_type": ftype,
        "tables_detected": len(tables),
        "profiling_success": profiling_success,
        "understanding_quality": understanding_quality,
        "mode": mode,
        "capability_level": capability,
        "output_control": output_policy,
        "domain_profile": manifest.get("domain_profile"),
        "domain_indicator_catalog": domain_indicator_catalog_summary,
        "data_locator_spec": str((args.out / "data_locator_spec.json").resolve()),
        "digest": str((args.out / "table_digest.md").resolve()),
        "ambiguities": str((args.out / "ambiguities.md").resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
