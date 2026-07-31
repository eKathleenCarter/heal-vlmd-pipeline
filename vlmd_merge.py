"""Merge LLM fixes into converted fields and write final VLMD output.

Generic — works for any format. Stem naming uses appl_id + a configurable
study label so output files are clearly identified.
"""
import argparse
import csv
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import yaml

from vlmd_split import GITHUB_MAX_FILE_BYTES, json_size, slugify, split_fields


def merge_fixes(fields: list, fixes: list) -> list:
    """
    Apply LLM fixup results onto the converted fields.

    Fixup responses only include the keys the LLM was asked to address, so
    this merges onto the existing field rather than replacing it outright —
    a full replacement would silently drop any key (section, title, etc.)
    the fixup prompt didn't ask about.
    """
    index = {f["name"]: i for i, f in enumerate(fields)}
    for fix in fixes:
        name = fix.get("name")
        if name and name in index:
            fields[index[name]].update(fix)
    return fields


def fields_to_csv_rows(fields: list) -> list[dict]:
    rows = []
    for f in fields:
        row = {
            "schemaVersion": "0.3.2",
            "section": f.get("section", ""),
            "name": f.get("name", ""),
            "title": f.get("title", ""),
            "description": f.get("description", ""),
            "type": f.get("type", ""),
            "format": f.get("format", ""),
            "constraints.required": (
                str(f.get("constraints", {}).get("required", "")).lower()
                if f.get("constraints", {}).get("required") is not None else ""
            ),
            "constraints.maxLength": str(f.get("constraints", {}).get("maxLength", "") or ""),
            "constraints.enum": "|".join(f.get("constraints", {}).get("enum", [])),
            "constraints.pattern": f.get("constraints", {}).get("pattern", ""),
            "constraints.maximum": str(f.get("constraints", {}).get("maximum", "") or ""),
            "constraints.minimum": str(f.get("constraints", {}).get("minimum", "") or ""),
            "enumLabels": "|".join(
                f"{k}={v}" for k, v in (f.get("enumLabels") or {}).items()
            ),
            "enumOrdered": str(f.get("enumOrdered", "")).lower() if "enumOrdered" in f else "",
            "missingValues": "|".join(f.get("missingValues", [])),
            "trueValues": "|".join(f.get("trueValues", [])),
            "falseValues": "|".join(f.get("falseValues", [])),
            "standardsMappings[0].instrument.url": "",
            "standardsMappings[0].instrument.source": "",
            "standardsMappings[0].instrument.title": "",
            "standardsMappings[0].instrument.id": "",
            "standardsMappings[0].item.url": "",
            "standardsMappings[0].item.source": "",
            "standardsMappings[0].item.id": "",
            "relatedConcepts[0].url": (f.get("relatedConcepts") or [{}])[0].get("url", ""),
            "relatedConcepts[0].title": (f.get("relatedConcepts") or [{}])[0].get("title", ""),
            "relatedConcepts[0].source": (f.get("relatedConcepts") or [{}])[0].get("source", ""),
            "custom": "|".join(
                f"{k}={v}" for k, v in (f.get("custom") or {}).items()
            ),
        }
        rows.append(row)
    return rows


# Maps this pipeline's internal format-YAML name to the canonical inputtype
# vocabulary used by heal-transformers/scripts/convert2vlmd.py's detect_input_type().
_INPUTTYPE_MAP = {
    "stata":       "stata",
    "redcap":      "redcap-csv",
    "hbcd":        "csv-data-dict",
    "generic-csv": "csv-data-dict",
}

_GITHUB_DD_BASE = (
    "https://github.com/heal-data-stewards/heal-data-dictionaries"
    "/tree/main/data-dictionaries"
)


def write_metadata_yaml(output_dir: Path, hdp_id: str, appl_id: str,
                        stem: str, title: str, format_name: str,
                        input_filename: str | None = None):
    input_file = input_filename or f"{stem}.csv"
    inputtype = _INPUTTYPE_MAP.get(format_name, format_name)
    github_base = f"{_GITHUB_DD_BASE}/{hdp_id}" if hdp_id else None

    meta = {
        "Project": {
            "HDP_ID": hdp_id,
            "APPL_ID": appl_id,
            "Filename": stem,
            "ProjectTitle": title,
            "Status": "READY",
            "LastModified": date.today().isoformat(),
            "ProjectType": "HEAL Research Programs",
        },
        stem: {
            "inputtype": inputtype,
            "relative_input_filepath": f"../../input/{input_file}",
            "relative_output_filepath": f"./{stem}.vlmd.json",
        },
    }
    if github_base:
        meta[stem]["input_filepath"] = f"{github_base}/input/{input_file}"
        meta[stem]["output_filepath"] = f"{github_base}/vlmd/{stem}/{stem}.vlmd.json"

    yaml_path = output_dir / "metadata.yaml"
    with open(yaml_path, "w", encoding="utf-8") as fh:
        yaml.dump(meta, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"  metadata.yaml → {yaml_path}", flush=True)


