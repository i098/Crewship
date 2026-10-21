"""Exercise the existing omp guard before a stub GitHub command can run."""

import json
import os
import shlex
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
const child = Bun.spawnSync(["bash", "-c", command], {{ cwd: process.env.GUARD_CWD, stdout: "inherit", stderr: "inherit" }});
process.exit(child.exitCode);
""")
    env = {
        **os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CALLS": str(calls), "GUARD_CWD": str(tmp_path),
    }
    env.pop("CREWSHIP_GITHUB_APPROVED_REPO", None)

    def run(command, *, approved=None, allowed=True, contract="i098/sanctum"):
        child_env = {**env}
        if contract is None:
            child_env.pop("CREWSHIP_GITHUB_REPO", None)
        else:
            child_env["CREWSHIP_GITHUB_REPO"] = contract
        if approved:
            child_env["CREWSHIP_GITHUB_APPROVED_REPO"] = approved
        calls.unlink(missing_ok=True)
        result = subprocess.run(
            ["bun", str(driver), command], env=child_env, capture_output=True, text=True
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
    "gh api -X POST repos/i098/sanctum/issues -f title=regression",
    "gh-axi api POST /repos/i098/sanctum/issues --field title=regression",
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
    "gh api -XDELETE repos/upstream/firstmate/issues/comments/1",
    "gh api repos/upstream/firstmate/issues --raw-field title=regression",
    "GH_REPO=i098/sanctum gh-axi issue create --title regression",
    "/usr/bin/env gh-axi issue create --title regression",
    "bash -lc 'gh-axi issue create --title regression'",
    "gh issue create --title https://github.com/i098/sanctum/issues/1",
    "gh-axi issue comment https://github.com/i098/sanctum/issues/1 --body regression",
    "gh issue comment https://github.com/upstream/firstmate/issues/1 -R i098/sanctum",
    "gh api -X POST 'repos/{owner}/{repo}/issues'",
    "gh api --method=PATCH repos/upstream/firstmate/issues/1",
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
    "issue unpin", "issue develop",
])
def test_mutation_requires_a_target(guarded, cli, subcommand):
    guarded(f"{cli} {subcommand} 1", allowed=False)


@pytest.mark.parametrize("command", [
    "gh-axi issue create --title incident --body regression # -R i098/sanctum",
    "gh issue create --title incident # --help",
    "bash -c 'gh-axi issue create --title incident # -R i098/sanctum'",
    "bash -lc 'gh issue create --title incident # --help'",
    "# -R i098/sanctum\ngh-axi issue create --title incident",
    "gh issue create --title incident # ignored\ngh issue list",
])
def test_shell_comments_cannot_authorize_writes(guarded, command):
    guarded(command, allowed=False)


@pytest.mark.parametrize("body", ["'# -R upstream/firstmate'", '"# text"', r"\#text", "text#suffix"])
def test_quoted_escaped_and_embedded_hashes_remain_arguments(guarded, body):
    guarded(f"gh issue create -R i098/sanctum --body {body}")


def test_command_after_a_comment_is_checked(guarded):
    guarded("# gh issue create\ngh issue create -R i098/sanctum --title incident")


@pytest.mark.parametrize("contract", [None, "i098/sanctum"])
def test_missing_target_blocks_with_or_without_a_contract(guarded, contract):
    guarded("gh-axi issue create --title incident", contract=contract, allowed=False)


def test_explicit_target_without_a_contract_runs(guarded):
    guarded("gh-axi issue create -R upstream/firstmate --title incident", contract=None)


@pytest.mark.parametrize("command", [
    "gh api --allow-escape-sequences -X POST repos/upstream/firstmate/issues -f title=incident",
    "gh api --allow-escape-sequences=false -X POST repos/upstream/firstmate/issues -f title=incident",
    "gh api --unknown-flag -X POST repos/upstream/firstmate/issues -f title=incident",
    "gh api -HAccept:application/json -X POST repos/upstream/firstmate/issues -f title=incident",
    "gh api -pcorsair -X POST repos/upstream/firstmate/issues -f title=incident",
    "gh api -q.id -X POST repos/upstream/firstmate/issues -f title=incident",
    "gh api -t'{{.id}}' -X POST repos/upstream/firstmate/issues -f title=incident",
    "gh api --help=false -X POST repos/upstream/firstmate/issues -f title=incident",
    "gh issue create --help=false --title incident",
    "gh-axi issue create --help=false --title incident",
    "gh issue create --help -h=false --title incident",
    "gh issue create -h --help=false --title incident",
    "gh api -X '$METHOD' repos/upstream/firstmate/issues -f title=incident",
    "gh issue edit 1 --remove-milestone -R upstream/firstmate",
    "gh issue edit 1 --remove-parent -R upstream/firstmate",
    "gh issue edit 1 --remove-type -R upstream/firstmate",
])
def test_flags_cannot_hide_mutations(guarded, command):
    guarded(command, allowed=False)


@pytest.mark.parametrize("flag", [
    "--allow-escape-sequences", "--allow-escape-sequences=false", "-HAccept:application/json",
    "-pcorsair", "-q.id", "-t'{{.id}}'",
])
def test_api_flags_preserve_authorized_targets(guarded, flag):
    guarded(f"gh api {flag} -X POST repos/i098/sanctum/issues -f title=incident")


@pytest.mark.parametrize("flag", ["--remove-milestone", "--remove-parent", "--remove-type"])
def test_issue_boolean_flags_preserve_authorized_targets(guarded, flag):
    guarded(f"gh issue edit 1 {flag} -R i098/sanctum")


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("position", ["1 {url}", "{url} 1"])
@pytest.mark.parametrize("kind", ["issues", "pull"])
def test_every_issue_selector_is_checked(guarded, scheme, position, kind):
    selectors = position.format(url=f"{scheme}://github.com/upstream/firstmate/{kind}/2")
    guarded(f"gh issue edit {selectors} -R i098/sanctum --title changed", allowed=False)


@pytest.mark.parametrize("flag", [
    "--parent", "--add-sub-issue", "--remove-sub-issue", "--add-blocked-by",
    "--remove-blocked-by", "--add-blocking", "--remove-blocking",
])
@pytest.mark.parametrize("value", [
    "http://github.com/upstream/firstmate/issues/2",
    "3,https://github.com/upstream/firstmate/issues/2",
])
def test_every_relationship_target_is_checked(guarded, flag, value):
    guarded(f"gh issue edit 1 -R i098/sanctum {flag} {value}", allowed=False)


@pytest.mark.parametrize("selectors", [
    "1 http://github.com/i098/sanctum/issues/2",
    "https://github.com/i098/sanctum/issues/2 1",
])
def test_multiple_authorized_selectors_run(guarded, selectors):
    guarded(f"gh issue edit {selectors} --title changed")


def test_authorized_relationships_run(guarded):
    guarded(
        "gh issue edit 1 -R i098/sanctum --parent 2 --add-sub-issue 3,4 "
        "--remove-sub-issue 5 --add-blocked-by 6 --remove-blocked-by 7 "
        "--add-blocking http://github.com/i098/sanctum/issues/8 --remove-blocking 9"
    )


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("field", ["--field", "--raw-field"])
@pytest.mark.parametrize("operation", [
    "createIssue", "updateIssue", "closeIssue", "reopenIssue", "deleteIssue", "transferIssue",
    "addComment", "updateIssueComment", "deleteIssueComment", "addSubIssue", "removeSubIssue",
    "addBlockedBy", "removeBlockedBy", "addReaction", "removeReaction", "lockLockable",
    "createLinkedBranch", "deleteLinkedBranch", "clearLabelsFromLabelable",
    "replaceActorsForAssignable", "addRelatesTo", "removeRelatesTo",
])
def test_graphql_issue_writes_require_explicit_approval(guarded, cli, field, operation):
    query = f"mutation {{ {operation}(input: {{id: \"node\"}}) {{ clientMutationId }} }}"
    guarded(
        f"{cli} api graphql {field} {shlex.quote('query=' + query)}",
        allowed=False,
    )


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("payload", [
    "--input payload.json", "--input -", "--field query=@query.graphql",
    "--raw-field query=@query.graphql",
])
def test_opaque_graphql_payloads_require_explicit_approval(guarded, cli, payload):
    guarded(f"{cli} api graphql {payload}", allowed=False)


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
def test_approved_graphql_issue_mutation_runs(guarded, cli):
    query = 'mutation { createIssue(input: {repositoryId: "node", title: "incident"}) { clientMutationId } }'
    guarded(
        f"{cli} api graphql --field {shlex.quote('query=' + query)}",
        approved="upstream/firstmate",
    )


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
def test_graphql_read_runs_without_approval(guarded, cli):
    guarded(f"{cli} api graphql --field 'query=query {{ viewer {{ login }} }}'")


@pytest.mark.parametrize("payload", ["--input payload.json", "--input -", "--field query=@query.graphql"])
def test_approved_opaque_graphql_payload_runs(guarded, payload):
    guarded(f"gh api graphql {payload}", approved="i098/sanctum")


@pytest.mark.parametrize("operation", ["close", "reopen"])
@pytest.mark.parametrize("flag", [
    "-c done", "-cdone", "-c=done", "--comment done",
    "-c https://github.com/upstream/firstmate/issues/2",
])
def test_issue_comment_flags_preserve_authorized_target(guarded, operation, flag):
    guarded(f"gh issue {operation} 5 {flag} -R i098/sanctum")


@pytest.mark.parametrize("operation", ["close", "reopen"])
def test_comment_urls_cannot_supply_issue_targets(guarded, operation):
    guarded(
        f"gh issue {operation} 5 -c https://github.com/i098/sanctum/issues/2",
        allowed=False,
    )


@pytest.mark.parametrize("flag", ["-c", "-c=false", "--checkout"])
def test_develop_checkout_flags_remain_boolean(guarded, flag):
    guarded(f"gh issue develop 5 {flag} -R i098/sanctum")


@pytest.mark.parametrize("command", [
    "gh api -X GET repos/i098/sanctum/issues --unknown-flag",
    "gh api --help=invalid",
])
def test_uncertain_api_flags_block_before_execution(guarded, command):
    guarded(command, allowed=False)
