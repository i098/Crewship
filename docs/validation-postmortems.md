# Validation post-mortems

Append one row for each failed no-mistakes run or CI gate with `scripts/validation_postmortem.py`.
The columns are the UTC entry date, run ID or link, failed step, root cause, fix, and prevention change link.
Keep the facts public and verified; state when a cause remains unknown or a fix has not merged.
A log entry alone is not prevention: land the linked code, test, brief, or check change.
The script rejects empty fields, joins whitespace, and escapes table separators.

| Date (UTC) | Run or link | Failed step | Root cause | Fix | Prevention change |
| --- | --- | --- | --- | --- | --- |
| 2026-10-27 | https://github.com/i098/Crewship/actions/runs/40430729048 | pull request body | The body used Details instead of What changed and why, changed checklist text, and omitted checklist items. | Restore the template sections and checklist; the next run passed: https://github.com/i098/Crewship/actions/runs/40430828556. | [Body checker](../scripts/check_pr_body.py) and [prepublication template rule](../CONTRIBUTING.md#pull-requests) require the exact template and a local body check. |
| 2026-10-27 | https://github.com/i098/Crewship/issues/754 | test_native_helper_calls_register_separately_from_chat | The report records missing completion rows after delivery warnings and a 30-second wait under parallel load; it does not prove a root cause. | The test-side change in https://github.com/i098/Crewship/pull/928 retries only the missing-record error, at most three attempts; it has not merged as of this entry. | [Committed test-side change](https://github.com/i098/Crewship/blob/5e51b1a20428cedba5dbf9f16b86cec06f6fd44c/tests/test_usage_source.py#L328-L339) retains the completion assertions and stops on other errors; this prevention is pending merge. |
| 2026-10-27 | fm/cf-postmortem ponytail-review 2026-10-27 | pre-validation review | Appending after a missing final newline joined two table rows. | Check the last byte and add a newline before the entry when needed. | [Append boundary check](../scripts/validation_postmortem.py) and [newline regression cases](../tests/test_validation_postmortem.py). Landed with this log entry. |
