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
    "gh issue list", "gh-axi pr view 42", "gh issue create -R i098/sanctum --help",
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


@pytest.mark.parametrize("body", ["'# text'", '"# text"', r"\#text", "text#suffix"])
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


@pytest.mark.parametrize("flag", ["--remove-milestone", "--remove-type"])
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
        "--add-blocking http://github.com/i098/sanctum/issues/8 --remove-blocking 9",
        approved="i098/sanctum",
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
        f"{cli} api graphql {field} {shlex.quote('query=' + query)} # repos/i098/sanctum/",
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
    query = 'mutation { createIssue(input: {repositoryId: "node", title: "https://github.com/upstream/firstmate/issues/1"}) { clientMutationId } }'
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


@pytest.mark.parametrize("flag", ["-h", "--help=true", "--help=1", "--help=t"])
@pytest.mark.parametrize("command", [
    "issue create --title incident --body regression",
    "api -X POST repos/upstream/firstmate/issues --field title=incident",
])
def test_axi_help_lookalikes_do_not_bypass_guard(guarded, flag, command):
    guarded(f"gh-axi {command} {flag}", allowed=False)


@pytest.mark.parametrize("cli,flag", [
    ("gh", "-h"), ("gh", "--help=true"), ("gh", "--help=1"),
    ("gh", "--help=t"), ("gh", "--help"), ("gh-axi", "--help"),
])
def test_each_cli_recognized_help_remains_available(guarded, cli, flag):
    guarded(f"{cli} issue create -R i098/sanctum {flag}")


@pytest.mark.parametrize("flag", [
    "--remove-parent", "--remove-parent=true", "--remove-parent=1",
    "--parent 2", "--parent=https://github.com/i098/sanctum/issues/2",
    "--add-sub-issue 2,3",
])
@pytest.mark.parametrize("approved,allowed", [(None, False), ("i098/other", True), ("invalid", False)])
def test_implicit_parent_targets_require_approval(guarded, flag, approved, allowed):
    guarded(f"gh issue edit 1 -R i098/sanctum {flag}", approved=approved, allowed=allowed)


@pytest.mark.parametrize("flag", ["--remove-parent=false", "--remove-parent=0"])
def test_disabled_parent_removal_needs_no_approval(guarded, flag):
    guarded(f"gh issue edit 1 -R i098/sanctum --title changed {flag}")


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("arguments", [
    "-X POST repos/i098/sanctum/issues/1/sub_issues --field sub_issue_id=123",
    "-X POST repos/i098/sanctum/issues/1/sub_issues --field sub_issue_id=123 --field replace_parent=true",
    "-X DELETE repos/i098/sanctum/issues/1/sub_issue --field sub_issue_id=123",
    "-X PATCH repos/i098/sanctum/issues/1/sub_issues/priority --field sub_issue_id=123 --field after_id=456",
    "-X PATCH repos/i098/sanctum/issues/1/sub_issues/priority --field sub_issue_id=123 --field before_id=456",
    "-X POST repos/i098/sanctum/issues/1/dependencies/blocked_by --field issue_id=123",
    "-X DELETE repos/i098/sanctum/issues/1/dependencies/blocked_by/123",
    "-X POST repos/i098/sanctum/issues/1/sub_issues --input payload.json",
    "-X POST repos/i098/sanctum/issues/1/dependencies/blocked_by --input -",
])
@pytest.mark.parametrize("approved,allowed", [(None, False), ("i098/other", True)])
def test_rest_relationship_targets_require_approval(guarded, cli, arguments, approved, allowed):
    guarded(f"{cli} api {arguments}", approved=approved, allowed=allowed)


@pytest.mark.parametrize("endpoint", [
    "repos/i098/sanctum/issues/1/parent",
    "repos/i098/sanctum/issues/1/sub_issues",
    "repos/i098/sanctum/issues/1/dependencies/blocked_by",
    "repos/i098/sanctum/issues/1/dependencies/blocking",
])
def test_relationship_reads_need_no_approval(guarded, endpoint):
    guarded(f"gh api {endpoint}")


def test_axi_numbered_relationships_keep_explicit_repo(guarded):
    guarded("gh-axi issue subissue add 1 2 -R i098/sanctum")


