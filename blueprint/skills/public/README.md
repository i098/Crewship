# Public skills

Skills that ship with Crewship. Put each skill in `blueprint/skills/public/<name>/SKILL.md`, with any helper files beside it. A folder with no `SKILL.md` of its own groups skills as `<group>/<name>/SKILL.md`: a file the skills share sits once in the group folder, with a relative symlink to it in each skill. The group installs whole, with its links, and each skill in it installs as a link `<name>` to `<group>/<name>`. With `profiles.public_skills` on, apply installs every skill here for omp (`~/.omp/agent/skills/`) and Claude Code (`~/.claude/skills/`). A skill in [`blueprint/skills/private/`](../private/README.md) with the same name wins on that host. See [Skills](../../../docs/omp.md#skills).

- [`clean-code-classes`](clean-code-classes/SKILL.md): one job per class, when to stop splitting, objects versus data, Law of Demeter, wrapping third-party libraries (credits `@s4.codes` reels).
- [`clean-code-comments`](clean-code-comments/SKILL.md): when a comment earns its place, and when to delete or replace it with code (credits `@s4.codes` reels).
- [`clean-code-errors`](clean-code-errors/SKILL.md): exceptions over error codes, catch blocks, wrapping library exceptions, the failure contract of a function (credits `@s4.codes` reels).
- [`clean-code-formatting`](clean-code-formatting/SKILL.md): blank lines, function order, declarations and indentation of a source file (credits `@s4.codes` reels).
- [`clean-code-functions`](clean-code-functions/SKILL.md): function size, one job, argument count, flags, side effects, switch statements, duplication (credits `@s4.codes` reels).
- [`clean-code-naming`](clean-code-naming/SKILL.md): names that reveal intent, no abbreviations or magic numbers (credits `@s4.codes` reels).
- [`clean-code-tests`](clean-code-tests/SKILL.md): F.I.R.S.T, one concept per test, build-operate-check, TDD (credits `@s4.codes` reels).
- [`code-clarity`](code-clarity/SKILL.md): write, review and simplify code by its naming, flow, state and abstractions (MIT, credited in [CREDITS.md](../../../CREDITS.md)).
- [`code-navigation`](code-navigation/SKILL.md): use CodeGraph and tokensave before grep or reading files.
- [`credentials`](credentials/SKILL.md): search every secrets file before you call a key absent, pass a process one variable and never the whole file, verify the process environment.
- [`engineering-standards`](engineering-standards/SKILL.md): weigh quality over cost, reproduce bugs end to end, fix lint, test and UI faults you see.
- [`eta-timeline`](eta-timeline/SKILL.md): answer an ETA question with a dark timeline PNG (operator's local time, one bar per item, done dots, moved amber, now line) rendered by headless Chrome, sendable with `fm-imessage --image`.
- [`fleet-browser`](fleet-browser/SKILL.md): the Obscura, Chrome and VNC browser ladder with one shared cookie jar, and when to use each tier.
- [`git-and-prs`](git-and-prs/SKILL.md): commit messages, generated files, and PR size and splits checked with `ponytail-review`.
- [`instagram-dm`](instagram-dm/SKILL.md): read the agent Instagram DMs with `instagrapi` (session reuse, email-code login), normalise shared posts to `/reel/` URLs for yt-dlp, wake the agent within seconds on a new DM from the operator, reply with `fm-insta-reply`, and curate a few worthwhile reels a day with `reel_curator.py`.
- [`ieee-documentation`](ieee-documentation/SKILL.md): IEEE 1016 design and IEEE 829 test documents, kept in proportion.
- [`manim`](manim/SKILL.md): explain math and diagrams with a Manim Community scene rendered to mp4 or gif in a 1-day-pruned cache, gif sendable with `fm-imessage --image`.
- [`mobile-app-first-build`](mobile-app-first-build/SKILL.md): validate an idea with a mobile web prototype, choose a platform, map flows, write requirements, build, test, and release (credits u/olenami's Reddit guide).
- [`observability`](observability/SKILL.md): walk seven levels of logs, metrics, traces, correlation, alerts, SLOs and cardinality, and review a service against them.
- [`openmontage`](openmontage/SKILL.md): make a video, reel or explainer clip with OpenMontage; renders mp4 into a 1-day-pruned cache, spring motion, beat-locked synthesized sound, a self-review pass; poster frame sendable with `fm-imessage --image`.
- [`operating-rules`](operating-rules/SKILL.md): ask or act, keep scope, finish the work, and answer a question as a question.
- [`pr-preview`](pr-preview/SKILL.md): a Lavish board that recreates the GitHub PR, issue or comment page, with the body rendered by GitHub's Markdown API (CSS vendored from `github-markdown-css`, MIT, credited in [CREDITS.md](../../../CREDITS.md)).
- [`process-safety`](process-safety/SKILL.md): kill by pid, not by pattern, and keep test services and worktree ports apart.
- [`prod-readiness`](prod-readiness/SKILL.md): run 20 evidence-backed checks before a production launch, deploy, release to users, or an "is this ready" review.
- [`progress-bars`](progress-bars/SKILL.md): a fixed ASCII progress-bar format with percentages from real counts.
- [`quality-gates`](quality-gates/SKILL.md): sentrux and fallow gates and the pull-based codex advisor.
- [`repo-readme`](repo-readme/SKILL.md): write or polish a repository README: hero with badges and Sponsor button, live screenshot, present-tense features, quick start, how-it-works diagram, layout and license, with a template and a polish checklist (community files, templates, topics and SEO, social preview).
- [`signal-chunks`](signal-chunks/SKILL.md): plan a week with one shipping goal and a timezoned deadline, eighteen-hour chunks, three to five signal tasks, named noise, an eighty-percent effort target, and CHUNK status with a verdict (Jobs-inspired method, not a claim about Jobs' own schedule).
- [`site-walkthrough-video`](site-walkthrough-video/SKILL.md): a smooth walk-through video of a 3D or WebGL site, driven with real keyboard and mouse-look input (planned route through open space, spring turns, a stop at each area), captured frame-exact at 1080p60 in parallel segments, reviewed per leg, framed on a desktop wallpaper with synthesized sound.
- [`slack-relay`](slack-relay/SKILL.md): relay Slack messages to iMessage; see the skill for filtering rules and setup.
- [`talk-style`](talk-style/SKILL.md): short, plain ASD-STE100 replies with no preamble and no em dash.
- [`third-party-signups`](third-party-signups/SKILL.md): act on an owner's standing authorization for signups, email codes and app approvals, with the bounds that always hold.
- [`ui-ux`](ui-ux/): two UI skills that share [`shared-basics.md`](ui-ux/shared-basics.md) (alignment, one primary button per view, relative units, accessibility): [`app-dashboard`](ui-ux/app-dashboard/SKILL.md) for app screens, dashboards, forms, dialogs and loading states, and [`landing-marketing`](ui-ux/landing-marketing/SKILL.md) for landing pages, CTA copy, entrance motion and gradients (credits Zander Whitehurst's reels).
- [`usage-card`](usage-card/SKILL.md): answer usage, quota, resource, load and disk questions with the `fm-usage-brief --png` card; notes the hourly `fm-usage-remind` reminder.
- [`tooling-conventions`](tooling-conventions/SKILL.md): bun, gh-axi, lavish, no-mistakes, herdr, skillspector, caveman and ponytail.
