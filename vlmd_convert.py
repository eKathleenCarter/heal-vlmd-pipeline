"""Generic YAML-driven VLMD converter.

Reads a format YAML spec and applies all mapping rules to convert any
supported data dictionary format to VLMD fields JSON.

Replaces hbcd_convert.py — run with --format formats/hbcd.yaml to get
identical output.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def _detect_encoding(file_path: str) -> str:
    try:
        with open(file_path, encoding="utf-8") as f:
            f.read(4096)
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


# ── Label cleaning strategies ────────────────────────────────────────────────

def _strip_outer_quotes(s: str) -> str:
    """Remove one layer of outer escaped double-quotes from a label string."""
    s = s.strip()
    if s.startswith('"') and s.endswith('"') and len(s) > 2:
        inner = s[1:-1]
        if not (inner.startswith('"') and inner.endswith('"')):
            return inner
    return s


LABEL_CLEANERS = {
    "strip_outer_quotes": _strip_outer_quotes,
    "strip": str.strip,
    None: str.strip,
}


# ── Levels parsers ───────────────────────────────────────────────────────────

def _parse_json_array(raw: str, value_key: str, label_key: str,
                      cleaner) -> tuple[list[str], dict[str, str]]:
    if not raw or raw.strip() in ("", "[]", "nan"):
        return [], {}
    try:
        items = json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        return [], {}
    if not isinstance(items, list):
        return [], {}
    enum_values = [str(item[value_key]) for item in items if value_key in item]
    enum_labels = {
        str(item[value_key]): cleaner(str(item.get(label_key, "")))
        for item in items
        if value_key in item
    }
    return enum_values, enum_labels


def _parse_pipe_separated(raw: str, pair_sep: str,
                           choice_sep: str) -> tuple[list[str], dict[str, str]]:
    if not raw or raw.strip() in ("", "nan"):
        return [], {}
    enum_values = []
    enum_labels = {}
    for choice in raw.split(choice_sep):
        parts = choice.split(pair_sep, 1)
        if len(parts) == 2:
            val = parts[0].strip()
            lbl = parts[1].strip()
            enum_values.append(val)
            enum_labels[val] = lbl
        elif len(parts) == 1 and parts[0].strip():
            val = parts[0].strip()
            enum_values.append(val)
            enum_labels[val] = val
    return enum_values, enum_labels


def _parse_comma_separated(raw: str) -> tuple[list[str], dict[str, str]]:
    if not raw or raw.strip() in ("", "nan"):
        return [], {}
    vals = [v.strip() for v in raw.split(",") if v.strip()]
    return vals, {v: v for v in vals}


def parse_levels(raw: str, levels_spec: dict | None) -> tuple[list[str], dict[str, str]]:
    if not levels_spec or not raw or str(raw).strip().lower() in ("", "nan"):
        return [], {}
    fmt = levels_spec.get("format", "auto_detect")
    cleaner = LABEL_CLEANERS.get(levels_spec.get("label_cleaning"), str.strip)

    if fmt == "json_array":
        return _parse_json_array(
            raw,
            levels_spec.get("value_key", "value"),
            levels_spec.get("label_key", "label"),
            cleaner,
        )
    if fmt == "pipe_separated":
        return _parse_pipe_separated(
            raw,
            levels_spec.get("pair_separator", ","),
            levels_spec.get("choice_separator", "|"),
        )
    if fmt == "comma_separated":
        return _parse_comma_separated(raw)
    if fmt == "auto_detect":
        # Try json_array first, then pipe_separated
        result = _parse_json_array(raw, "value", "label", str.strip)
        if result[0]:
            return result
        result = _parse_pipe_separated(raw, ",", "|")
        if result[0]:
            return result
        return _parse_comma_separated(raw)
    return [], {}


# ── Column resolution helpers ────────────────────────────────────────────────

def resolve_column_spec(spec: Any, df_columns: set[str]) -> str | None:
    """Resolve a column spec (string or list of candidates) to an actual column name."""
    if spec is None:
        return None
    if isinstance(spec, str):
        return spec if spec in df_columns else None
    if isinstance(spec, list):
        for candidate in spec:
            if candidate and candidate in df_columns:
                return candidate
    return None


def get_val(row: dict, col: str | None) -> str:
    if not col:
        return ""
    v = row.get(col, "")
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


# ── Stata reader ──────────────────────────────────────────────────────────────

def read_stata(file_path: str) -> pd.DataFrame:
    try:
        import pyreadstat
    except ImportError:
        raise ImportError("pyreadstat required for Stata files: pip install pyreadstat")
    df, meta = pyreadstat.read_dta(file_path)
    # Build normalized dataframe with expected column names
    records = []
    for col in df.columns:
        rec = {
            "varname": col,
            "varlabel": meta.column_labels.get(col, "") or "",
            "vartype": str(df[col].dtype),
        }
        # Add value labels if present
        vl = (meta.variable_value_labels or {}).get(col, {})
        if vl:
            # Store as JSON array in a value_labels column
            items = [{"value": str(k), "label": str(v)} for k, v in vl.items()]
            rec["value_labels"] = json.dumps(items)
        else:
            rec["value_labels"] = ""
        records.append(rec)
    return pd.DataFrame(records, dtype=str)


# ── Row converter ─────────────────────────────────────────────────────────────

def row_to_vlmd_field(row: dict, spec: dict, resolved_cols: dict) -> dict:
    """Convert one row dict to a VLMD field dict using pre-resolved column names."""
    field: dict = {}

    # name (required)
    field["name"] = get_val(row, resolved_cols.get("name_column"))

    # description (required)
    desc = get_val(row, resolved_cols.get("description_column"))
    field["description"] = desc  # empty string flagged by linter

    # title
    title = get_val(row, resolved_cols.get("title_column"))
    if title:
        field["title"] = title

    # type
    type_col = resolved_cols.get("type_mapping_column")
    if type_col:
        raw_type = get_val(row, type_col).lower()
        lookup = spec.get("type_mapping", {}).get("lookup", {})
        vlmd_type = lookup.get(raw_type)
        if vlmd_type:
            field["type"] = vlmd_type

    # enumOrdered
    ordered_col = resolved_cols.get("enum_ordered_column")
    if ordered_col:
        trigger_vals = spec.get("enum_ordered", {}).get("trigger_values", [])
        if get_val(row, ordered_col).lower() in [v.lower() for v in trigger_vals]:
            field["enumOrdered"] = True

    # section
    section_val = get_val(row, resolved_cols.get("section_primary_column"))
    if not section_val:
        section_val = get_val(row, resolved_cols.get("section_fallback_column"))
    if section_val:
        field["section"] = section_val

    # levels → constraints.enum + enumLabels
    levels_col = resolved_cols.get("levels_column")
    if levels_col:
        raw_levels = get_val(row, levels_col)
        # For stata, levels come from value_labels column
        levels_source = raw_levels
        if spec.get("levels", {}).get("format") == "stata_value_labels":
            levels_source = get_val(row, "value_labels")
            levels_spec_override = {"format": "json_array", "value_key": "value", "label_key": "label"}
            enum_values, enum_labels = parse_levels(levels_source, levels_spec_override)
        else:
            enum_values, enum_labels = parse_levels(levels_source, spec.get("levels"))
        if enum_values:
            field.setdefault("constraints", {})["enum"] = enum_values
            field["enumLabels"] = enum_labels

    # relatedConcepts
    rel_concepts = []
    for rc_spec in spec.get("related_concepts", []):
        url_col = rc_spec.get("url_column")
        if not url_col:
            continue
        url = get_val(row, url_col)
        if rc_spec.get("require_http") and not url.startswith("http"):
            continue
        if url:
            title_col = rc_spec.get("title_column")
            rc = {
                "url": url,
                "source": rc_spec.get("source_name", ""),
            }
            if title_col:
                t = get_val(row, title_col)
                if t:
                    rc["title"] = t
            rel_concepts.append(rc)
    if rel_concepts:
        field["relatedConcepts"] = rel_concepts

    # custom
    custom: dict = {}
    explicit_custom = spec.get("custom_columns", [])
    for col in explicit_custom:
        if col not in row:
            continue
        val = get_val(row, col)
        if val:
            custom[col] = val

    # capture_unmapped_as_custom: send everything else to custom
    if spec.get("capture_unmapped_as_custom"):
        accounted = set(resolved_cols.values()) | set(explicit_custom)
        for col, val in row.items():
            if col in accounted:
                continue
            v = get_val(row, col)
            if v:
                custom[col] = v

    if custom:
        field["custom"] = custom

    return field


VALID_VLMD_TYPES = {"number", "integer", "string", "boolean", "date", "datetime", "time"}

PLACEHOLDER_DESCRIPTIONS = {
    "n/a", "na", "tbd", "see codebook", "see codebook.", "see notes", "see note",
    "no description", "none", "missing", "unknown", "placeholder", "todo", "fill in",
    "to be determined", "not available", "not applicable",
}


def flag_field(field: dict) -> list[str]:
    issues = []

    desc = field.get("description", "").strip()
    if not desc:
        issues.append("missing_description")
    else:
        if desc.lower().rstrip(".").strip() in PLACEHOLDER_DESCRIPTIONS:
            issues.append("description_too_short")

    ftype = field.get("type", "")
    if not ftype:
        issues.append("missing_type")
    elif ftype not in VALID_VLMD_TYPES:
        issues.append("type_not_in_schema")

    enum_vals = (field.get("constraints") or {}).get("enum", [])
    enum_labels = field.get("enumLabels") or {}
    if enum_vals and not enum_labels:
        issues.append("enum_without_labels")

    return issues


# ── Column resolution (pre-compute once per file) ────────────────────────────

def resolve_all_columns(spec: dict, df_columns: set[str]) -> dict:
    """Resolve all column specs from the format YAML to actual column names."""
    r: dict[str, str | None] = {}
    r["name_column"] = resolve_column_spec(spec.get("name_column"), df_columns)
    r["description_column"] = resolve_column_spec(spec.get("description_column"), df_columns)
    r["title_column"] = resolve_column_spec(spec.get("title_column"), df_columns)
    r["type_mapping_column"] = resolve_column_spec(
        spec.get("type_mapping", {}).get("source_column"), df_columns
    )
    r["enum_ordered_column"] = resolve_column_spec(
        (spec.get("enum_ordered") or {}).get("source_column"), df_columns
    )
    r["section_primary_column"] = resolve_column_spec(
        (spec.get("section") or {}).get("primary_column"), df_columns
    )
    r["section_fallback_column"] = resolve_column_spec(
        (spec.get("section") or {}).get("fallback_column"), df_columns
    )
    r["levels_column"] = resolve_column_spec(
        (spec.get("levels") or {}).get("source_column"), df_columns
    )
    return r


# ── Main convert function ─────────────────────────────────────────────────────

def convert(input_path: str, format_yaml: str,
            output_fields: str, output_lint: str) -> int:
    spec = yaml.safe_load(Path(format_yaml).read_text(encoding="utf-8"))
    format_name = spec.get("format_name", Path(format_yaml).stem)
    print(f"Format: {format_name}", flush=True)

    # Read input
    reader = spec.get("input_reader", "csv")
    if reader == "stata":
        df = read_stata(input_path)
    else:
        encoding = _detect_encoding(input_path)
        df = pd.read_csv(input_path, dtype=str, keep_default_na=False,
                         low_memory=False, encoding=encoding)

    print(f"Reading {input_path} ...", flush=True)
    print(f"  {len(df):,} rows, {len(df.columns)} columns", flush=True)

    # Pre-resolve column names
    df_cols = set(df.columns)
    resolved = resolve_all_columns(spec, df_cols)

    if not resolved.get("name_column"):
        print(f"ERROR: could not find a name column in {list(df.columns)}", file=sys.stderr)
        return 1

    print(f"  Column mapping: name={resolved['name_column']!r}, "
          f"description={resolved['description_column']!r}, "
          f"type={resolved['type_mapping_column']!r}, "
          f"section={resolved['section_primary_column']!r}", flush=True)

    fields = []
    lint_records = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        field = row_to_vlmd_field(row_dict, spec, resolved)
        issues = flag_field(field)
        fields.append(field)
        if issues:
            lint_records.append({
                "name": field["name"],
                "issues": issues,
                "source_row": row_dict,
                "vlmd_field_draft": field,
            })

    Path(output_fields).write_text(
        json.dumps(fields, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    Path(output_lint).write_text(
        json.dumps(lint_records, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    names = [f["name"] for f in fields]
    dupes = len(names) - len(set(names))
    no_name = sum(1 for n in names if not n)

    print(f"  Converted: {len(fields):,} fields", flush=True)
    print(f"  Lint flags: {len(lint_records)}", flush=True)
    if dupes:
        print(f"  WARNING: {dupes} duplicate names", flush=True)

    if no_name:
        print(f"ERROR: {no_name} fields have no name", file=sys.stderr)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--format", required=True, help="Path to format YAML")
    ap.add_argument("--output-fields", default="work/vlmd_converted.json")
    ap.add_argument("--output-lint", default="work/vlmd_lint_report.json")
    args = ap.parse_args()
    sys.exit(convert(args.input, args.format, args.output_fields, args.output_lint))


if __name__ == "__main__":
    main()
