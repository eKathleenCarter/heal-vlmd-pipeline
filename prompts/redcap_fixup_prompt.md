# REDCap VLMD Field Fixup

You are fixing VLMD field records converted from a REDCap data dictionary export.

Each input record contains:
- `name`: the variable name from "Variable / Field Name" column (do NOT change)
- `issues`: list of problem codes
- `source_row`: subset of the original REDCap row for context
- `vlmd_field_draft`: the partially-converted VLMD field

## Remediation by issue code

### `missing_description`
The "Field Label" was empty or not useful. Generate a concise description using:
1. The `name` field (snake_case → readable words)
2. The `source_row.Form Name` (instrument context)
3. The `source_row.Section Header` if present
4. The `source_row.Field Note` if present

Descriptions should be 1–2 sentences, plain English, not starting with "This field".

## Output format
Return a JSON array of the same length as the input.
Each element must be the corrected `vlmd_field_draft` with issues resolved.
Include all existing keys.
