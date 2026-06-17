# System Invariants (VLMD Pipeline)

- Respond with **only a JSON array** as specified; no prose, no code fences, no trailing commas.
- Output length MUST match input length (one output object per input record).
- Do not invent data. If a value cannot be reasonably inferred, omit the key or use an empty string.
- Never add keys to the VLMD field that are not present in the HEAL VLMD schema.
- Apply identical normalization rules across all chunks in a run.
- Never echo the prompt or input back.

## Output format for every element

Each element of the output array must be a JSON object with exactly three keys:

```json
{
  "field": { ...corrected vlmd_field_draft... },
  "justification": "One to three sentences explaining what was changed and why.",
  "sources": ["list", "of", "specific", "evidence", "used"]
}
```

`sources` should name the exact inputs that informed the fix — e.g. `"name component 'anthro'"`,
`"source_row.table_label = 'Anthropometrics'"`, `"HBCD domain prefix 'ph_' = physical health"`,
`"VLMD schema constraint for type=string"`. Be specific enough that a human reviewer can verify
the reasoning without re-reading the original data.
