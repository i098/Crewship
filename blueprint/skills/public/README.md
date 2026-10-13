# Public skills

Skills that ship with Crewship. Put each skill in `blueprint/skills/public/<name>/SKILL.md`, with any helper files beside it. The `agents` profile installs every skill here for omp (`~/.omp/agent/skills/`) and Claude Code (`~/.claude/skills/`). A skill in [`blueprint/skills/private/`](../private/README.md) with the same name wins on that host. See [Skills](../../../docs/omp.md#skills).

- [`code-clarity`](code-clarity/SKILL.md): write, review and simplify code by its naming, flow, state and abstractions (MIT, credited in [CREDITS.md](../../../CREDITS.md)).
- [`code-navigation`](code-navigation/SKILL.md): use CodeGraph and tokensave before grep or reading files.
- [`engineering-standards`](engineering-standards/SKILL.md): weigh quality over cost, reproduce bugs end to end, fix lint, test and UI faults you see.
- [`eta-timeline`](eta-timeline/SKILL.md): answer an ETA question with a dark timeline PNG (operator's local time, one bar per item, done dots, moved amber, now line) rendered by headless Chrome, sendable with `fm-imessage --image`.
- [`git-and-prs`](git-and-prs/SKILL.md): commit messages, generated files, and PR size and splits checked with `ponytail-review`.
- [`instagram-dm`](instagram-dm/SKILL.md): read the agent Instagram DMs with `instagrapi` (session reuse, email-code login), normalise shared posts to `/reel/` URLs for yt-dlp, wake the agent within seconds on a new DM from the operator, reply with `fm-insta-reply`, and curate a few worthwhile reels a day with `reel_curator.py`.
- [`ieee-documentation`](ieee-documentation/SKILL.md): IEEE 1016 design and IEEE 829 test documents, kept in proportion.
- [`manim`](manim/SKILL.md): explain math and diagrams with a Manim Community scene rendered to mp4 or gif in a 1-day-pruned cache, gif sendable with `fm-imessage --image`.
- [`openmontage`](openmontage/SKILL.md): make a video, reel or explainer clip with OpenMontage; renders mp4 into a 1-day-pruned cache, spring motion, beat-locked synthesized sound, a self-review pass; poster frame sendable with `fm-imessage --image`.
- [`operating-rules`](operating-rules/SKILL.md): ask or act, keep scope, finish the work, and answer a question as a question.
- [`pr-preview`](pr-preview/SKILL.md): a Lavish board that recreates the GitHub PR, issue or comment page, with the body rendered by GitHub's Markdown API (CSS vendored from `github-markdown-css`, MIT, credited in [CREDITS.md](../../../CREDITS.md)).
- [`process-safety`](process-safety/SKILL.md): kill by pid, not by pattern, and keep test services and worktree ports apart.
- [`progress-bars`](progress-bars/SKILL.md): a fixed ASCII progress-bar format with percentages from real counts.
- [`quality-gates`](quality-gates/SKILL.md): sentrux and fallow gates and the pull-based codex advisor.
- [`site-walkthrough-video`](site-walkthrough-video/SKILL.md): a smooth walk-through video of a 3D or WebGL site, driven with real keyboard and mouse-look input (planned route through open space, spring turns, a stop at each area), captured frame-exact at 1080p60 in parallel segments, reviewed per leg, framed on a desktop wallpaper with synthesized sound.
- [`slack-relay`](slack-relay/SKILL.md): text the operator the important Slack messages (DMs, mentions, threads, decisions, deadlines, asks, incidents) from the slk cache, read-only, filtered by one `omp -p` call, at most one `fm-imessage` text per minute, every decision logged; opt-in `systemd --user` unit.
- [`talk-style`](talk-style/SKILL.md): short, plain ASD-STE100 replies with no preamble and no em dash.
- [`usage-card`](usage-card/SKILL.md): answer usage, quota, resource, load and disk questions with the `fm-usage-brief --png` card; notes the hourly `fm-usage-remind` reminder.
- [`tooling-conventions`](tooling-conventions/SKILL.md): bun, gh-axi, lavish, no-mistakes, herdr, skillspector, caveman and ponytail.
