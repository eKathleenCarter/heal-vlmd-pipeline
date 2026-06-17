"""Send lint-flagged fields to LLM for fixup.

Reads prompt paths from the format YAML so each format can have its own
context-specific fixup instructions. Falls back to generic_fixup_prompt.md.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import tiktoken
import yaml

from llm_client import DEFAULT_MODEL, MODELS, call_llm, parse_json_response

MAX_ROWS_PER_CHUNK = 30
MAX_RETRIES = 2
ENCODING = tiktoken.get_encoding("cl100k_base")
PROMPTS_DIR = Path(__file__).parent / "prompts"


def count_tokens(text: str) -> int:
    return len(ENCODING.encode(text))


def load_prompts_from_spec(format_yaml: str | None) -> tuple[str, str]:
    """Load system + user prompts, preferring paths from format YAML."""
    defaults = {
        "system": PROMPTS_DIR / "system_invariants_vlmd.md",
        "user": PROMPTS_DIR / "generic_fixup_prompt.md",
    }

    if format_yaml and Path(format_yaml).exists():
        spec = yaml.safe_load(Path(format_yaml).read_text(encoding="utf-8"))
        base = Path(format_yaml).parent.parent  # heal-vlmd-pipeline/
        fp = spec.get("fixup_prompt")
        sp = spec.get("system_invariants_prompt")
        if fp:
            defaults["user"] = base / fp
        if sp:
            defaults["system"] = base / sp

    return (
        defaults["system"].read_text(encoding="utf-8").strip(),
        defaults["user"].read_text(encoding="utf-8").strip(),
    )


def process_chunk(system: str, base_prompt: str, chunk: list,
                  model_key: str, attempt: int = 0) -> list:
    user_msg = base_prompt + "\n\nFields to fix:\n" + json.dumps(chunk, indent=2, ensure_ascii=False)
    raw, ok, err = call_llm(system, user_msg, model_key=model_key, max_tokens=4096)

    if not ok:
        raise RuntimeError(f"LLM call failed: {err}")

    try:
        parsed = parse_json_response(raw)
    except (json.JSONDecodeError, ValueError) as e:
        if attempt < MAX_RETRIES:
            print(f"  JSON parse error (attempt {attempt + 1}): {e} — retrying", flush=True)
            retry_msg = (
                user_msg
                + "\n\nIMPORTANT: Previous response could not be parsed. "
                "Return ONLY a valid JSON array, no prose or code fences."
            )
            raw2, ok2, err2 = call_llm(system, retry_msg, model_key=model_key, max_tokens=4096)
            if not ok2:
                raise RuntimeError(f"LLM retry failed: {err2}")
            parsed = parse_json_response(raw2)
        else:
            raise RuntimeError(f"JSON parse failed after {MAX_RETRIES} retries: {e}")

    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")
    return parsed


def fixup(lint_path: str, output_path: str, checkpoint_path: str,
          format_yaml: str | None, model_key: str) -> int:
    lint_records = json.loads(Path(lint_path).read_text(encoding="utf-8"))
    if not lint_records:
        print("No lint records to fix.", flush=True)
        Path(output_path).write_text("[]", encoding="utf-8")
        return 0

    items_for_llm = [
        {
            "name": rec["name"],
            "issues": rec["issues"],
            "source_row": {k: v for k, v in (rec.get("source_row") or rec.get("hbcd_row", {})).items()
                           if k in ["description", "instruction", "table_label", "domain",
                                    "sub_domain", "source", "type_level", "type_data",
                                    "Field Label", "Form Name", "Field Type", "Section Header"]},
            "vlmd_field_draft": rec["vlmd_field_draft"],
        }
        for rec in lint_records
    ]

    print(f"Fixing {len(items_for_llm)} flagged fields with model {model_key!r} ...", flush=True)
    system, base_prompt = load_prompts_from_spec(format_yaml)

    # Load checkpoint
    checkpoint = {}
    if Path(checkpoint_path).exists():
        try:
            checkpoint = json.loads(Path(checkpoint_path).read_text(encoding="utf-8"))
            print(f"  Resuming from checkpoint ({len(checkpoint)} chunks done)", flush=True)
        except Exception:
            checkpoint = {}

    chunks = [items_for_llm[i: i + MAX_ROWS_PER_CHUNK]
               for i in range(0, len(items_for_llm), MAX_ROWS_PER_CHUNK)]

    all_fixed = []
    for i, chunk in enumerate(chunks):
        chunk_key = str(i)
        if chunk_key in checkpoint:
            print(f"  Chunk {i + 1}/{len(chunks)}: skipped (checkpoint)", flush=True)
            all_fixed.extend(checkpoint[chunk_key])
            continue

        print(f"  Chunk {i + 1}/{len(chunks)}: {len(chunk)} records ...", end=" ", flush=True)
        t0 = time.time()
        try:
            fixed = process_chunk(system, base_prompt, chunk, model_key)
        except Exception as e:
            print(f"\nERROR in chunk {i}: {e}", file=sys.stderr)
            return 1
        print(f"done ({time.time() - t0:.1f}s)", flush=True)

        checkpoint[chunk_key] = fixed
        Path(checkpoint_path).write_text(
            json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        all_fixed.extend(fixed)

    Path(output_path).write_text(
        json.dumps(all_fixed, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Fixed fields → {output_path}", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lint", default="work/vlmd_lint_report.json")
    ap.add_argument("--output", default="work/vlmd_llm_fixes.json")
    ap.add_argument("--checkpoint", default="work/vlmd_llm_fixes.checkpoint.json")
    ap.add_argument("--format", default=None, help="Format YAML path (for prompt selection)")
    ap.add_argument("--model", default=DEFAULT_MODEL, choices=list(MODELS))
    args = ap.parse_args()
    sys.exit(fixup(args.lint, args.output, args.checkpoint, args.format, args.model))


if __name__ == "__main__":
    main()
