"""VLMD conversion pipeline — single entry point.

Orchestrates detect → convert → validate → fixup → merge by calling each
module's functions directly (no subprocesses).

Usage:
    python run_pipeline.py --input FILE --hdp-id HDP01258 [OPTIONS]

See README.md or --help for full option list.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

PIPELINE_DIR = Path(__file__).parent
WORK_DIR = PIPELINE_DIR / "work"
OUTPUT_DIR = PIPELINE_DIR / "output"


def _banner(text: str):
    print(f"\n=== {text} ===", flush=True)


def run(
    input_file: str,
    format_yaml: str | None,
    appl_id: str,
    hdp_id: str,
    title: str,
    study_label: str,
    model: str,
    skip_llm: bool,
    no_detect: bool,
    output_dir: Path,
    yes: bool = False,
    dest_dir: Path | None = None,
) -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 0: HEAL platform lookup ─────────────────────────────────────────
    if hdp_id:
        _banner("Step 0: HEAL platform lookup")
        from vlmd_lookup import lookup, confirm_study

        resolved_appl_id, study_info = lookup(hdp_id, appl_id if appl_id != "unknown" else None)

        if resolved_appl_id:
            appl_id = resolved_appl_id
            # Use the study name as the title if one wasn't explicitly provided
            if title == "HEAL Study Data Dictionary" and study_info.get("study_name"):
                title = study_info["study_name"]

        if study_info and not confirm_study(yes=yes):
            print("  Aborted.", flush=True)
            return 1

    print("=" * 44, flush=True)
    print(" VLMD Conversion Pipeline", flush=True)
    print(f" Input:  {input_file}", flush=True)
    print(f" Appl:   {appl_id}  HDP: {hdp_id or 'n/a'}", flush=True)
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

        detection_path = WORK_DIR / "vlmd_detection.json"
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

    converted_path = str(WORK_DIR / "vlmd_converted.json")
    lint_report_path = str(WORK_DIR / "vlmd_lint_report.json")

    rc = convert(input_file, format_yaml, converted_path, lint_report_path)
    if rc != 0:
        return rc

    # ── Step 3: Validate ──────────────────────────────────────────────────────
    _banner("Step 3: Validate")
    from vlmd_lint import lint

    validation_report_path = str(WORK_DIR / "vlmd_validation_report.json")
    lint_exit = lint(converted_path, validation_report_path, title)

    # ── Step 4: LLM fixup ─────────────────────────────────────────────────────
    fixes_path = None
    if lint_exit != 0 and not skip_llm:
        _banner(f"Step 4: LLM fixup  (model: {model})")
        from vlmd_fixup import fixup

        fixes_path = str(WORK_DIR / "vlmd_llm_fixes.json")
        checkpoint_path = str(WORK_DIR / "vlmd_llm_fixes.checkpoint.json")

        rc = fixup(
            lint_report_path,
            fixes_path,
            checkpoint_path,
            format_yaml,
            model,
        )
        if rc != 0:
            return rc

    elif lint_exit != 0 and skip_llm:
        print("  (LLM fixup skipped via --skip-llm)", flush=True)

    # ── Step 5: Merge and write output ────────────────────────────────────────
    _banner("Step 5: Merge and write output")
    from vlmd_merge import merge

    rc = merge(
        converted_path,
        fixes_path,
        str(output_dir),
        hdp_id,
        appl_id,
        title,
        study_label,
        format_name,
        validate=True,
    )
    if rc != 0:
        return rc

    # ── Copy to destination repository (optional) ─────────────────────────────
    if dest_dir and hdp_id and appl_id and appl_id != "unknown":
        final_dir = dest_dir / appl_id / hdp_id / "vlmd"
        _banner(f"Copying to {dest_dir}")
        final_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for pattern in ("*.vlmd.json", "*.vlmd.csv", "metadata.yaml"):
            for src in output_dir.glob(pattern):
                shutil.copy2(src, final_dir / src.name)
                print(f"  {src.name} → {final_dir}", flush=True)
                copied += 1
        if copied == 0:
            print("  Nothing to copy.", flush=True)
    elif dest_dir and (not hdp_id or appl_id == "unknown"):
        print("  NOTE: --dest-dir skipped (requires both --hdp-id and a resolved APPL_ID).",
              flush=True)

    print(f"\n{'=' * 44}", flush=True)
    print(f" Done!  Output in: {output_dir}", flush=True)
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

  # Copy validated output to a destination repository
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258 \\
    --dest-dir /path/to/CleanedDataDictionaries

  # Known format, skip detection
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258 \\
    --format formats/hbcd.yaml --study-label HBCD_DataDictionary

  # Non-interactive / scripted use
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258 --yes

  # Skip LLM (deterministic only)
  python run_pipeline.py --input data_dict.csv --hdp-id HDP01258 --skip-llm
""",
    )
    ap.add_argument("--input", required=True, help="Path to input data dictionary (CSV or .dta)")
    ap.add_argument("--format", default=None, help="Format YAML path (skips auto-detection)")
    ap.add_argument("--hdp-id", default="",
                    help="HEAL Data Platform project ID (e.g. HDP01258) — used to fetch study info")
    ap.add_argument("--appl-id", default="unknown",
                    help="NIH award/application number (auto-fetched from platform if --hdp-id provided)")
    ap.add_argument("--title", default="HEAL Study Data Dictionary",
                    help="Study title (auto-fetched from platform if --hdp-id provided)")
    ap.add_argument("--study-label", default="DataDictionary",
                    help="Short label for output filename: {appl_id}_{label}.vlmd.json")
    ap.add_argument("--model", default="azure-gpt-4.1-mini",
                    help="LLM model key (default: azure-gpt-4.1-mini)")
    ap.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Output directory")
    ap.add_argument("--skip-llm", action="store_true", help="Skip LLM fixup step")
    ap.add_argument("--no-detect", action="store_true",
                    help="Skip format detection (requires --format)")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Skip study confirmation prompt (for scripted/bot use)")
    ap.add_argument("--dest-dir", default=None,
                    help="Root of destination repository; output is copied to "
                         "{dest-dir}/{appl_id}/{hdp_id}/vlmd/ after validation passes")

    args = ap.parse_args()
    sys.exit(run(
        input_file=args.input,
        format_yaml=args.format,
        appl_id=args.appl_id,
        hdp_id=args.hdp_id,
        title=args.title,
        study_label=args.study_label,
        model=args.model,
        skip_llm=args.skip_llm,
        no_detect=args.no_detect,
        output_dir=Path(args.output_dir),
        yes=args.yes,
        dest_dir=Path(args.dest_dir) if args.dest_dir else None,
    ))


if __name__ == "__main__":
    main()
