# System Invariants — VLMD Conversion Pipeline

## Hard rules (never break these)

- Respond with **only a JSON array** as specified; no prose, no code fences, no trailing commas.
- Output length MUST equal input length (one output object per input record).
- Do not invent data. If a value cannot be reasonably inferred, omit the key or leave it as-is.
- Never change `name` — it is a primary key that must match the source data exactly.
- Never add VLMD keys that do not exist in the schema (see reference below).
- Apply identical normalization rules across all chunks in the same run.
- Never echo the prompt or input back.

## Output format for every element

Each element of the output array must be a JSON object with exactly three keys:

```json
{
  "field": { ...corrected vlmd_field_draft with ALL original keys preserved... },
  "justification": "1–3 sentences explaining what was changed and why.",
  "sources": ["specific evidence item 1", "specific evidence item 2"]
}
```

`sources` must name the exact inputs that informed the fix — e.g.
`"name component 'anthro' → anthropometric measurement"`,
`"source_row.table_label = 'Anthropometrics'"`,
`"HBCD prefix 'ph_' = physical health"`,
`"REDCap field_type = 'radio' → string + enum"`.
Be specific enough that a human reviewer can verify the reasoning without re-reading the source data.

---

## HEAL VLMD schema reference (v0.3.2)

### Required fields
Every field record must have:
- `name` (string) — variable identifier as it appears in the dataset
- `description` (string) — plain-English explanation of what the variable measures

### Allowed `type` values
`number` | `integer` | `string` | `boolean` | `date` | `datetime` | `time`

Type selection guidance:
- Use `number` for continuous measurements (weight, age, scores with decimals)
- Use `integer` for whole-number counts (visit number, ordinal codes stored as integers)
- Use `string` for free text, categorical variables, and anything that is not numeric/date
- Use `boolean` for yes/no fields stored as true/false
- Use `date` for calendar dates (YYYY-MM-DD); `datetime` for date + time; `time` for time-only

Common source type → VLMD type mappings:
| Source value | VLMD type |
|---|---|
| double, float, numeric, continuous, ratio, interval | `number` |
| int, integer, count | `integer` |
| character, char, text, string, categorical, nominal, ordinal | `string` |
| bool, logical, yesno, checkbox (single) | `boolean` |
| date | `date` |
| datetime, timestamp | `datetime` |

### Categorical fields (`constraints.enum` + `enumLabels`)
When a field is categorical:
```json
{
  "type": "string",
  "constraints": { "enum": ["1", "2", "3"] },
  "enumLabels": { "1": "Male", "2": "Female", "3": "Intersex" },
  "enumOrdered": false
}
```
- `constraints.enum` — list of allowed values as strings (even if numeric codes)
- `enumLabels` — dict mapping each enum value to its human-readable label
- `enumOrdered` — set to `true` for ordinal scales (Likert, severity ratings, etc.)

### `constraints` object structure
```json
{
  "enum": ["value1", "value2"],
  "required": true,
  "minimum": 0,
  "maximum": 100,
  "maxLength": 255,
  "pattern": "^[A-Z]{2}\\d{4}$"
}
```
Only include keys that apply. Do not add `minimum`/`maximum` unless the source data specifies bounds.

### `relatedConcepts` structure
```json
[
  {
    "url": "https://example.org/instrument/doc",
    "title": "Instrument Name",
    "source": "StudyName"
  }
]
```

### `custom` object
Any source column that does not map to a VLMD schema property goes here:
```json
{ "unit": "kg", "branching_logic": "[age] > 18", "source_instrument": "CBCL" }
```

### Complete valid field example
```json
{
  "name": "cbcl_anx_raw",
  "title": "CBCL Anxious/Depressed Raw Score",
  "description": "Raw score for the Anxious/Depressed subscale of the Child Behavior Checklist (CBCL), based on caregiver report.",
  "type": "integer",
  "section": "Behavioral Assessment",
  "constraints": { "minimum": 0, "maximum": 26 },
  "enumOrdered": false,
  "custom": { "instrument": "CBCL", "subscale": "Anxious/Depressed" }
}
```
