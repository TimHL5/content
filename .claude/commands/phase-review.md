Review the current phase in PLAN.md against its "Done when" criteria.

1. For each task, confirm it's implemented and tested; cite files.
2. Run `make lint test` (and `make eval` if the phase is ≥ 2) and report the results.
3. Check the guardrails in CLAUDE.md (reference media not reused, deletion lifecycle, deterministic vs LLM fields, renderer purity).
4. List gaps, bugs, or spec drift, ordered by severity.
5. If everything passes, propose updating "Current phase" in PLAN.md. Don't change it until I confirm.
