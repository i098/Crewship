# Review evidence

Use each row that applies to your change.

| Change kind | Required evidence | Capture tool | Host | PR body section |
| --- | --- | --- | --- | --- |
| Visible UI (web, desktop, or terminal) | Before and after screenshots of the same view and state | `chrome-devtools-axi` for web; OS screenshot tool for desktop or terminal | GitHub upload or public R2 bucket | `Review evidence` |
| UI motion or interaction | Screenshots plus a short recording of the changed flow | Browser or OS screen recorder | GitHub upload or public R2 bucket | `Review evidence` |
| Design choice that needs reviewer input | A bearings board with the options and the decision to review | Lavish board export | Public R2 bucket | `Review evidence` |
| CLI, API, runtime, or infrastructure | Command, scenario, and observed result | Terminal or CI job | PR text or GitHub Actions run | `Test evidence` |
| Documentation or tests only | Rendered page or targeted test result | Markdown preview or test runner | PR text, GitHub upload, or GitHub Actions run | `Test evidence` |

1. Capture the actual surface on the base and head revisions with the same input.
   Remove secrets and private data before you upload anything.
2. Upload images and video to GitHub or an approved public R2 bucket.
   Publish board exports to the approved public R2 bucket.
   Never commit evidence binaries.
3. Embed the screenshots under `## Review evidence` as `![Before](https://…)` and `![After](https://…)`.
   Link the recording or board with a descriptive label, such as `[Recording of the setup flow](https://…)`.
   Open each link as a reviewer to check access.

Ask a maintainer to add `ui` to a PR that changes the visible UI.
If the repository has no `ui` label, create it in GitHub once before applying it.
The required PR body check needs one filled `Review evidence` section when the `ui` label is present.
PRs without that label can omit the section.
The [local PR check](../CONTRIBUTING.md#pull-requests) still checks for a hosted image when the diff changes UI files.
Reviewers verify that the linked evidence covers the change.
