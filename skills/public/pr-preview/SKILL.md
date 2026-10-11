---
name: pr-preview
description: Use before you post a pull request, issue or comment, and when an approval request needs a faithful look at the page. Builds a Lavish board that recreates the GitHub PR, issue or comment page with the real body rendering.
---

# Show the page before you post it

A reader cannot judge Markdown from raw text. Before you post a PR, an issue or a comment, build the board and show it. Post only after the reader says go.

The board is one HTML file. The body comes from GitHub's own Markdown API (`gh api markdown`, mode `gfm`, the target repository as context), so `@mentions`, `#refs`, task lists, tables, code blocks and alerts render as they will on the target repository. The style is the Primer Markdown CSS (`github-markdown-light.css`, vendored from `github-markdown-css`, MIT; see `LICENSE` and CREDITS.md in the Crewship repository).

## Steps

1. Write the title and the body to files outside the repository, for example under `/tmp`.
2. Run the script that sits next to this file. `gh` MUST be signed in.
   - PR from the current branch, read from local git: `pr_preview.py pr --repo OWNER/REPO --base main --head [FORK:]BRANCH --title "…" --body-file /tmp/body.md`
   - PR that is already pushed, read from the compare API: add `--compare`.
   - Issue: `pr_preview.py issue --repo OWNER/REPO --title "…" --body-file /tmp/body.md`
   - One comment: `pr_preview.py comment --repo OWNER/REPO --body-file /tmp/comment.md`
3. The script prints the HTML path (default `.lavish/pr-preview.html`; use `--out` for a name per topic). Open it: `lavish-axi .lavish/pr-preview.html`.
4. Give the reader the board. If the reader asks for changes, edit the body file, run the script again and reload.

## What the board shows

- PR: title, `#N` (`--number`), "wants to merge N commits into `base` from `fork:branch`", and three tabs. Conversation has the body comment and the sidebar. Commits and Files changed come from the real branch, with line numbers and `+`/`-` counts.
- Issue: title, state, the body comment and the sidebar.
- Comment: the one comment box.

## Options

- `--author LOGIN` (default: the `gh` login), `--when "3 days ago"`, `--number N`.
- `--base-ref` and `--head-ref` set the git refs when they differ from `origin/<base>` and `HEAD`. `--git DIR` reads another clone.
- `--tab commits|files` sets the tab shown first. `--max-diff-lines` (default 600) cuts long diffs.

## Limits

- The board needs network access for avatars and for images in the body.
- GitHub shows data that does not exist before posting: checks, reviewers, labels, timeline events. The board shows static placeholders there. Diffs have no syntax colours and no file tree.
- The diff is plain HTML, not `@pierre/diffs`, so the file loads no external script.
