# Format Detection & Column Mapping Prompt

You are analyzing a data dictionary file to map its columns to HEAL VLMD schema properties.

## VLMD schema properties (target)

Required:
- `name` — unique variable identifier (snake_case or similar)
- `description` — human-readable description of what the variable measures

Optional but important:
- `title` — short display label
- `type` — data type: number, integer, string, boolean, date, datetime, time
- `section` — grouping/instrument/form this variable belongs to
- `constraints.enum` — allowed values for categorical variables (list of strings)
- `enumLabels` — dict mapping enum values to human-readable labels
- `enumOrdered` — true if categorical variable has an ordered relationship
- `constraints.minimum` — minimum allowed/observed value for numeric variables
- `constraints.maximum` — maximum allowed/observed value for numeric variables
- `relatedConcepts` — links to documentation or ontology terms
- `custom` — catch-all for format-specific metadata

## Your task

Given the column names and sample rows from an unknown data dictionary file:

1. Identify which column contains variable names (the `name` property)
2. Identify which column contains descriptions or labels
3. Identify which column, if any, indicates data type
4. Identify which column, if any, contains categorical choices/levels
5. Identify which column, if any, groups variables into sections
6. Identify which column, if any, gives the minimum allowed/valid value for
   numeric variables (`minimum_column`) — look for headers like `minimum`,
   `min`, `lower_bound`, `valid_min`, `range_low`
7. Identify which column, if any, gives the maximum allowed/valid value for
   numeric variables (`maximum_column`) — look for headers like `maximum`,
   `max`, `upper_bound`, `valid_max`, `range_high`
8. Identify which column, if any, holds free-text notes/definitions for
   specific values (`value_labels_column`) — distinct from the categorical
   choices/levels column; typically prose like `1=Yes; 2=No` or per-value
   annotations, not a structured list of all valid codes
9. Suggest data type mapping (source type values → VLMD type strings)
10. Suggest the format of the levels column (json_array, pipe_separated, comma_separated, or other)
11. List remaining columns that should go into `custom` — do NOT include any
    column already mapped above (name, description, title, type, levels,
    section, minimum, maximum, value_labels)

## Output format

Return a single JSON object:

```json
{
  "format_guess": null,
  "confidence": 0.15,
  "reasoning": "Brief explanation of what the file appears to be",
  "proposed_mapping": {
    "name_column": "ColumnName or null",
    "description_column": "ColumnName or null",
    "title_column": "ColumnName or null",
    "type_mapping": {
      "source_column": "ColumnName or null",
      "lookup": {"source_val": "vlmd_type"}
    },
    "enum_ordered": {
      "source_column": "ColumnName or null",
      "trigger_values": []
    },
    "section": {
      "primary_column": "ColumnName or null",
      "fallback_column": null
    },
    "levels": {
      "source_column": "ColumnName or null",
      "format": "pipe_separated",
      "pair_separator": ",",
      "choice_separator": "|"
    },
    "minimum_column": "ColumnName or null",
    "maximum_column": "ColumnName or null",
    "value_labels_column": "ColumnName or null",
    "related_concepts": [],
    "custom_columns": ["col1", "col2"],
    "capture_unmapped_as_custom": true
  },
  "column_explanations": {
    "ColumnName": "Why this column maps to that property"
  }
}
```

For `levels.format`, choose from:
- `json_array` — column contains JSON like `[{"value":"1","label":"Yes"}]`
- `pipe_separated` — column contains text like `1, Yes | 2, No`
- `comma_separated` — column contains text like `Yes,No,Maybe`
- `auto_detect` — format is unclear

Set `format_guess` to a known format name if you recognize it (hbcd, redcap) — or null if unknown.
Set `confidence` between 0.0 (no idea) and 1.0 (certain).
