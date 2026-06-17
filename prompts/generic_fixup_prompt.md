# Generic VLMD Field Fixup

You are fixing VLMD (Variable Level Metadata Dictionary) field records from a data dictionary
of unknown or generic format, converting to HEAL VLMD schema v0.3.2.

Each input record contains:
- `name`: the variable name (do NOT change)
- `issues`: list of problem codes requiring remediation
- `source_row`: available columns from the original file for context
- `vlmd_field_draft`: the partially-converted VLMD field to be corrected

---

## Remediation by issue code

### `missing_description`
Generate a clear, concise description (1–2 sentences):

1. Split `name` on underscores and camelCase boundaries to derive readable words
2. Search `source_row` for any column that contains descriptive text
   (common column names: `label`, `field_label`, `question`, `description`, `title`, `text`)
3. Use `source_row` section/category/form/domain columns for instrument context
4. For score/computed variables (suffix `_raw`, `_t`, `_z`, `_pct`, `_sum`), name the scale and score type

Rules:
- 1–2 sentences, plain English
- Do not start with "This field", "This variable", or "The variable"
- Do not repeat the variable name verbatim
- Do not invent measurement details not present in the source row

**Examples:**

| name | source context | good description |
|------|---------------|-----------------|
| `participant_age_months` | domain="Demographics" | "Age of the participant in months at the time of assessment." |
| `bpi_pain_severity` | label="Pain Severity", domain="Pain Assessment" | "Composite pain severity score from the Brief Pain Inventory (BPI)." |
| `visit_number` | form="Visit Log" | "Sequential visit number for this participant." |
| `consent_signed` | type="yesno" | "Indicates whether the participant signed the informed consent form." |

---

### `description_too_short`
The description is a known placeholder ("N/A", "See codebook", "TBD", etc.) with no real
content. Replace it entirely following the same rules as `missing_description`.

---

### `missing_type`
Infer the VLMD type from available source columns:

1. Look for a type/data_type column in `source_row` and map it:
   - `double`, `float`, `numeric`, `continuous`, `decimal`, `ratio`, `interval` → `number`
   - `int`, `integer`, `count`, `whole` → `integer`
   - `char`, `character`, `text`, `string`, `categorical`, `nominal`, `ordinal` → `string`
   - `bool`, `logical`, `binary`, `yesno` → `boolean`
   - `date` → `date`; `datetime`, `timestamp` → `datetime`
2. If the field already has `constraints.enum`, it is categorical → type = `string`
3. Infer from the variable name:
   - ends in `_date`, `_dt` → `date`
   - ends in `_flag`, `_yn`, `_yes_no` → `boolean`
   - ends in `_count`, `_n`, `_num` → `integer`
   - ends in `_score`, `_pct`, `_rate`, `_mean` → `number`
4. Default to `string` when none of the above apply

---

### `type_not_in_schema`
The `type` value is not in the VLMD allowed set. Replace it with the correct value:

| Invalid value | Use instead |
|---|---|
| float, double, numeric, continuous, decimal | `number` |
| int, long, count, whole | `integer` |
| char, character, text, varchar, categorical, nominal, ordinal | `string` |
| bool, logical, binary, yesno | `boolean` |
| datetime, timestamp, posixct | `datetime` |

---

### `enum_without_labels`
`constraints.enum` has values but `enumLabels` is empty or missing.
Reconstruct labels from the source data:

1. Look for a choices/levels/options column in `source_row`
   - Pipe-separated format `1, Yes | 2, No` → split on `|`, then on the first `,`
   - JSON array format `[{"value":"1","label":"Yes"}]` → extract value/label pairs
   - Comma-separated labels only `Yes,No,Unknown` → use as labels, use 0-based index as values
2. If no label source exists, use the enum value itself as the label
   (e.g. `{"1": "1"}`) — better than leaving enumLabels empty

---

## Output format

Return a JSON array of the same length as the input.
Each element must follow the wrapper format from the system prompt:

```json
{
  "field": { ...corrected vlmd_field_draft with ALL original keys preserved... },
  "justification": "What was changed and why, citing specific source values.",
  "sources": [
    "name components 'bpi' + 'pain' + 'severity'",
    "source_row.domain = 'Pain Assessment'",
    "source_row.data_type = 'numeric' → type = 'number'"
  ]
}
```

Only modify `field` properties needed to resolve the listed issue codes.
Preserve all other keys exactly as they appear in `vlmd_field_draft`.