@pytest.mark.parametrize("shell", [
    "bash -e -c", "sh -e -c", "bash -o pipefail -c", "bash --noprofile --login -c",
    "bash -O extglob -c", "bash --noprofile --norc -ec", "bash -c -e",
    "bash --rcfile /dev/null -c",
])
@pytest.mark.parametrize("target,allowed", [("", False), ("-R i098/sanctum", True)])
def test_nested_shell_options_do_not_hide_writes(guarded, shell, target, allowed):
    command = f'"$GUARD_CWD/gh-axi" issue create --title incident {target}'
    guarded(f"{shell} {shlex.quote(command)}", allowed=allowed)


def test_nested_login_shell_requires_target(guarded):
    guarded("bash --login -c 'gh-axi issue create --title incident'", allowed=False)


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("prefix", ["", "/", "https://api.github.com/"])
@pytest.mark.parametrize("resource", [
    "pulls/42", "pulls/42/comments", "releases/1", "comments/1",
    "branches/main/protection", "labels/bug",
])
def test_non_issue_api_placeholders_remain_outside_guard(guarded, cli, prefix, resource):
    guarded(f"{cli} api -X PATCH '{prefix}repos/{{owner}}/{{repo}}/{resource}' --field body=changed")


@pytest.mark.parametrize("endpoint", [
    "repos/{owner}/{repo}/{resource}", "$ENDPOINT",
    "repos/${OWNER}/${REPO}/pulls/42", "repos/{owner}/{repo}/issues/42",
])
def test_unresolved_api_targets_still_block(guarded, endpoint):
    guarded(f"gh api -X PATCH {shlex.quote(endpoint)} --field title=changed", allowed=False)


@pytest.mark.parametrize("flag", ["--list", "-l", "--list=true", "-l=true", "--list=1", "-l=t"])
def test_develop_listing_with_explicit_target_runs(guarded, flag):
    guarded(f"gh issue develop 1 -R i098/sanctum {flag}")


@pytest.mark.parametrize("flag", [
    "--list=false", "-l=false", "--list=0", "--list=f", "--list -l=false",
])
def test_develop_false_listing_still_requires_target(guarded, flag):
    guarded(f"gh issue develop 1 {flag}", allowed=False)


@pytest.mark.parametrize("separator", [" ", "="])
@pytest.mark.parametrize("first,last,approved,allowed", [
    ("upstream/firstmate", "i098/sanctum", None, False),
    ("upstream/firstmate", "i098/sanctum", "upstream/firstmate", True),
    ("i098/sanctum", "upstream/firstmate", None, True),
])
def test_axi_transfer_checks_first_destination(guarded, separator, first, last, approved, allowed):
    guarded(
        f"gh-axi issue transfer 1 -R i098/sanctum "
        f"--to-repo{separator}{first} --to-repo{separator}{last}",
        approved=approved, allowed=allowed,
    )


@pytest.mark.parametrize("separator", [" ", "="])
@pytest.mark.parametrize("branch_repo,approved,allowed", [
    ("upstream/firstmate", None, False),
    ("upstream/firstmate", "upstream/firstmate", True),
    ("i098/sanctum", None, True),
    ("https://github.com/upstream/firstmate", None, False),
    ("https://github.com/i098/sanctum", None, True),
])
def test_develop_checks_branch_repository(guarded, separator, branch_repo, approved, allowed):
    guarded(
        f"gh issue develop 1 -R i098/sanctum --branch-repo{separator}{branch_repo} --name incident",
        approved=approved, allowed=allowed,
    )


@pytest.mark.parametrize("separator", [" ", "="])
@pytest.mark.parametrize("first,last,allowed", [
    ("upstream/firstmate", "i098/sanctum", True),
    ("i098/sanctum", "upstream/firstmate", False),
])
def test_develop_checks_last_branch_repository(guarded, separator, first, last, allowed):
    guarded(
        f"gh issue develop 1 -R i098/sanctum "
        f"--branch-repo{separator}{first} --branch-repo{separator}{last} --name incident",
        allowed=allowed,
    )


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("script", [
    'value="$({command})"',
    'value="`{command}`"',
    "value=$({command})",
    "value=`{command}`",
    'value="$(printf \'%s\' "$({command})")"',
    'value="\'$({command})\'"',
    'value="${{missing:-$({command})}}"',
    'value="$\\\n({command})"',
    "eval '{command}'",
    "builtin eval '{command}'",
    "command eval '{command}'",
    "eval '{cli}' 'issue create --title incident {target}'",
    "bash -c 'value=\"$({command})\"'",
])
@pytest.mark.parametrize("target,allowed", [
    ("", False), ("-R i098/sanctum", True), ("-R upstream/firstmate", False),
])
def test_executable_shell_regions_check_issue_targets(guarded, cli, script, target, allowed):
    command = f"{cli} issue create --title incident {target}"
    guarded(script.format(command=command, cli=cli, target=target), allowed=allowed)


