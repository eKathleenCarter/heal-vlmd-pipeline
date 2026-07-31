"""Split an oversized VLMD document into GitHub-size-safe parts, form-style.

GitHub rejects any file over 100MB. A pretty-printed VLMD JSON document for a
large study (tens of thousands of fields) can exceed that. Rather than invent
a new convention, this mirrors how heal-data-dictionaries already represents
studies with multiple data dictionaries: several independent form folders
under vlmd/, one per source instrument (e.g. TG2_Adult/, TG2_Youth/, each
with its own vlmd.json + vlmd.csv + metadata.yaml).

Here, each VLMD `section` (instrument/form/domain) plays the same role: one
section becomes one form-style output, kept under the byte limit. A section
is only broken up further (field-by-field) in the rare case that it alone
exceeds the limit.
"""
import json
import re
import sys

GITHUB_MAX_FILE_BYTES = 100 * 1024 * 1024  # GitHub hard limit — pushes of larger files are rejected


def json_size(doc: dict) -> int:
    """Size in bytes of `doc` serialized the same way merge() writes VLMD JSON."""
    return len(json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8"))


def slugify(label: str) -> str:
    """Filesystem-safe folder/file name segment for a section label."""
    slug = re.sub(r"[^\w]+", "_", label.strip())
    return slug.strip("_") or "Uncategorized"


def _group_by_section(fields: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group fields by `section`, preserving the order sections first appear in."""
    order = []
    groups: dict[str, list[dict]] = {}
    for f in fields:
        section = f.get("section") or "Uncategorized"
        if section not in groups:
            groups[section] = []
            order.append(section)
        groups[section].append(f)
    return [(s, groups[s]) for s in order]


def _split_oversized_group(
    label: str, group_fields: list[dict], base_doc: dict, max_bytes: int
) -> list[tuple[str, list[dict]]]:
    """Field-by-field packing fallback for a single section too big to fit alone."""
    chunks: list[list[dict]] = []
    current: list[dict] = []
    for field in group_fields:
        candidate = current + [field]
        if current and json_size({**base_doc, "fields": candidate}) > max_bytes:
            chunks.append(current)
            current = [field]
        else:
            current = candidate
    if current:
        chunks.append(current)

    if len(chunks) == 1:
        return [(label, chunks[0])]
    return [(f"{label}_{i}", chunk) for i, chunk in enumerate(chunks, start=1)]


def split_fields(
    fields: list[dict], base_doc: dict, max_bytes: int = GITHUB_MAX_FILE_BYTES,
    force: bool = False,
) -> list[tuple[str, list[dict]]]:
    """Partition `fields` into (section_label, fields) parts, one per section.

    `base_doc` is the VLMD document without `fields` (schemaVersion/title/
    description) — used to account for the fixed overhead of each part.
    Returns a single `("", fields)` entry (fields unmodified) when the full
    document already fits under `max_bytes` and `force` is False — no split
    needed. `force=True` splits by section regardless of size (used when the
    user opts into per-form output for a multi-section dictionary that isn't
    actually oversized).
    """
    if not force and json_size({**base_doc, "fields": fields}) <= max_bytes:
        return [("", fields)]

    parts: list[tuple[str, list[dict]]] = []
    for section, group_fields in _group_by_section(fields):
        group_size = json_size({**base_doc, "fields": group_fields})
        if group_size > max_bytes:
            parts.extend(_split_oversized_group(section, group_fields, base_doc, max_bytes))
        else:
            parts.append((section, group_fields))
    return parts


def section_counts(fields: list[dict]) -> dict[str, int]:
    """Count fields per `section`, preserving the order sections first appear in."""
    counts: dict[str, int] = {}
    for f in fields:
        section = f.get("section") or "Uncategorized"
        counts[section] = counts.get(section, 0) + 1
    return counts


def confirm_form_split(section_labels: list[str], mode: str = "ask", yes: bool = False) -> bool:
    """Decide whether to split a multi-section document into one form per section.

    `mode`: "yes" always splits, "no" never splits by form (size-based
    splitting can still kick in separately as a safety net), "ask" prompts
    interactively — unless `yes` is set (non-interactive/scripted run via
    --yes), in which case it defaults to not splitting and prints a note
    about --split-by-form.
    """
    if mode == "yes":
        return True
    if mode == "no":
        return False

    # mode == "ask"
    if yes:
        print(
            "  NOTE: multiple forms/sections detected but running non-interactively "
            "(--yes) — keeping them combined. Pass --split-by-form yes to split "
            "automatically in scripted runs.",
            flush=True,
        )
        return False

    preview = ", ".join(section_labels[:6])
    if len(section_labels) > 6:
        preview += f", ... ({len(section_labels)} total)"
    print(
        f"\n  Detected {len(section_labels)} forms/sections in this data dictionary: {preview}",
        flush=True,
    )
    try:
        answer = input(
            "  Create a separate VLMD + metadata.yaml for each form, or combine into "
            "one? [combine/split] (default: combine): "
        ).strip().lower()
        return answer in ("split", "s", "separate", "forms", "yes", "y")
    except (EOFError, KeyboardInterrupt):
        print(
            "\n  Non-interactive session detected. Pass --split-by-form yes/no to skip "
            "this prompt.",
            file=sys.stderr, flush=True,
        )
        return False
