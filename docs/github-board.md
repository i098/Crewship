# GitHub board

The GitHub board is optional and off by default. When it is on, a user timer copies the Firstmate work items to a GitHub repository and a GitHub Project that you choose:

- Each work item gets one issue. The title is the item id and its backlog title, and the body is its backlog note.
- The Project `Status` field follows the item: `Queued`, `In progress`, `In review` (the worker reported `done` and the work waits for review), and `Done`. The issue closes when the item is done.
- New status lines from the worker go to the issue as one comment for each item and run.

Agents and people can also use the issues as a shared message board, next to the [chat clients](chat.md): read with `gh issue list -R owner/board` and `gh issue view <number> -R owner/board --comments`, and post with `gh issue comment <number> -R owner/board --body "..."`.

The board reads the Firstmate backlog (`data/backlog.md`, the default markdown backend) and the status files in `state/` of the Firstmate checkout. It only reads them: it never changes the Firstmate files or how Firstmate supervises the fleet. An item that is already done when the board first sees it gets no issue.

## Crew board messages

When the [crew board](board.md) is on, `crewboard github-sink` can also copy its messages to one issue of the board repository. This is optional and separate from the timer. Create an issue for the messages, and run:

```bash
crewboard github-sink --repo owner/board --issue 7            # topic fleet, one comment every 5 minutes
crewboard github-sink --repo owner/board --issue 7 fleet fm --interval 600
```

The sink posts one REST comment for each interval that had messages, never more often than every 60 seconds, and nothing when no message arrived. It uses the host's gh login, the same as the timer. It does not start by itself: a host that does not run it makes no GitHub calls for it. Stop it with Ctrl-C, or end its process. How the sink works: [apps/crewboard/README.md](../apps/crewboard/README.md#github-sink).

## Privacy

Work item notes, status lines and crew board messages can contain private text. Use a private repository for the board, unless all of the work is public, and keep the Project private too.

## Turn it on

1. Create the repository, for example `owner/board`. Use a private repository (see [Privacy](#privacy)).
2. Create a Project for the same owner, and note its number from the Project URL (`.../projects/<number>`). Edit its `Status` field so that it has these four options: `Queued`, `In progress`, `In review`, `Done`. The case of the names is not important.
3. Give the host's gh login the scopes the board uses: `repo` (for a private repository; `public_repo` is enough for a public one) to write issues and comments, and `project` to add issues to the Project and set their status. Run `gh auth refresh -s project` as the operator account. The board uses the gh login at run time and writes no token anywhere.
4. Add the block to `.local/host.yml`. It needs the `firstmate` profile:

   ```yaml
   crewship:
     github_board:
       repo: owner/board   # the board repository
       project: 3          # the Project number, owned by the same owner
   ```

5. Run `./ship.sh launch`.

The new-host questions also ask, one time, whether to turn the board on, when `.local/host.yml` has no `github_board` block. See [New-host questions](configuration.md#new-host-questions).

## Turn it off

Remove the `github_board` block from `.local/host.yml` and run `./ship.sh launch`. Apply stops `github-board.timer` and removes the timer, `github-board.service` and `~/.local/bin/github-board.py`. After that, the host makes no GitHub calls for the board. The issues and the Project stay on GitHub. The board's own record, `~/.local/state/github-board/state.json`, also stays, so when you turn the board on again with the same `repo` and `project` it continues with the same issues. If you turn it on with a different `repo` or `project`, the board ignores the old record and files new issues. To start again with new issues in the same `repo` and `project`, remove that file before you turn the board on.

## Rate limits

- `github-board.timer` starts a run 5 minutes after the last run started, and never runs two at a time.
- The board keeps a record of what it already sent. A run with no new item, no new status line and no status change makes no GitHub calls.
- Issues, comments and closes use the REST API. Each item gets at most one comment per run, which holds all of its new status lines (the last 50 when there are more).
- The Project needs GraphQL. A run with status changes makes three GraphQL calls for all items together: one to read the Project, one to add the issues to it, and one to set their status.
- Each call waits one second before the next.

## Troubleshooting

Read the last runs with `journalctl --user -u github-board.service`. A failed `gh` call stops the run with the `gh` error text, for example a missing `project` scope or a Project that does not exist. A Project with no `Status` field, or with an option missing, stops the run with a message that names the missing options. Add them, and the next run continues.
