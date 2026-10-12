# Firstmate patches

Fixes for upstream [Firstmate](https://github.com/kunchenguid/firstmate) that upstream does not have yet. Each apply puts the Firstmate checkout on `origin/main` plus one local commit per file here, in file-name order (`scripts/firstmate-patch-layer.sh`, called from `ansible/tasks/firstmate.yml`).

To add a patch, commit the fix on top of upstream `main` in a Firstmate clone, run `git format-patch -1`, and save the file here as `<next number>-<short name>.patch`. Keep the `From:` line generic: the commit on each host takes its author, date, and message from the file.

[Firstmate patch layer](../../docs/dependencies.md#firstmate-patch-layer) tells what each patch does, how apply handles upstream changes, and how to drop a patch once upstream has it.

To test the board patch against an upstream checkout, set `FIRSTMATE_TEST_SOURCE` to that checkout and run:

```bash
FIRSTMATE_TEST_SOURCE=/path/to/firstmate uv run pytest tests/test_firstmate_patches.py -k crewboard
```

The tests export that checkout's `HEAD` into temporary directories and never change the checkout.
They check patch application, real brief generation, and the supervisor output renderer that session start calls.
They compare board-off output byte for byte and bind a real Unix socket for board-on output.
Without `FIRSTMATE_TEST_SOURCE`, these integration tests skip rather than fetch upstream code during the test suite.

Upstream Firstmate is under the [MIT License](https://github.com/kunchenguid/firstmate/blob/main/LICENSE). These patches change Firstmate code and stay under that license, not the license of this repository.
