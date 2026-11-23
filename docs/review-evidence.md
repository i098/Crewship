# Review evidence

Use each row that applies to your change.

| Change kind | Required evidence | Capture tool | Host | PR body section |
| --- | --- | --- | --- | --- |
| Visible UI (web, desktop, or terminal) | Before and after screenshots of the same view and state; for a new view, the After image only | `chrome-devtools-axi` for web; OS screenshot tool for desktop or terminal | GitHub upload | `Review evidence` |
| UI motion or interaction | Screenshots plus a short recording of the changed flow | Browser or OS screen recorder | GitHub upload | `Review evidence` |
| Design choice that needs reviewer input | A bearings board with the options and the decision to review | Lavish board export as PNG or HTML | GitHub upload | `Review evidence` |
| CLI, API, runtime, or infrastructure | Command, scenario, and observed result | Terminal or CI job | PR text or GitHub Actions run | `Test evidence` |
| Documentation or tests only | Rendered page or targeted test result | Markdown preview or test runner | PR text, GitHub upload, or GitHub Actions run | `Test evidence` |

1. Capture the actual surface on the base and head revisions with the same input.
   Capture only the head revision for a new view.
   Remove secrets and private data before you upload anything.
2. [Attach screenshots and recordings to the PR on GitHub](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files).
   Attach PNG or HTML board exports to a PR comment and copy the attachment URL.
   Never commit evidence binaries.
3. Embed the screenshots on separate lines under `## Review evidence` as `![Before](URL)` and `![After](URL)`.
   For a new view, put `Before: none, new view` on its own line in place of the Before image.
   Link the recording or board with a descriptive label, such as `[Recording of the setup flow](https://…)`.
   Open each link as a reviewer to check access.

The required PR body check detects UI files in the diff and checks the format of screenshot links in `Review evidence`.
PRs without UI file changes can omit the section unless another row applies.
Reviewers verify that the linked evidence covers the change.
