# HBCD VLMD Field Fixup

You are fixing VLMD (Variable Level Metadata Dictionary) field records for the HBCD
(Healthy Brain and Child Development) study. HBCD is a longitudinal study of early brain
and child development in the United States.

Each input record contains:
- `name`: the variable name (snake_case, do NOT change)
- `issues`: list of problem codes requiring remediation
- `hbcd_row`: subset of the original HBCD source row for context
- `vlmd_field_draft`: the partially-converted VLMD field to be corrected

## Remediation rules by issue code

### `missing_description`
Generate a clear, concise (1–2 sentence) description for the field.

**Process:**
1. Parse the `name` field by splitting on underscores to understand the variable structure.
   Common HBCD prefix patterns:
   - `ph_` = physical health
   - `bio_` = biospecimens
   - `nt_` = novel technology
   - `nc_` = neurocognition
   - `sed_` = social/environmental determinants
   - `beh_` = behavior/child-caregiver interaction
   - `dem_` = demographics
   - `pex_` = pregnancy/exposure
2. Use `hbcd_row.table_label` to identify the instrument/form.
3. Use `hbcd_row.domain` and `hbcd_row.sub_domain` for broader context.
4. Use `hbcd_row.instruction` if available and non-empty.

**Example:** For `name = "ph_ch_anthro_warning_message"`, `table_label = "Anthropometrics"`,
`domain = "Physical Health"`: description = "Warning message generated during anthropometric
measurement recording for the child."

The description should:
- Be written in plain English
- Not start with "This field" or "This variable"
- Describe what the variable measures or represents
- Not exceed two sentences

## Output format

Return a JSON array where each element follows the wrapper format defined in the system prompt:

```json
{
  "field": { ...corrected vlmd_field_draft with ALL original keys preserved... },
  "justification": "Explain what was changed and why in 1–3 sentences.",
  "sources": [
    "name component 'anthro' → anthropometric",
    "source_row.table_label = 'Anthropometrics'",
    "source_row.domain = 'Physical Health'",
    "HBCD prefix 'ph_ch_' = physical health / child"
  ]
}
```

- Only modify `field` properties indicated by the issue codes
- `sources` must list the specific evidence used — name parts, source_row values, domain knowledge
- Do not add VLMD schema keys beyond what's needed to fix the issue
