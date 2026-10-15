Write the report on Mu2eBO campaign "{prefix}" (study "{study}") as Markdown.

FACTS.trigger says why it was asked for: "exit" = the campaign loop has just ended (a final report);
"milestone" = the campaign may still be running (an interim report: say so in the title and first bullet, and
treat every number as provisional); "manual" = an operator asked. If FACTS.note is not empty, quote it under the
title as the requester's note. Use these sections:

1. Summary (3-5 bullets)
2. Campaign setup (study, q, max_evals, picker, executor, context, exit code; from campaign_record)
3. Outcome by child state (a table from child_states; row counts only from counts)
4. Top configurations (a table: config, every objective, and the knobs)
5. Campaign vs whole board (board_campaign against board_all)
6. Surrogate view (objectives with directions and transforms, knob bounds, champion; from surrogate_stats)
7. Context from DocDB (from the kb_search results; omit the section if there are none)
8. Caveats and next steps (no new numbers here)

Do not write a provenance section: it is appended by the program from the actual calls. You may call the tools
for anything FACTS lacks; most reports need none. Return only the report.

FACTS:
```json
{facts}
```
