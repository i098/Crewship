Closes #

<!-- Every PR follows this template, including Dependabot and release PRs. There are no exemptions. -->

## Summary

<!-- One or two sentences: what this PR does. -->

## What changed and why

-

## Test evidence

<!-- The commands you ran and what they showed. -->

## Checklist

<!-- Keep every item. Check completed items. See CONTRIBUTING.md#pull-requests for unchecked items and required explanations. -->

- [ ] One concern in this PR.
- [ ] The title uses the commit format, for example `fix(provisions): check the digest before install`.
- [ ] Tests pass (`uv run pytest`).
- [ ] Lint clean (`uv run ruff check`).
- [ ] Ansible syntax clean (`--syntax-check`).
- [ ] Idempotent: `launch` → `launch` = `changed=0` on the second run.
- [ ] A changelog fragment, `changelog.d/<issue>.<type>.md` (not a `CHANGELOG.md` edit), or the `no changelog` label.
