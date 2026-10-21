"""Exercise the existing omp guard before a stub GitHub command can run."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
EXTENSION = ROOT / "blueprint/config/omp-no-pattern-kill.ts"
pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


@pytest.fixture
def guarded(tmp_path):
    calls = tmp_path / "calls"
    stub = tmp_path / "gh"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
    stub.chmod(0o755)
    (tmp_path / "gh-axi").symlink_to(stub)
    driver = tmp_path / "guard.ts"
    driver.write_text(f"""
import extension from {json.dumps(str(EXTENSION))};
let handler;
extension({{ on: (_event, callback) => {{ handler = callback; }} }});
const command = process.argv[2];
const result = await handler({{ toolName: "bash", input: {{ command }} }});
if (result.block) {{
    console.error(result.reason);
    process.exit(1);
}}
const child = Bun.spawnSync(["bash", "-c", command], {{ stdout: "inherit", stderr: "inherit" }});
process.exit(child.exitCode);
""")
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "CALLS": str(calls)}
    env["CREWSHIP_GITHUB_REPO"] = "i098/sanctum"
    env.pop("CREWSHIP_GITHUB_APPROVED_REPO", None)

    def run(command, *, approved=None, allowed=True):
        if approved:
            env["CREWSHIP_GITHUB_APPROVED_REPO"] = approved
        result = subprocess.run(
            ["bun", str(driver), command], env=env, capture_output=True, text=True
        )
        assert (result.returncode == 0) is allowed, result.stderr
        assert calls.exists() is allowed, result.stderr
        if not allowed:
            assert "Blocked:" in result.stderr
        return result

    return run


def test_original_missing_target_never_reaches_gh(guarded):
    guarded("gh-axi issue create --title incident --body regression", allowed=False)


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("target", ["-R i098/sanctum", "--repo=i098/sanctum"])
def test_explicit_contract_target_runs(guarded, cli, target):
    guarded(f"{cli} issue create {target} --title regression")


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
def test_mismatch_never_reaches_gh(guarded, cli):
    guarded(f"{cli} issue create -R upstream/firstmate --title regression", allowed=False)


def test_exact_upstream_approval_runs(guarded):
    guarded(
        "gh-axi issue create -R upstream/firstmate --title regression",
        approved="upstream/firstmate",
    )


def test_unrelated_approval_does_not_authorize_upstream(guarded):
    guarded(
        "gh issue create -R upstream/firstmate --title regression",
        approved="upstream/another",
        allowed=False,
    )


@pytest.mark.parametrize("command", [
    "gh issue list", "gh-axi pr view 42", "gh issue create --help",
    "gh api repos/upstream/firstmate/issues",
    "gh api -X GET repos/upstream/firstmate/issues -f page=1",
    "gh-axi api repos/upstream/firstmate/issues --field page=1",
    "gh-axi issue subissue list 16",
])
def test_reads_run_without_a_target_or_approval(guarded, command):
    guarded(command)


@pytest.mark.parametrize("command", [
    "gh issue comment https://github.com/i098/sanctum/issues/1 --body regression",
    "gh pr close https://github.com/i098/sanctum/pull/2",
    "gh api -X POST repos/i098/sanctum/issues -f title=regression",
    "gh-axi api POST /repos/i098/sanctum/issues --field title=regression",
    "gh api -XPUT /repos/i098/sanctum/pulls/1",
    "gh -Ri098/sanctum issue create --title regression",
    "gh-axi issue create -R=i098/sanctum --title regression",
    "gh-axi api -X=PATCH /repos/i098/sanctum/issues/1 --input payload.json",
    "gh issue create --title ';' -R i098/sanctum",
    "gh issue create --body '\\>' -R i098/sanctum",
    "gh issue create > /dev/null --title regression -R i098/sanctum",
    "gh issue create 2>/dev/null --title regression -R i098/sanctum",
    "gh issue create --title regression -R i098/sanctum 2>&1",
    "gh \\\n issue create --title regression -R i098/sanctum",
])
def test_explicit_urls_and_api_paths_run(guarded, command):
    guarded(command)


@pytest.mark.parametrize("command", [
    "gh issue create --body 'use -R i098/sanctum'",
    "gh issue create --body --help",
    "gh api -X PATCH 'repos/{owner}/{repo}/issues/1' -R i098/sanctum",
    "gh api -X PUT repos/upstream/firstmate/pulls/1",
    "gh api -XDELETE repos/upstream/firstmate/issues/comments/1",
    "gh api repos/upstream/firstmate/comments/1 -F body=regression",
    "gh api repos/upstream/firstmate/issues --raw-field title=regression",
    "gh-axi api DELETE /repos/upstream/firstmate/comments/1",
    "gh-axi api -X=PUT /repos/upstream/firstmate/pulls/1",
    "GH_REPO=i098/sanctum gh-axi issue create --title regression",
    "/usr/bin/env gh-axi issue create --title regression",
    "bash -lc 'gh-axi issue create --title regression'",
    "gh issue create --title https://github.com/i098/sanctum/issues/1",
    "gh-axi issue comment https://github.com/i098/sanctum/issues/1 --body regression",
    "gh issue comment https://github.com/upstream/firstmate/issues/1 -R i098/sanctum",
    "gh pr create --repo i098/sanctum --repo upstream/firstmate",
    "gh api -X POST 'repos/{owner}/{repo}/issues'",
    "gh api --method=PATCH repos/upstream/firstmate/issues/1",
    "gh api repos/upstream/firstmate/pulls/1/comments -f body=regression",
    "gh api repos/upstream/firstmate/issues --input payload.json",
    "gh-axi api POST repos/upstream/firstmate/issues",
    "gh-axi api -X DELETE repos/upstream/firstmate/issues/comments/1",
    "gh issue transfer 1 upstream/firstmate -R i098/sanctum",
    "gh-axi issue transfer 1 --to-repo upstream/firstmate -R i098/sanctum",
    "cd /tmp; gh-axi issue create --title regression",
    "bash -c 'gh-axi issue create --title regression'",
    "gh api -i repos/upstream/firstmate/issues -f title=regression",
    "gh issue create -R i098/sanctum --title regression --body ';' --repo upstream/firstmate",
    "gh issue create -R i098/sanctum --title regression --body \\; --repo upstream/firstmate",
    "gh api -X POST > /dev/null repos/upstream/firstmate/issues -f title=regression",
    "gh api -X POST 2>/dev/null repos/upstream/firstmate/issues -f title=regression",
    "gh-axi issue subissue add 16 20 -R upstream/firstmate",
    "gh-axi issue subissue remove 16 20",
])
def test_ambiguous_or_outside_targets_never_run(guarded, command):
    guarded(command, allowed=False)


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("subcommand", [
    "issue create", "issue edit", "issue comment", "issue close", "issue reopen",
    "issue delete", "issue transfer", "issue lock", "issue unlock", "issue pin",
    "issue unpin", "issue develop", "pr create", "pr comment", "pr edit", "pr close",
    "pr reopen", "pr merge", "pr review", "pr ready",
])
def test_mutation_requires_a_target(guarded, cli, subcommand):
    guarded(f"{cli} {subcommand} 1", allowed=False)
