# PDF Data Dictionary Extraction Prompt

You are extracting variable/field definitions from pages of a PDF data dictionary codebook.

## Your task

Parse the raw table rows extracted from PDF pages and identify individual variable records.
Each variable record has:

- **name** — short identifier (usually ALL_CAPS or mixed-case, e.g. `PAINDUR`, `BMH03`, `PANAS1`)
- **label** — the question text or variable description
- **choices** — response options for categorical variables, pipe-separated: `value, Label | value, Label`
  - e.g. `1, Yes | 0, No | 2, Does not apply`
  - Leave blank for free-text or numeric entry fields
- **section** — the section/instrument/domain this variable belongs to (carry forward from section headers)

## Input format

You will receive raw table rows extracted from PDF pages, as a JSON array of arrays.
Each element is a page; each page contains rows from all tables on that page.
Cells may contain `\n` for line breaks, `null` for empty cells.

Example input rows:
```json
[
  ["", "PAINDUR", "How long have you had this type of pain?", "[###]", null, null, "", null],
  ["BPLWSUIT", "Are you involved in a lawsuit related to your back problem?", "1: Yes\n0: No\n2: Does not apply", null, null, ""],
  ["", "Baseline Demographics (Part of the Minimal Dataset)", null, null, null, null, null, ""],
  ["EDLEVEL", "What is the highest level of education you have completed?", "1: Primary\n2: Some high school\n3: High school grad\n4: Some college\n5: College grad\n6: Post-graduate", "", null, ""]
]
```

## Rules

1. **Identify variable rows**: a variable row has a short identifier (2–15 chars, often ALL_CAPS) as one of
   the first two non-empty cells. Section headers, blank rows, and continuation rows are NOT variables.

2. **Section headers**: rows where the main content is a long descriptive phrase with no short identifier
   are section headers. Carry the section name forward until the next header.

3. **Continuation rows**: when choices overflow onto the next row (the name cell is blank), append
   those choices to the previous variable's choices rather than creating a new record.

4. **Choices format**: convert `N: Label\nM: Label` or `N: Label` to pipe-separated `N, Label | M, Label`.
   Strip trailing colons, normalize whitespace. If choices look like `[###]` or `[open text]`, the
   field is free text — leave choices blank.

5. **Section carry-forward**: once you identify a section header, all subsequent variables belong to
   that section until a new header appears.

6. **Deduplication**: each variable `name` should appear only once. If you see the same name twice,
   merge the records (combine choices from both).

## Output format

Return a JSON array of objects — one per variable found in the input:

```json
[
  {
    "name": "PAINDUR",
    "label": "How long have you had the type of pain for which you are enrolled in this study?",
    "choices": "",
    "section": "Baseline Demographics"
  },
  {
    "name": "BPLWSUIT",
    "label": "Are you involved in a lawsuit or legal claim related to your back problem?",
    "choices": "1, Yes | 0, No | 2, Does not apply",
    "section": "Baseline Demographics"
  }
]
```

Return ONLY the JSON array — no prose, no code fences.
