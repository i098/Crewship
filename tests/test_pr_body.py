import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_pr_body.py"
SPEC = importlib.util.spec_from_file_location("check_pr_body", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)
TEMPLATE = (ROOT / ".github/PULL_REQUEST_TEMPLATE.md").read_text()
VALID_BODY = """Closes #695

## Summary

Check every pull request body against the repository template.

## What changed and why

- Add a small body checker so incomplete descriptions cannot pass the required check.

## Test evidence

```text
python3 -m unittest discover -s tests -p test_pr_body.py
All body-check tests passed.
```

## Checklist

- [x] One concern in this PR.
- [x] The title uses the commit format, for example `fix(provisions): check the digest before install`.
- [x] Tests pass (`uv run pytest`).
- [x] Lint clean (`uv run ruff check`).
- [ ] Ansible syntax clean (`--syntax-check`). Not applicable: no playbook changed.
- [ ] Idempotent: `launch` → `launch` = `changed=0` on the second run. Not applicable: no provisioning path changed.
- [x] A changelog fragment, `changelog.d/<issue>.<type>.md` (not a `CHANGELOG.md` edit), or the `no changelog` label.

<details>
<summary>Validation evidence</summary>

## Risk Assessment

Low: a read-only format check.

## Testing

The checker accepted this body and rejected incomplete bodies.

</details>
"""


class PRBodyTests(unittest.TestCase):
    def check(self, body):
        return checker.check_body(body, TEMPLATE)

    def test_pipeline_style_body_with_collapsed_evidence_passes(self):
        self.assertEqual(self.check(VALID_BODY), [])

    def test_blank_template_does_not_pass(self):
        self.assertTrue(self.check(TEMPLATE))

    def test_real_opening_issue_reference_is_required(self):
        for first in ("Closes #", "Closes #0", "Summary\nCloses #695", "<!-- Closes #695 -->"):
            with self.subTest(first=first):
                self.assertTrue(self.check(VALID_BODY.replace("Closes #695", first, 1)))

    def test_each_required_heading_must_appear_once(self):
        for heading in ("Summary", "What changed and why", "Test evidence", "Checklist"):
            with self.subTest(heading=heading):
                self.assertTrue(self.check(VALID_BODY.replace(f"## {heading}\n", "", 1)))
                self.assertTrue(self.check(VALID_BODY + f"\n## {heading}\nDuplicate.\n"))

    def test_required_sections_cannot_be_empty_or_comment_only(self):
        for content in ("", "-", "<!-- Fill this in. -->", "```text\n```", "<br>", "<div></div>"):
            with self.subTest(content=content):
                body = VALID_BODY.replace(
                    "Check every pull request body against the repository template.", content
                )
                self.assertTrue(self.check(body))

    def test_comment_and_fenced_headings_do_not_supply_required_sections(self):
        for wrapped in (f"<!--\n{VALID_BODY}\n-->", f"```markdown\n{VALID_BODY}\n```"):
            with self.subTest(wrapped=wrapped[:20]):
                self.assertTrue(self.check("Closes #695\n" + wrapped))

    def test_headings_inside_code_do_not_create_duplicate_sections(self):
        body = VALID_BODY.replace("All body-check tests passed.", "## Summary\nexample output")
        self.assertEqual(self.check(body), [])

    def test_comment_markers_inside_code_are_literal(self):
        body = VALID_BODY.replace("All body-check tests passed.", "print('<!--')")
        self.assertEqual(self.check(body), [])

    def test_comment_markers_inside_inline_code_are_literal(self):
        body = VALID_BODY.replace(
            "Check every pull request body against the repository template.",
            "Handle `<!--` in PR descriptions.",
        )
        self.assertEqual(self.check(body), [])

    def test_markup_inside_inline_code_is_visible_content(self):
        body = VALID_BODY.replace(
            "Check every pull request body against the repository template.", "`<br>`"
        )
        self.assertEqual(self.check(body), [])

    def test_longer_fence_is_not_closed_by_shorter_fence(self):
        body = VALID_BODY.replace(
            "```text\npython3 -m unittest discover -s tests -p test_pr_body.py\n"
            "All body-check tests passed.\n```",
            "````text\n```\n## Summary\nexample output\n````",
        )
        self.assertEqual(self.check(body), [])

    def test_every_template_checklist_item_is_required(self):
        for line in VALID_BODY.splitlines():
            if line.startswith("- ["):
                with self.subTest(item=line):
                    self.assertTrue(self.check(VALID_BODY.replace(line, "", 1)))

    def test_checklist_items_inside_code_do_not_count(self):
        item = "- [x] One concern in this PR."
        body = VALID_BODY.replace(item, f"```markdown\n{item}\n```", 1)
        self.assertTrue(self.check(body))

    def test_indented_code_cannot_replace_the_checklist(self):
        body = "\n".join(
            "    " + line if line.startswith("- [") else line for line in VALID_BODY.splitlines()
        )
        self.assertTrue(self.check(body))

    def test_unchecked_items_require_an_inapplicable_reason(self):
        item = "- [x] One concern in this PR."
        for suffix in ("", " Not applicable:", " Not applicable: ---"):
            with self.subTest(suffix=suffix):
                self.assertTrue(self.check(VALID_BODY.replace(item, item.replace("[x]", "[ ]") + suffix)))

    def test_unchecked_item_with_reason_passes(self):
        item = "- [x] Lint clean (`uv run ruff check`)."
        body = VALID_BODY.replace(item, item.replace("[x]", "[ ]") + " Not applicable: no Python changes.")
        self.assertEqual(self.check(body), [])

    def test_cli_reads_stdin_and_reports_failure_for_an_incomplete_file(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], input=VALID_BODY, text=True, capture_output=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory) / "body.md"
            body.write_text("Closes #695\n")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(body)],
                text=True, capture_output=True, timeout=10,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("## Summary", result.stderr)


if __name__ == "__main__":
    unittest.main()
