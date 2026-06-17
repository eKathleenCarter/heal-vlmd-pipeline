# HBCD VLMD Field Fixup

You are fixing VLMD field records for the HBCD (Healthy Brain and Child Development) study —
a large longitudinal study of early brain and child development in the United States. Variables
span neuroimaging, biospecimens, behavioral assessments, demographics, and environmental exposures.

Each input record contains:
- `name`: variable name in snake_case (do NOT change)
- `issues`: list of problem codes to fix
- `source_row`: key columns from the original HBCD source row for context
- `vlmd_field_draft`: the partially-converted VLMD field to correct

---

## HBCD domain knowledge

### Variable name prefix patterns
HBCD variable names encode domain and subdomain as prefixes separated by underscores.
Use these to infer context when source columns are sparse:

| Prefix | Domain / instrument |
|--------|-------------------|
| `ph_` | Physical Health |
| `ph_ch_` | Physical Health — Child |
| `ph_m_` | Physical Health — Mother/Caregiver |
| `bio_` | Biospecimens |
| `bio_nails_` | Biospecimens — Nail samples |
| `bio_bf_` | Biospecimens — Breastfeeding/Formula |
| `nt_` | Novel Technology |
| `nt_wearable_` | Novel Technology — Wearable sensors |
| `nc_` | Neurocognition |
| `nc_cog_` | Neurocognition — Cognitive assessment |
| `eeg_` | EEG / Neurophysiology |
| `mri_` | MRI / Neuroimaging |
| `sed_` | Social & Environmental Determinants |
| `sed_bfy_` | SED — Baby's First Years |
| `beh_` | Behavior / Child-Caregiver Interaction |
| `beh_ecbq_` | Behavior — Early Childhood Behavior Questionnaire |
| `dem_` | Demographics |
| `dem_child_` | Demographics — Child |
| `dem_cg_` | Demographics — Caregiver |
| `pex_` | Pregnancy / Prenatal Exposure |
| `pex_bm_` | Pregnancy — Birth Mother |
| `vis_` | Visit metadata |
| `adm_` | Administrative |

### Common HBCD instrument abbreviations in variable names
`anthro` = anthropometric measurements, `cbcl` = Child Behavior Checklist,
`bsid` = Bayley Scales of Infant Development, `brief` = BRIEF executive function,
`ecbq` = Early Childhood Behavior Questionnaire, `msel` = Mullen Scales of Early Learning,
`aosi` = Autism Observation Scale for Infants, `eeg` = electroencephalography,
`dti` = diffusion tensor imaging, `t1w`/`t2w` = MRI structural sequences,
`nback` = N-back working memory task, `sst` = Stop Signal Task

---

## Remediation by issue code

### `missing_description`
Generate a clear, concise description (1–2 sentences) using this process:

1. Parse `name` by splitting on underscores — use the prefix table above to identify domain
2. Identify the instrument from `source_row.table_label` or `source_row.sub_domain`
3. Use `source_row.instruction` if present and non-empty (it often contains the original question text)
4. Use `source_row.domain` and `source_row.sub_domain` for broader context
5. For scoring/computed variables (suffix `_raw`, `_t`, `_z`, `_pct`, `_sum`), name the scale and score type

Rules:
- 1–2 sentences, plain English
- Do not start with "This field", "This variable", or "The variable"
- Do not repeat the variable name verbatim
- Do not invent measurement details (ranges, units) that are not in the source row

**Examples:**

| name | source context | good description |
|------|---------------|-----------------|
| `ph_ch_anthro_warning_message` | table_label="Anthropometrics", domain="Physical Health" | "Warning message generated during child anthropometric measurement data entry." |
| `eeg_alpha_power_oz` | table_label="EEG Resting State", sub_domain="Power Spectral Density" | "Alpha band power (8–12 Hz) measured at electrode Oz during resting-state EEG." |
| `beh_ecbq_surgency_raw` | table_label="ECBQ", domain="Behavior" | "Raw surgency/extraversion score from the Early Childhood Behavior Questionnaire (ECBQ) based on caregiver report." |
| `vis_001_completion` | table_label="Visit Information" | "Completion status of visit 001." |

---

### `description_too_short`
The description is a known placeholder ("N/A", "See codebook", "TBD", etc.) with no real
content. Replace it entirely following the same rules as `missing_description`.

---

### `missing_type`
Infer the VLMD type from the source row and variable name:

1. Check `source_row.type_data` and `source_row.type_level` using this mapping:
   - `double` / `float` / `interval` / `ratio` → `number`
   - `integer` / `count` → `integer`
   - `character` / `text` / `nominal` / `ordinal` → `string`
   - `date` → `date`
2. If `source_row.levels1` has values, the field is categorical → type = `string`
3. If the variable name ends in `_date` or `_dt` → type = `date`
4. If the variable name ends in `_flag`, `_yn`, `_yes_no` → type = `boolean`
5. If none of the above apply, default to `string`

---

### `type_not_in_schema`
The `type` value is not in the VLMD allowed set. Map it to the nearest valid type:

| Invalid value | Use instead |
|---|---|
| float, double, numeric, continuous, decimal | `number` |
| int, long, count, whole | `integer` |
| char, character, text, varchar, categorical, nominal, ordinal, free_text | `string` |
| bool, logical, binary, yesno | `boolean` |
| datetime, timestamp, posixct | `datetime` |

---

### `enum_without_labels`
`constraints.enum` has values but `enumLabels` is empty or missing.
Reconstruct labels from the source data:

1. Check `source_row.levels1` — if it contains a JSON array like
   `[{"value": "1", "label": "Male"}, ...]`, extract value→label pairs directly
2. If levels are pipe-separated like `1, Male | 2, Female`, split on `|` then `,`
3. If only numeric codes exist with no labels available, use the code as both key and value
   (e.g., `{"1": "1", "2": "2"}`) — this is better than leaving enumLabels empty

---

## Output format

Return a JSON array where each element follows the wrapper format from the system prompt:

```json
{
  "field": { ...corrected vlmd_field_draft with ALL original keys preserved... },
  "justification": "What was changed and why, referencing specific source values used.",
  "sources": [
    "name prefix 'ph_ch_' = Physical Health / Child",
    "source_row.table_label = 'Anthropometrics'",
    "source_row.type_data = 'double' → type = 'number'"
  ]
}
```

- Only modify `field` properties needed to resolve the listed issue codes
- Preserve all other keys exactly as they appear in `vlmd_field_draft`
- Do not add VLMD schema keys beyond what is needed to fix the issue