@pytest.mark.parametrize("script", [
    "printf '%s' '$(gh-axi issue create --title incident)'",
    "printf '%s' '`gh-axi issue create --title incident`'",
    'printf "%s" "\\$(gh-axi issue create --title incident)"',
    'printf "%s" "\\`gh-axi issue create --title incident\\`"',
    "printf '%s' eval 'gh-axi issue create --title incident'",
    "printf '%s' 'eval gh-axi issue create --title incident'",
    "# $(gh-axi issue create --title incident)\nprintf '%s' safe",
    'eval "printf \'%s\' \'\\$(gh-axi issue create --title incident)\'"',
])
def test_raw_issue_write_examples_require_targets(guarded, script):
    guarded(script, allowed=False)


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("script", [
    'value="$(case ready in ready) {command} ;; esac)"',
    'value="$(case ready in (other|ready) {command} ;; esac)"',
    'value="$(case in in (in) {command} ;; esac)"',
    r'value="$(case r\eady in ready) {command} ;; esac)"',
    'value="$(case outer in outer) case ready in ready) {command} ;; esac ;; esac)"',
    "{ eval '{command}'; }",
    "2>/dev/null eval '{command}'",
    "{ 2>/dev/null eval '{command}'; }",
    "2>/dev/null builtin eval '{command}'",
])
@pytest.mark.parametrize("target,allowed", [
    ("", False), ("-R i098/sanctum", True), ("-R upstream/firstmate", False),
])
def test_case_and_prefixed_eval_keep_write_checks(guarded, cli, script, target, allowed):
    command = f"{cli} issue create --title incident {target}"
    guarded(script.replace("{command}", command), allowed=allowed)


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("operator", ["<<", "<<-"])
@pytest.mark.parametrize("delimiter", ["'EOF'", '"EOF"', r"\EOF", "E'OF'"])
def test_quoted_heredoc_examples_require_targets(guarded, cli, operator, delimiter):
    indent = "\t" if operator == "<<-" else ""
    body = f'value="$({cli} issue create --title example)"\neval \'{cli} issue create\'\n'
    indented = "".join(indent + line for line in body.splitlines(keepends=True))
    guarded(f"cat {operator}{delimiter}\n{indented}{indent}EOF", allowed=False)


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("target,allowed", [("", False), ("-R i098/sanctum", True)])
def test_unquoted_heredoc_expansions_are_checked(guarded, cli, target, allowed):
    guarded(
        f"cat <<EOF\n'value=\"$({cli} issue create --title example {target})\"'\nEOF\ngh issue list",
        allowed=allowed,
    )


def test_multiple_and_nested_quoted_heredocs_require_targets(guarded):
    command = (
        "value=\"$(cat <<'INNER'\n$(gh-axi issue create --title example)\nINNER\n)\"\n"
        "cat <<'FIRST' <<\\SECOND\n"
        "gh-axi issue create --title example\nFIRST\n"
        "eval 'gh-axi issue create --title example'\nSECOND\n"
        "gh issue list"
    )
    guarded(command, allowed=False)


def test_printed_eval_issue_write_requires_target(guarded):
    guarded("printf '%s' 2>/dev/null eval 'gh-axi issue create'; gh issue list", allowed=False)


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("arguments", [
    "issue create --title incident",
    "api -X POST repos/{owner}/{repo}/issues --field title=incident",
    'api graphql --field \'query=mutation { createIssue(input: {repositoryId: "node", title: "incident"}) { clientMutationId } }\'',
])
@pytest.mark.parametrize("wrapper", [
    "here_string_then_command", "ansi_delimiter_then_command", "quoted_bash_input",
    "unquoted_sh_input", "piped_input", "here_string", "nested_here_string",
])
def test_raw_guard_covers_all_shell_input_forms(guarded, cli, arguments, wrapper):
    command = f"{cli} {arguments}"
    scripts = {
        "here_string_then_command": f"cat <<< note\n{command}",
        "ansi_delimiter_then_command": f"cat <<$'EOF'\ntext\nEOF\n{command}",
        "quoted_bash_input": f"bash <<'EOF'\n{command}\nEOF",
        "unquoted_sh_input": f"sh -s <<EOF\n{command}\nEOF",
        "piped_input": f"cat <<'EOF' | bash\n{command}\nEOF",
        "here_string": f"bash <<< {shlex.quote(command)}",
        "nested_here_string": f"bash -c {shlex.quote('bash <<< ' + shlex.quote(command))}",
    }
    guarded(scripts[wrapper], allowed=False)


