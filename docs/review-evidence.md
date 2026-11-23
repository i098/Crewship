# Review evidence

Use each row that applies to your change.

| Change kind | Required evidence | Capture tool | Host | PR body section |
| --- | --- | --- | --- | --- |
| UI changes on the paths below | Before and after screenshots of the same view and state; for a new view, the After image only | `chrome-devtools-axi` for web; OS screenshot tool for terminal | GitHub upload | `Review evidence` |
| UI motion or interaction | A short recording of the changed flow, plus screenshots if the path list applies | Browser or OS screen recorder | GitHub upload | `Review evidence` |
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
   If GitHub inserts an HTML tag, copy its `src` URL into the Markdown image.
   Use a separate upload for each revision.
   For a new view, put `Before: none, new view` on its own line in place of the Before image.
   Start each evidence line with Markdown, not an HTML tag or comment.
   Link the recording or board with a descriptive label, such as `[Recording of the setup flow](https://…)`.
   Open each link as a reviewer to check access.

## Automatic screenshot checks

The local pre-push check and CI use the same case-insensitive Git globs from the repository root:

- Site pages, templates, styles, and scripts: `site/public/**/*.html`, `site/public/**/*.css`, `site/public/**/*.js`, `site/build.py`.
- Terminal UI source: `tools/*-tui/**/*.ts`, `tools/fleet-health/**/*.ts`, `tools/tui-theme/**/*.ts`.

The checks exclude `tools/**/*.test.ts` and `site/public/google2a77445d3f9ccb0e.html`, a site verification file.
Other paths do not require screenshots.
Omit the `Review evidence` section only when no row calls for it.
The checker reads link format and upload IDs, but does not fetch attachments.
Reviewers open the links and verify that the evidence covers the change.
