# Description Triage

You are reviewing data-dictionary variables whose `description` was flagged as
suspiciously short by an automated heuristic (a low word count, or an exact match
against a list of common English placeholder strings like "n/a" or "todo"). Not
every flagged description is actually broken, and not every broken-looking one
should be rewritten by guessing — your job is to sort candidates into the right
bucket, not to fix them yourself.

The guiding principle: **never invent or infer meaning the source data doesn't
actually contain.** The original data dictionary's values are the ground truth
for this study — a cryptic technical value the source author actually wrote
(e.g. "relResdiff1") is still real content, even if it means nothing to an
outside reader. Rewriting it risks fabricating an explanation nobody verified.
That is a fundamentally different problem from a description that's empty,
truncated, or a placeholder someone forgot to fill in — those really do need
an LLM (or a human) to supply real content because there currently is none.

For each field below, decide:

- `"send_to_llm"` — the description is genuinely inadequate: empty-in-spirit
  filler, a truncated fragment, or an obvious unfilled placeholder ("TBD",
  "n/a", "none"). There is no real content to preserve, so an LLM rewrite adds
  information rather than replacing it.
- `"leave_as_is"` — the description is short but already conveys real meaning
  given context: a legitimate field label ("Header", "Language"), or a
  correctly-translated non-English word that makes sense in context (e.g.
  Spanish "todo" = "all" in a Spanish-language instrument table).
- `"flag_for_human"` — the value is real source content, but is cryptic,
  abbreviated, or technical jargon that isn't self-explanatory to an outside
  reader ("relResdiff1", "relResA"). Do NOT guess what it means and do NOT
  propose a rewrite. This needs a human with domain knowledge to either
  confirm it's fine as-is or supply the correct expansion themselves.

Use every piece of context provided — especially `table_label`, `domain`, and
`sub_domain` — to judge language and subject matter before assuming a short or
unusual word is a placeholder. If the context suggests a non-English instrument
(e.g. a table label naming a language, or a field name pattern shared with a
same-topic English-labeled table), weigh that heavily. When genuinely unsure
whether something is broken or just terse domain jargon, prefer
`"flag_for_human"` over `"send_to_llm"` — the safe default is to not touch
real source data, not to guess.

Return ONLY a JSON array, one object per field, in the same order given, no prose
or code fences:

```json
[
  {"name": "<field name>", "decision": "send_to_llm" | "leave_as_is" | "flag_for_human", "justification": "<one sentence>"}
]
```

Fields to triage:
