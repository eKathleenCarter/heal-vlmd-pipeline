"""VLMD conversion pipeline — single entry point.

Orchestrates detect → convert → validate → fixup → merge by calling each
module's functions directly (no subprocesses).

Usage:
    python run_pipeline.py --input FILE --hdp-id HDP01258 [OPTIONS]

See README.md or --help for full option list.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

PIPELINE_DIR = Path(__file__).parent
WORK_DIR = PIPELINE_DIR / "work"
OUTPUT_DIR = PIPELINE_DIR / "output"


def _banner(text: str):
    print(f"\n=== {text} ===", flush=True)


def _derive_name(input_file: str) -> str:
    """Derive a clean file stem from the input path (spaces → underscores)."""
    return re.sub(r"[\s]+", "_", Path(input_file).stem)


def run(
    input_file: str,
    format_yaml: str | None,
    appl_id: str,
    hdp_id: str,
    title: str,
    study_label: str,
    name: str | None = None,
    model: str = "azure-gpt-4.1-mini",
    skip_llm: bool = False,
    no_detect: bool = False,
    output_dir: Path = OUTPUT_DIR,
    yes: bool = False,
    dest_dir: Path | None = None,
    max_file_size_mb: float = 100,
    split_by_form: str = "ask",
) -> int:
    # ── Derive file stem ──────────────────────────────────────────────────────
    file_name = name or _derive_name(input_file)
    file_stem = f"{hdp_id}_{file_name}" if hdp_id else file_name

    # Per-run subdirectories
    run_key = hdp_id if hdp_id else "scratch"
    work_subdir = WORK_DIR / run_key
    work_subdir.mkdir(parents=True, exist_ok=True)

    vlmd_out = output_dir / "vlmd" / file_stem
    vlmd_out.mkdir(parents=True, exist_ok=True)

    input_copy_dir = output_dir / "input"
    input_copy_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 0: HEAL platform lookup ─────────────────────────────────────────
    if hdp_id:
        _banner("Step 0: HEAL platform lookup")
        from vlmd_lookup import lookup, confirm_study

        resolved_appl_id, study_info = lookup(hdp_id, appl_id if appl_id != "unknown" else None)

        if resolved_appl_id:
            appl_id = resolved_appl_id
            if title == "HEAL Study Data Dictionary" and study_info.get("study_name"):
                title = study_info["study_name"]

        if study_info and not confirm_study(yes=yes):
            print("  Aborted.", flush=True)
            return 1

    print("=" * 44, flush=True)
    print(" VLMD Conversion Pipeline", flush=True)
    print(f" Input:  {input_file}", flush=True)
    print(f" Appl:   {appl_id}  HDP: {hdp_id or 'n/a'}", flush=True)
    print(f" Stem:   {file_stem}", flush=True)
    print(f" Model:  {model}", flush=True)
    print("=" * 44, flush=True)

    # ── Step 1: Format detection ──────────────────────────────────────────────
    if not no_detect and not format_yaml:
        _banner("Step 1: Format detection")
        from vlmd_detect import detect, format_detection_message

        detection = detect(
            input_file,
            formats_dir=str(PIPELINE_DIR / "formats"),
            model_key=model,
            llm_fallback=True,
        )

        detection_path = work_subdir / "vlmd_detection.json"
        detection_path.write_text(
            json.dumps(
                {k: v for k, v in detection.items() if k != "sample_rows"},
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if detection["format_name"] is None:
            print(format_detection_message(detection), flush=True)
            print(
                f"\n  Detection result saved to {detection_path}\n"
                f"  Run vlmd_interview.py to save a mapping, then re-run with:\n"
                f"    python run_pipeline.py --input '{input_file}' "
                f"--format formats/{appl_id}.yaml --no-detect ...",
                flush=True,
            )
            return 1

        format_yaml = detection["format_yaml_path"]
        print(f"  Using format: {format_yaml}", flush=True)

    elif not format_yaml:
        print("ERROR: --format is required when --no-detect is set", file=sys.stderr)
        return 1

    format_name = yaml.safe_load(Path(format_yaml).read_text(encoding="utf-8")).get(
        "format_name", Path(format_yaml).stem
    )

    # ── Step 2: Convert ───────────────────────────────────────────────────────
    _banner(f"Step 2: Convert  (format: {format_name})")
    from vlmd_convert import convert

    converted_path = str(work_subdir / "vlmd_converted.json")
    convert_lint_path = str(work_subdir / "vlmd_lint_report.json")

    rc = convert(input_file, format_yaml, converted_path, convert_lint_path)
    if rc != 0:
        return rc

    # Load and report converter lint flags
    convert_lint_records = json.loads(Path(convert_lint_path).read_text(encoding="utf-8"))
    if convert_lint_records:
        print(f"\n  {len(convert_lint_records)} field(s) flagged for LLM review:", flush=True)
        for rec in convert_lint_records[:10]:
            issues_str = ", ".join(rec["issues"])
            print(f"    [{rec['name']}]  issues: {issues_str}", flush=True)
        if len(convert_lint_records) > 10:
            print(f"    ... and {len(convert_lint_records) - 10} more (see {convert_lint_path})", flush=True)

    # ── Step 3: Validate ──────────────────────────────────────────────────────
    _banner("Step 3: Validate")
    from vlmd_lint import lint

    validation_report_path = str(work_subdir / "vlmd_validation_report.json")
    lint_exit = lint(converted_path, validation_report_path, title)

    # ── Step 4: LLM fixup ─────────────────────────────────────────────────────
    # Run if converter flagged any fields OR schema validation found errors
    needs_fixup = (lint_exit != 0 or bool(convert_lint_records))
    fixes_path = None
    cleanup_log_path = str(work_subdir / "vlmd_llm_cleanup.json")

    if needs_fixup and not skip_llm:
        _banner(f"Step 4: LLM fixup  (model: {model})")
        from vlmd_fixup import fixup

        fixes_path = str(work_subdir / "vlmd_llm_fixes.json")
        checkpoint_path = str(work_subdir / "vlmd_llm_fixes.checkpoint.json")

        if convert_lint_records and lint_exit == 0:
            print(
                f"  Note: schema validation passed but {len(convert_lint_records)} "
                "converter flag(s) need LLM attention.",
                flush=True,
            )

        rc = fixup(
            convert_lint_path,
            fixes_path,
            checkpoint_path,
            format_yaml,
            model,
            cleanup_log_path=cleanup_log_path,
        )
        if rc != 0:
            return rc

    elif needs_fixup and skip_llm:
        print(
            f"  (LLM fixup skipped via --skip-llm; "
            f"{len(convert_lint_records)} flag(s) left unresolved)",
            flush=True,
        )

    # ── Step 5: Merge and write output ────────────────────────────────────────
    _banner("Step 5: Merge and write output")
    from vlmd_merge import merge
    from vlmd_split import confirm_form_split, section_counts

    converted_fields = json.loads(Path(converted_path).read_text(encoding="utf-8"))
    sections = section_counts(converted_fields)
    split_by_form_decision = False
    if len(sections) > 1:
        split_by_form_decision = confirm_form_split(
            list(sections.keys()), mode=split_by_form, yes=yes
        )

    rc = merge(
        converted_path,
        fixes_path,
        str(vlmd_out),
        hdp_id,
        appl_id,
        title,
        study_label,
        format_name,
        validate=True,
        file_stem=file_stem,
        input_filename=Path(input_file).name,
        max_file_size_mb=max_file_size_mb,
        split_by_form=split_by_form_decision,
    )
    if rc != 0:
        return rc

    # ── Copy input file to output/input/ ──────────────────────────────────────
    src_input = Path(input_file)
    if src_input.exists():
        shutil.copy2(src_input, input_copy_dir / src_input.name)
        print(f"  Input  → {input_copy_dir / src_input.name}", flush=True)

    # ── Copy to destination repository (optional) ─────────────────────────────
    if dest_dir and hdp_id:
        dest_hdp = dest_dir / hdp_id
        dest_vlmd_root = dest_hdp / "vlmd"
        dest_input = dest_hdp / "input"

        _banner(f"Copying to {dest_dir}")
        dest_vlmd_root.mkdir(parents=True, exist_ok=True)
        dest_input.mkdir(parents=True, exist_ok=True)

        # Sibling section form-folders written by vlmd_merge.py when the
        # combined output exceeded GitHub's size limit (e.g. HDP01258_.._Demographics/),
        # mirroring how this repo represents studies with multiple data
        # dictionaries (TG2_Adult/, TG2_Youth/, etc).
        vlmd_root = vlmd_out.parent
        split_dirs = sorted(
            d for d in vlmd_root.glob(f"{file_stem}_*") if d.is_dir()
        )

        copied = 0
        if split_dirs:
            # The combined folder (vlmd_out) may still exceed GitHub's size
            # limit, so only the per-section form-folders (each under the
            # limit) are copied to the repo that gets pushed to GitHub. The
            # combined folder stays in output/ locally as the full reference copy.
            print(
                "  NOTE: output was split by section — copying each section's "
                "form-folder; combined folder stays local.",
                flush=True,
            )
            for src_dir in split_dirs:
                dest_dir_path = dest_vlmd_root / src_dir.name
                dest_dir_path.mkdir(parents=True, exist_ok=True)
                for src in src_dir.glob("*"):
                    shutil.copy2(src, dest_dir_path / src.name)
                    print(f"  {src_dir.name}/{src.name} → {dest_dir_path}", flush=True)
                    copied += 1
        else:
            dest_vlmd = dest_vlmd_root / file_stem
            dest_vlmd.mkdir(parents=True, exist_ok=True)
            for pattern in ("*.vlmd.json", "*.vlmd.csv", "metadata.yaml"):
                for src in vlmd_out.glob(pattern):
                    shutil.copy2(src, dest_vlmd / src.name)
                    print(f"  {src.name} → {dest_vlmd}", flush=True)
                    copied += 1

        if src_input.exists():
            shutil.copy2(src_input, dest_input / src_input.name)
            print(f"  {src_input.name} → {dest_input}", flush=True)

        if copied == 0:
            print("  Nothing to copy.", flush=True)

    elif dest_dir and not hdp_id:
        print("  NOTE: --dest-dir skipped (requires --hdp-id).", flush=True)

    print(f"\n{'=' * 44}", flush=True)
    print(f" Done!  Output in: {vlmd_out}", flush=True)
    if Path(cleanup_log_path).exists():
        print(f" LLM log: {cleanup_log_path}", flush=True)
    print(f"{'=' * 44}", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Convert a data dictionary to HEAL VLMD format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard run — APPL_ID and title fetched from HEAL platform
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258

  # Control the output filename prefix
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258 \\
    --name HBCD_datadictionary

  # Copy validated output to a destination repository
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258 \\
    --dest-dir /path/to/heal-data-dictionaries/data-dictionaries

  # Known format, skip detection
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258 \\
    --format formats/hbcd.yaml --name HBCD_datadictionary

  # Non-interactive / scripted use
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258 --yes

  # Skip LLM (deterministic only)
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258 --skip-llm
""",
    )
    ap.add_argument("--input", required=True, help="Path to input data dictionary (CSV or .dta)")
    ap.add_argument("--format", default=None, help="Format YAML path (skips auto-detection)")
    ap.add_argument("--hdp-id", default="",
                    help="HEAL Data Platform project ID (e.g. HDP01258)")
    ap.add_argument("--appl-id", default="unknown",
                    help="NIH award/application number (auto-fetched if --hdp-id provided)")
    ap.add_argument("--title", default="HEAL Study Data Dictionary",
                    help="Study title (auto-fetched if --hdp-id provided)")
    ap.add_argument("--study-label", default="DataDictionary",
                    help="Short label for metadata (legacy)")
    ap.add_argument("--name", default=None,
                    help="Output filename prefix (default: derived from input filename). "
                         "Final stem: {hdp-id}_{name}. "
                         "Example: --name HBCD_datadictionary → HDP01258_HBCD_datadictionary.vlmd.json")
    ap.add_argument("--model", default="azure-gpt-4.1-mini",
                    help="LLM model key (default: azure-gpt-4.1-mini)")
    ap.add_argument("--output-dir", default=str(OUTPUT_DIR),
                    help="Base output directory. Files go to {output-dir}/vlmd/{stem}/ "
                         "and {output-dir}/input/. Default: output/{hdp-id}/")
    ap.add_argument("--skip-llm", action="store_true", help="Skip LLM fixup step")
    ap.add_argument("--no-detect", action="store_true",
                    help="Skip format detection (requires --format)")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Skip study confirmation prompt (for scripted/bot use)")
    ap.add_argument("--dest-dir", default=None,
                    help="Root of destination repository (e.g. heal-data-dictionaries/data-dictionaries). "
                         "Files are copied to {dest-dir}/{hdp-id}/vlmd/{stem}/ and {dest-dir}/{hdp-id}/input/ "
                         "after validation passes.")
    ap.add_argument("--max-file-size-mb", type=float, default=100,
                    help="Split VLMD output into multiple files (by section) if it would exceed "
                         "this size in MB. Default: 100 (GitHub's hard file size limit).")
    ap.add_argument("--split-by-form", choices=("ask", "yes", "no"), default="ask",
                    help="When a data dictionary has multiple sections/forms: 'ask' prompts "
                         "interactively (default; defaults to 'no' under --yes), 'yes' always "
                         "splits into one form-folder per section, 'no' always keeps them "
                         "combined (size-based splitting can still apply as a safety net).")

    args = ap.parse_args()

    # Default output-dir to output/{hdp-id}/ when not explicitly set
    if args.output_dir == str(OUTPUT_DIR) and args.hdp_id:
        output_dir = OUTPUT_DIR / args.hdp_id
    else:
        output_dir = Path(args.output_dir)

    sys.exit(run(
        input_file=args.input,
        format_yaml=args.format,
        appl_id=args.appl_id,
        hdp_id=args.hdp_id,
        title=args.title,
        study_label=args.study_label,
        name=args.name,
        model=args.model,
        skip_llm=args.skip_llm,
        no_detect=args.no_detect,
        output_dir=output_dir,
        yes=args.yes,
        dest_dir=Path(args.dest_dir) if args.dest_dir else None,
        max_file_size_mb=args.max_file_size_mb,
        split_by_form=args.split_by_form,
    ))


if __name__ == "__main__":
    main()
