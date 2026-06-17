# System Invariants (VLMD Pipeline)

- Respond with **only a JSON object or array** as specified; no prose, no code fences, no trailing commas.
- Do not invent data. If a value cannot be reasonably inferred, omit the key or use an empty string.
- Output length MUST match input length when processing arrays (one output per input record).
- Never add keys not present in the VLMD schema.
- Apply identical normalization rules across all chunks in a run.
- Never echo the prompt or input back.
