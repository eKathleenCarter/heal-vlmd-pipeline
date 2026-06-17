# REDCap VLMD Field Fixup

You are fixing VLMD field records converted from a REDCap data dictionary export.
REDCap is a widely used clinical data capture platform. Its export format has specific
column conventions that provide strong contextual signals for fixing VLMD fields.

Each input record contains:
- `name`: the variable name from "Variable / Field Name" (do NOT change)
- `issues`: list of problem codes requiring remediation
- `source_row`: key columns from the original REDCap row
- `vlmd_field_draft`: the partially-converted VLMD field to be corrected

---

## REDCap source column reference

Key columns available in `source_row`:

| REDCap column | What it contains |
|---|---|
| `Field Label` | Human-readable question text — primary source for descriptions |
| `Field Type` | radio, checkbox, text, notes, calc, yesno, truefalse, slider, dropdown, date_*, datetime_* |
| `Form Name` | The CRF/instrument this field belongs to (maps to `section`) |
| `Section Header` | Sub-section within the form |
| `Choices, Calculations, OR Slider Labels` | Pipe-separated choices: `1, Yes \| 2, No` |
| `Field Note` | Supplemental instructions for data entry staff |
| `Text Validation Type OR Show Slider Number` | Validation type: `integer`, `number`, `date_mdy`, `email`, etc. |
| `Text Validation Min` / `Text Validation Max` | Numeric bounds for text fields |
| `Branching Logic (Show field if...)` | Conditional display logic |

### REDCap `Field Type` → VLMD `type` mapping

| REDCap Field Type | VLMD type | Notes |
|---|---|---|
| `text` (no validation) | `string` | |
| `text` + validation `integer` | `integer` | |
| `text` + validation `number` | `number` | |
| `text` + validation `date_*` | `date` | |
| `text` + validation `datetime_*` | `datetime` | |
| `notes` | `string` | Long free-text |
| `radio` | `string` | Categorical — add enum + enumLabels from Choices column |
| `dropdown` | `string` | Categorical — same as radio |
| `checkbox` | `string` | Multi-select; each checkbox option is a separate variable in REDCap exports |
| `yesno` | `boolean` | REDCap stores as 1/0 but semantically yes/no |
| `truefalse` | `boolean` | |
| `calc` | `number` | Calculated field |
| `slider` | `integer` | Visual analog scale |
| `descriptive` | `string` | Display-only text; may have no real data |

---

## Remediation by issue code

### `missing_description`
Generate a concise, plain-English description using:

1. `source_row["Field Label"]` — use this directly if it is a complete sentence or meaningful phrase
   (clean it: remove trailing `:`, fix capitalization, remove HTML tags)
2. If `Field Label` is empty or just the variable name, infer from:
   - `source_row["Form Name"]` — instrument context
   - `source_row["Section Header"]` — sub-section context
   - `source_row["Field Note"]` — supplemental description
   - `name` components (split on underscores)
3. For checkbox sub-variables (names ending in `___1`, `___2`, etc.), describe the specific
   option being captured: "Indicates whether [option label] was selected for [parent question]."

Rules:
- 1–2 sentences, plain English
- Do not start with "This field", "This variable", or "The variable"
- Do not repeat the variable name verbatim

**Examples:**

| name | source context | good description |
|------|---------------|-----------------|
| `consent_obtained` | Field Label="Informed consent obtained?", Form Name="Enrollment" | "Indicates whether informed consent was obtained from the participant at enrollment." |
| `pain_scale_score` | Field Label="", Form Name="Pain Assessment", Section Header="VAS Scale" | "Pain intensity score from the Visual Analog Scale (VAS) administered at this visit." |
| `race___3` | Field Label="Race (choice=American Indian or Alaska Native)", Form Name="Demographics" | "Indicates whether the participant identified as American Indian or Alaska Native." |

---

### `description_too_short`
The description is a known placeholder ("N/A", "See codebook", "TBD", etc.) with no real
content. Replace it entirely using the same approach as `missing_description`.

---

### `missing_type`
Use the `Field Type` → VLMD type mapping table above.
Also check `source_row["Text Validation Type OR Show Slider Number"]` for text fields.

---

### `type_not_in_schema`
Map the invalid type value to the nearest valid VLMD type using the system invariants reference.
For REDCap-specific values: `calc` → `number`, `yesno` → `boolean`, `slider` → `integer`.

---

### `enum_without_labels`
Parse labels from `source_row["Choices, Calculations, OR Slider Labels"]`.
REDCap choices are pipe-separated: `1, Male | 2, Female | 3, Intersex`

Parse as:
```
for each choice in choices.split("|"):
    value, label = choice.strip().split(",", 1)
    enumLabels[value.strip()] = label.strip()
```

For `yesno` fields with no choices column, use: `{"1": "Yes", "0": "No"}`.
For `truefalse` fields: `{"1": "True", "0": "False"}`.

---

## Output format

Return a JSON array of the same length as the input.
Each element must follow the wrapper format from the system prompt:

```json
{
  "field": { ...corrected vlmd_field_draft with ALL original keys preserved... },
  "justification": "What was changed and why, citing specific REDCap column values.",
  "sources": [
    "source_row[\"Field Label\"] = 'Informed consent obtained?'",
    "source_row[\"Field Type\"] = 'yesno' → type = 'boolean'",
    "source_row[\"Form Name\"] = 'Enrollment' → section"
  ]
}
```

Only modify `field` properties needed to resolve the listed issue codes.
Preserve all other keys exactly as they appear in `vlmd_field_draft`.