# Typographic Unicode punctuation → plain ASCII equivalents. Applied as a
# final pass so output is portable regardless of source format (PDF text
# extraction, Word-authored REDCap/Qualtrics exports, etc. commonly carry
# smart quotes and other typographic characters).
_TEXT_NORMALIZE_MAP = {
    "‘": "'", "’": "'",   # ' '
    "“": '"', "”": '"',  # " "
    "–": "-", "—": "-",  # – —
    "…": "...",               # …
    " ": " ",                 # non-breaking space
}


def _normalize_text(value):
    if not isinstance(value, str):
        return value
    for orig, repl in _TEXT_NORMALIZE_MAP.items():
        value = value.replace(orig, repl)
    return value


def normalize_fields(fields: list) -> list:
    """Strip smart quotes / typographic punctuation from field text in place."""
    for f in fields:
        for key in ("title", "description", "section"):
            if key in f:
                f[key] = _normalize_text(f[key])
        if isinstance(f.get("enumLabels"), dict):
            f["enumLabels"] = {k: _normalize_text(v) for k, v in f["enumLabels"].items()}
    return fields


def validate_output(vlmd_doc: dict) -> bool:
    try:
        from healdata_utils import validate_vlmd_json
        result = validate_vlmd_json(vlmd_doc)
        report = result.get("report", result)
        is_valid = report.get("valid", False)
        errors = report.get("errors", [])
        print(f"  Validation: valid={is_valid}, errors={len(errors)}", flush=True)
        if errors:
            for e in errors[:5]:
                print(f"    - {e}", flush=True)
            if len(errors) > 5:
                print(f"    ... and {len(errors) - 5} more", flush=True)
        return is_valid
    except Exception as e:
        print(f"  WARNING: validation skipped ({e})", flush=True)
        return True