@pytest.mark.parametrize("script", [
    "bash <<'EOF'\ngh-axi issue create -R i098/sanctum --title incident\nEOF",
    "sh -s <<EOF\ngh issue create --repo=i098/sanctum --title incident\nEOF",
    "cat <<'EOF' | bash\ngh-axi issue create -Ri098/sanctum --title incident\nEOF",
    "bash <<< 'gh issue create -R i098/sanctum --title incident'",
    "bash <<< 'gh api -X POST repos/i098/sanctum/issues --field title=incident'",
])
def test_explicit_shell_input_targets_run_locally(guarded, script):
    guarded(script)


def test_targeted_printed_example_runs_without_a_write(guarded, tmp_path):
    result = guarded(
        "cat <<'EOF'\ngh-axi issue create -R i098/sanctum --title example\nEOF\ngh issue list"
    )
    assert result.stdout == "gh-axi issue create -R i098/sanctum --title example\n"
    assert (tmp_path / "calls").read_text() == "issue list\n"


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
@pytest.mark.parametrize("approved,allowed", [(None, False), ("upstream/firstmate", True)])
def test_raw_shell_input_retains_contract_checks(guarded, cli, approved, allowed):
    guarded(
        f"bash <<< '{cli} issue create -R upstream/firstmate --title incident'",
        approved=approved, allowed=allowed,
    )


@pytest.mark.parametrize("cli", ["gh", "gh-axi"])
def test_raw_issue_mutation_still_needs_target_text_with_approval(guarded, cli):
    query = 'mutation { createIssue(input: {repositoryId: "node", title: "incident"}) { clientMutationId } }'
    guarded(
        f"{cli} api graphql --field {shlex.quote('query=' + query)}",
        approved="upstream/firstmate", allowed=False,
    )


@pytest.mark.parametrize("arguments", [
    "gh api repos/upstream/firstmate/issues",
    "gh api --method=GET repos/upstream/firstmate/issues -F page=1",
    "gh api -XHEAD repos/upstream/firstmate/issues",
    "gh-axi api repos/upstream/firstmate/issues --field page=1",
    "gh-axi api GET repos/upstream/firstmate/issues --field page=1",
    "gh-axi api -X HEAD repos/upstream/firstmate/issues",
])
@pytest.mark.parametrize("wrapper", ["{command}", "bash <<< {quoted}", "cat <<'EOF'\n{command}\nEOF\ngh issue list"])
def test_raw_api_reads_do_not_require_contract_approval(guarded, arguments, wrapper):
    guarded(wrapper.format(command=arguments, quoted=shlex.quote(arguments)))


@pytest.mark.parametrize("arguments", [
    "gh api repos/upstream/firstmate/issues -f title=incident",
    "gh api -X POST repos/upstream/firstmate/issues",
    "gh api --method=PATCH repos/upstream/firstmate/issues/1",
    "gh-axi api POST repos/upstream/firstmate/issues --field title=incident",
    "gh-axi api -XDELETE repos/upstream/firstmate/issues/1",
])
@pytest.mark.parametrize("wrapper", ["{command}", "bash <<< {quoted}", "cat <<'EOF'\n{command}\nEOF\ngh issue list"])
def test_raw_api_writes_still_require_contract_approval(guarded, arguments, wrapper):
    guarded(wrapper.format(command=arguments, quoted=shlex.quote(arguments)), allowed=False)


def test_api_read_does_not_hide_a_later_write(guarded):
    guarded(
        "gh api -X GET repos/upstream/firstmate/issues; "
        "gh api -X POST repos/upstream/firstmate/issues --field title=incident",
        allowed=False,
    )
