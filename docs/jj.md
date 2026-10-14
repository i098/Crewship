# Jujutsu (jj)

`crewship.profiles.jj` is off by default.
It installs [Jujutsu](https://github.com/jj-vcs/jj) (`jj`) for agents, to use next to git in the same repository.

## Enable

```yaml
crewship:
  profiles:
    jj: true
```

Run `./ship.sh chart` to preview, then `./ship.sh launch` to apply.
Apply installs the latest jj release as `~/.local/bin/jj`, which agents already have on `PATH`.
It resolves the release at apply time, checks the download against the SHA-256 that GitHub lists for the release asset, and refuses a release without one.
Nothing is pinned, so each apply moves jj to the newest release.
Apply changes no repository: jj is available, and each repository opts in by itself.

## Colocated mode

In a colocated repository, `.jj/` sits next to `.git/`.
jj keeps its own history and reads and writes the same git objects and refs as git.
jj bookmarks are git branches, and `jj git push` pushes the same refs that `git push` does.
`.jj/` has its own ignore file, so `git status` stays clean.

Run this once in an existing git repository.
jj does not read git's user name and email, so the snippet copies them:

```bash
jj git init --colocate
jj config set --repo user.name "$(git config user.name)"
jj config set --repo user.email "$(git config user.email)"
jj metaedit --update-author   # gives the first working-copy commit the same author
```

`jj config set --repo` stores the values in your jj user config directory, not in the repository.
The first two `jj config set` commands print a warning that the setting applies to future commits only; `jj metaedit --update-author` fixes the one commit that exists.

## Firstmate worktrees

jj does not support git worktrees.
If you run `jj git init --colocate` inside a `git worktree add` directory, jj prints a warning and makes a second jj repository that is not linked to the first one.
Use `jj workspace add` for each additional working copy instead:

```bash
cd <project clone>                       # colocated once, as above
jj workspace add ../<task>-workspace     # one workspace per task
```

Every workspace has its own working copy and shares the repository, its history, and its operation log.
In a colocated repository, jj also creates a git worktree for the new workspace, so `git` works in it.
Remove a workspace with `jj workspace forget <name>`, then delete its directory.

## Never run `jj undo` or `jj op restore`

All workspaces of a repository share one operation log.
`jj undo` and `jj op restore` rewind that log, so they undo the operations of every agent, in every workspace, not only your own.
Agents must never run them.
To fix a mistake in your own work, use the commands that change one commit: `jj abandon`, `jj squash`, `jj restore <path>`, or `jj describe`.
`jj op log` only reads, so it is safe.

## Pushes and no-mistakes

Git refs stay authoritative.
no-mistakes and `git push` read branches and commits, and jj writes both, so neither needs a change.
After a jj command, git's `HEAD` is detached, because jj keeps its working-copy commit in its own history.
Before a step that needs a git branch, such as `/no-mistakes` or `git push`, commit the work and point a bookmark at it:

```bash
jj commit -m "feat: what changed"
jj bookmark set <branch> -r @-
git switch <branch>
```

Then run the step as usual.
Without a bookmark there is no branch for it to push.

## Opt out

Set `jj: false`, or delete the key, in `.local/host.yml`.
Apply stops installing and updating jj.
It leaves the installed `~/.local/bin/jj` in place, as it does for any tool; delete that link to remove it.

To stop using jj in one repository, delete its `.jj/` directory.
Git keeps every branch and commit, because jj wrote them to git.
Forget the extra workspaces first, as in [Firstmate worktrees](#firstmate-worktrees), or remove their git worktrees with `git worktree remove`.