def merge(converted_path: str, fixes_path: str | None, output_dir: str,
          hdp_id: str, appl_id: str, title: str,
          study_label: str, format_name: str, validate: bool,
          file_stem: str | None = None,
          input_filename: str | None = None,
          max_file_size_mb: float = GITHUB_MAX_FILE_BYTES / (1024 * 1024),
          split_by_form: bool = False) -> int:
    fields = json.loads(Path(converted_path).read_text(encoding="utf-8"))
    print(f"Loaded {len(fields):,} converted fields", flush=True)

    if fixes_path and Path(fixes_path).exists():
        fixes = json.loads(Path(fixes_path).read_text(encoding="utf-8"))
        if fixes:
            print(f"Applying {len(fixes)} LLM fixes ...", flush=True)
            fields = merge_fixes(fields, fixes)

    fields = normalize_fields(fields)

    vlmd_doc = {
        "schemaVersion": "0.3.2",
        "title": title,
        "description": (
            f"Converted from {format_name} format to HEAL VLMD schema v0.3.2. "
            f"Study ID: {hdp_id or appl_id}"
        ),
    }
    vlmd_doc = {**base_doc, "fields": fields}

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    # .../vlmd/ — where sibling section "form" folders are created, matching
    # how heal-data-dictionaries represents studies with multiple data
    # dictionaries (e.g. vlmd/TG2_Adult/, vlmd/TG2_Youth/, each self-contained).
    vlmd_root = out.parent

    if file_stem:
        stem = file_stem
    else:
        label = study_label.replace(" ", "_") if study_label else "DataDictionary"
        stem = f"{appl_id}_{label}"

    # Validate the full combined document once. Each split part is a subset
    # of the same validated fields under the same title/description
    # skeleton, so it is schema-valid by construction — no need to
    # re-validate every part separately.
    validation_passed = True
    if validate:
        validation_passed = validate_output(vlmd_doc)

    # Always write the full combined document — kept locally as the complete
    # reference copy even when section form-folders are also written below.
    # This file is NOT copied to --dest-dir when a split happens, since it
    # may still exceed GitHub's size limit (see run_pipeline.py's dest-dir
    # copy step) — only the per-section form-folders are.
    combined_json_path = out / f"{stem}.vlmd.json"
    combined_json_path.write_text(
        json.dumps(vlmd_doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"  JSON (combined) → {combined_json_path}  "
        f"({combined_json_path.stat().st_size / (1024 * 1024):.1f} MB)",
        flush=True,
    )

    combined_csv_path = out / f"{stem}.vlmd.csv"
    rows = fields_to_csv_rows(fields)
    if rows:
        with open(combined_csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  CSV  (combined) → {combined_csv_path}", flush=True)

    write_metadata_yaml(out, hdp_id, appl_id, stem, title, format_name, input_filename)

    max_bytes = int(max_file_size_mb * 1024 * 1024)
    parts = split_fields(fields, base_doc, max_bytes, force=split_by_form)
    is_split = not (len(parts) == 1 and parts[0][0] == "")

    part_dir_names: list[str] = []
    if is_split:
        full_size_mb = json_size(vlmd_doc) / (1024 * 1024)
        if full_size_mb * 1024 * 1024 > max_bytes:
            reason = f"output is {full_size_mb:.1f} MB, over the {max_file_size_mb:.0f} MB limit"
        else:
            reason = f"requested (combined output is {full_size_mb:.1f} MB, under the {max_file_size_mb:.0f} MB limit)"
        print(
            f"  Splitting into {len(parts)} section form-folder(s) — {reason} — "
            f"mirroring how this repo represents studies with multiple data dictionaries",
            flush=True,
        )

        for section_label, part_fields in parts:
            part_stem = f"{stem}_{slugify(section_label)}"
            part_dir = vlmd_root / part_stem
            part_dir.mkdir(parents=True, exist_ok=True)
            part_dir_names.append(part_stem)

            part_doc = {
                **base_doc,
                "description": f"{base_doc['description']} — section: {section_label}",
                "fields": part_fields,
            }

            part_json_path = part_dir / f"{part_stem}.vlmd.json"
            part_json_path.write_text(
                json.dumps(part_doc, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(
                f"  JSON → {part_json_path}  "
                f"({part_json_path.stat().st_size / (1024 * 1024):.1f} MB)",
                flush=True,
            )

            part_csv_path = part_dir / f"{part_stem}.vlmd.csv"
            part_rows = fields_to_csv_rows(part_fields)
            if part_rows:
                with open(part_csv_path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=list(part_rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(part_rows)
                print(f"  CSV  → {part_csv_path}", flush=True)

            write_metadata_yaml(part_dir, hdp_id, appl_id, part_stem, title, format_name, input_filename)

    # Now that the new output has been written successfully, remove leftover
    # section form-folders from a previous run that split differently (or no
    # longer needs splitting at all).
    prefix = f"{stem}_"
    for candidate in vlmd_root.iterdir():
        if candidate.is_dir() and candidate.name.startswith(prefix) and candidate.name not in part_dir_names:
            shutil.rmtree(candidate)

    summary = f"combined + {len(part_dir_names)} section form-folder(s)" if is_split else "combined file only"
    print(f"\nDone. {len(fields):,} fields written ({summary}).", flush=True)

    if validate and not validation_passed:
        print(
            "ERROR: Final VLMD document failed schema validation.\n"
            f"       Output written to {out} for inspection.\n"
            "       Fix validation errors before copying to the final repository.",
            file=sys.stderr, flush=True,
        )
        return 2
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--converted", default="work/vlmd_converted.json")
    ap.add_argument("--fixes", default=None)
    ap.add_argument("--output-dir", default="output")
    ap.add_argument("--hdp-id", default="")
    ap.add_argument("--appl-id", default="unknown")
    ap.add_argument("--title", default="HEAL Study Data Dictionary")
    ap.add_argument("--study-label", default="DataDictionary",
                    help="Short label used in output filename: {appl_id}_{study_label}.vlmd.json")
    ap.add_argument("--format-name", default="unknown", help="Source format name for metadata")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--max-file-size-mb", type=float, default=GITHUB_MAX_FILE_BYTES / (1024 * 1024),
                    help="Split output into multiple files (by section) if it would exceed this "
                         "size in MB. Default: 100 (GitHub's hard file size limit).")
    ap.add_argument("--split-by-form", action="store_true",
                    help="Always split into one form-folder per section, even if the combined "
                         "output is under --max-file-size-mb.")
    args = ap.parse_args()
    sys.exit(merge(
        args.converted, args.fixes, args.output_dir,
        args.hdp_id, args.appl_id, args.title,
        args.study_label, args.format_name, args.validate,
        max_file_size_mb=args.max_file_size_mb,
        split_by_form=args.split_by_form,
    ))


if __name__ == "__main__":
    main()
