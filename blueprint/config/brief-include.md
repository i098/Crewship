For parallel slices of one feature, merge them into one feature branch. Validate that branch once and open one pull request. Do not start a validation run per slice.
When your worktree is the Crewship repo, query past runs with their post-mortem notes with `bun tools/runs-tui/runs-tui.ts --json --all`. It prints one JSON document.
Before you send a board link (a Lavish board, a diagram or a PR preview), run `board-phone-fit BOARD.html`. Fix each failure and run it again until it passes.
