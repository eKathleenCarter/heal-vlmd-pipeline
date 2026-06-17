# Generic VLMD Field Fixup

You are fixing VLMD (Variable Level Metadata Dictionary) field records from a data dictionary
of unknown or generic format, converting to HEAL VLMD schema v0.3.2.

Each input record contains:
- `name`: the variable name (do NOT change)
- `issues`: list of problem codes requiring remediation
- `source_row`: available columns from the original file for context
- `vlmd_field_draft`: the partially-converted VLMD field to be corrected

## Remediation by issue code

### `missing_description`
Generate a clear, concise (1–2 sentence) description:
1. Split `name` on underscores/camelCase to derive readable words
2. Look in `source_row` for any column that contains descriptive text
3. Use `source_row` section/category/form context if available

Descriptions should:
- Be written in plain English
- Not start with "This field" or "This variable"
- Describe what the variable measures or represents

## Output format
Return a JSON array of the same length as the input.
Each element must follow the wrapper format defined in the system prompt:
`{"field": {...corrected vlmd_field_draft...}, "justification": "...", "sources": [...]}`.
Preserve all existing keys in `field`. Only modify properties indicated by the issue codes.
