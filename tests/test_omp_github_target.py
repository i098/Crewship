"""Run the installed gh guard wrapper through PATH and bash in front of a recording stub."""

import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("provisions", ROOT / "scripts/provisions.py")
provisions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provisions)

CONTRACT = "i098/sanctum"
UPSTREAM = "upstream/firstmate"

STUB = f"""#!{sys.executable}
import json, os, sys
record = {{"argv": sys.argv[1:], "cwd": os.getcwd(), "probe": os.environ.get("GH_PROBE")}}
if os.environ.get("GH_STUB_STDIN"):
    record["stdin"] = sys.stdin.read()
with open(os.environ["GH_STUB_CALLS"], "a") as calls:
    calls.write(json.dumps(record) + "\\n")
sys.exit(int(os.environ.get("GH_STUB_STATUS", "0")))
"""

AXI = f"""#!{sys.executable}
import os, sys
words, repo = sys.argv[1:], None
rest = []
while words:
    word = words.pop(0)
    if word in ("-R", "--repo"):
        repo = words.pop(0)
    elif word.startswith("--repo="):
        repo = word[7:]
    elif word.startswith("-R="):
        repo = word[3:]
    else:
        rest.append(word)
repo = repo if repo is not None else os.environ.get("GH_REPO")
if rest[:1] == ["api"]:
    if len(rest) > 1 and rest[1] in ("GET", "HEAD", "POST", "PATCH", "PUT", "DELETE"):
        rest[1:2] = ["-X", rest[1]]
    elif not any(word.startswith("-X") for word in rest):
        rest[1:1] = ["-X", "GET"]
os.execvp("gh", ["gh", *rest, *(["--repo", repo] if repo else [])])
"""


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    real = home / ".local/share/crewship/tools/gh/2.0.0/x86_64/gh_2.0.0/bin/gh"
    real.parent.mkdir(parents=True)
    real.write_text(STUB)
    real.chmod(0o755)
    provisions.install_gh_guard(home, real)
    shims = tmp_path / "shims"
    shims.mkdir()
    (shims / "gh-axi").write_text(AXI)
    (shims / "gh-axi").chmod(0o755)
    (tmp_path / "work").mkdir()
    return home


@pytest.fixture
def run(home, tmp_path):
    calls = tmp_path / "calls.jsonl"
    base = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("CREWSHIP_GITHUB_", "GH_"))
    }
    base["PATH"] = f"{home / '.local/bin'}:{tmp_path / 'shims'}:{base['PATH']}"
    base["GH_STUB_CALLS"] = str(calls)

    def run(script, *, contract=CONTRACT, approved=None, stdin=None, **extra):
        env = {**base, **extra}
        if contract:
            env["CREWSHIP_GITHUB_REPO"] = contract
        if approved:
            env["CREWSHIP_GITHUB_APPROVED_REPO"] = approved
        calls.unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", "-c", script], cwd=tmp_path / "work", env=env, input=stdin,
            capture_output=True, text=True, timeout=30,
        )
        result.calls = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        return result

    return run


def assert_blocked(result):
    assert result.calls == [], result.stderr
    assert result.returncode == 2
    assert "Blocked:" in result.stderr


def assert_ran(result, command, work):
    assert result.returncode == 0, result.stderr
    assert [call["argv"] for call in result.calls] == [shlex.split(command)]
    assert result.calls[0]["cwd"] == str(work)


def check(run, tmp_path, command, allowed, **options):
    result = run(f"gh {command}", **options)
    if allowed:
        assert_ran(result, command, tmp_path / "work")
    else:
        assert_blocked(result)


def test_argv_cwd_env_stdin_and_status_pass_through(run, tmp_path):
    (tmp_path / "work/sub").mkdir()
    argv = ["issue", "create", "-R", CONTRACT, "--title", "two words", "--body", "$x 'q' \\n"]
    result = run(
        f"cd sub && gh {shlex.join(argv)}", stdin="piped input\n",
        GH_STUB_STDIN="1", GH_STUB_STATUS="7", GH_PROBE="kept",
    )
    assert result.returncode == 7
    assert result.calls == [{
        "argv": argv, "cwd": str(tmp_path / "work/sub"), "probe": "kept", "stdin": "piped input\n",
    }]


def test_real_gh_link_cannot_recurse_through_local_bin(home, run):
    real = home / ".local/share/crewship/gh-guard/gh-real"
    real.unlink()
    real.symlink_to(home / ".local/bin/gh")
    result = run("gh issue list")
    assert result.returncode == 2
    assert result.calls == []


def test_original_missing_target_incident_blocks(run):
    assert_blocked(run("gh-axi issue create --title incident --body regression"))


@pytest.mark.parametrize("script", [
    "cd /tmp && gh issue create --title incident",
    "bash <<< 'gh issue create --title incident'",
    "bash <<'EOF'\ngh issue create --title incident\nEOF",
    "cat <<'EOF' | bash\ngh-axi issue create --title incident\nEOF",
    'value="$(gh issue create --title incident)"',
    "value=`gh-axi issue create --title incident`",
    "eval 'gh issue create --title incident'",
    "bash -c 'gh-axi issue create --title incident'",
    "GH_REPO=i098/sanctum gh issue create --title incident",
    "gh issue create --title incident # -R i098/sanctum",
])
def test_missing_target_blocks_in_every_shell_form(run, script):
    result = run(script)
    assert result.calls == [], result.stderr
    assert "Blocked:" in result.stderr


@pytest.mark.parametrize("script", [
    "cd /tmp && gh issue create -R i098/sanctum --title incident",
    "bash <<< 'gh issue create -R i098/sanctum --title incident'",
    "bash <<'EOF'\ngh issue create --repo=i098/sanctum --title incident\nEOF",
    'value="$(gh issue create -R i098/sanctum --title incident)"',
    "eval 'gh issue create -R i098/sanctum --title incident'",
])
def test_explicit_target_runs_in_every_shell_form(run, script):
    result = run(script)
    assert result.returncode == 0, result.stderr
    assert len(result.calls) == 1
    assert result.calls[0]["argv"][:2] == ["issue", "create"]


@pytest.mark.parametrize("script", [
    "gh issue list -R i098/sanctum; gh issue create --title incident",
    "gh issue list -R i098/sanctum\nbash <<< 'gh issue create --title incident'",
    "gh api repos/i098/sanctum/issues && gh api -X POST 'repos/{owner}/{repo}/issues' -f title=x",
    "bash <<< 'gh-axi issue create --title incident'; gh issue list -R i098/sanctum",
])
def test_read_target_does_not_authorize_another_write(run, script):
    result = run(script)
    assert len(result.calls) == 1, result.stderr
    assert result.calls[0]["argv"][1] in {"list", "repos/i098/sanctum/issues"}
    assert "Blocked:" in result.stderr


@pytest.mark.parametrize("command,options,allowed", [
    ("issue create -R i098/sanctum --title x", {}, True),
    ("issue create -Ri098/sanctum --title x", {}, True),
    ("issue create -R upstream/firstmate --title x", {}, False),
    ("issue create -R upstream/firstmate --title x", {"approved": UPSTREAM}, True),
    ("issue create -R upstream/firstmate --title x", {"approved": "upstream/other"}, False),
    ("issue create -R upstream/firstmate --title x", {"contract": None}, True),
    ("issue create --title x", {"contract": None}, False),
    ("issue create -R upstream/firstmate -R i098/sanctum --title x", {}, True),
    ("issue create -R i098/sanctum -R upstream/firstmate --title x", {}, False),
])
def test_contract_and_approval(run, tmp_path, command, options, allowed):
    check(run, tmp_path, command, allowed, **options)


@pytest.mark.parametrize("text", [
    "-R upstream/firstmate", "--repo=i098/other", "https://github.com/upstream/firstmate/issues/2",
    "repos/upstream/firstmate/issues/2",
])
def test_title_body_and_comment_text_never_affect_targets(run, tmp_path, text):
    quoted = shlex.quote(text)
    check(run, tmp_path, f"issue create -R i098/sanctum --title {quoted} --body {quoted}", True)
    check(run, tmp_path, f"issue close 5 -R i098/sanctum -c {quoted}", True)
    check(run, tmp_path, f"issue create --title {quoted} --body {quoted}", False)
    check(run, tmp_path, f"issue close 5 -c {quoted}", False)


@pytest.mark.parametrize("command,options,allowed", [
    ("issue transfer 1 upstream/firstmate -R i098/sanctum", {}, False),
    ("issue transfer 1 upstream/firstmate -R i098/sanctum", {"approved": UPSTREAM}, True),
    ("issue transfer 1 i098/sanctum -R i098/sanctum", {}, True),
    ("issue develop 1 -R i098/sanctum --branch-repo upstream/firstmate --name x", {}, False),
    ("issue develop 1 -R i098/sanctum --branch-repo=upstream/firstmate", {"approved": UPSTREAM}, True),
    ("issue develop 1 -R i098/sanctum --branch-repo https://github.com/i098/sanctum", {}, True),
    ("issue develop 1 -R i098/sanctum --branch-repo upstream/firstmate --branch-repo i098/sanctum", {}, True),
    ("issue develop 1 -R i098/sanctum --branch-repo i098/sanctum --branch-repo upstream/firstmate", {}, False),
    ("issue develop 1 --list", {}, True),
    ("issue develop 1 -l", {}, True),
    ("issue develop 1 --list=false", {}, False),
    ("issue create --title x --help", {}, True),
    ("issue create --title x -h", {}, True),
    ("issue create --title x --help=true", {}, True),
    ("issue create --title x --help=false", {}, False),
])
def test_destinations_listing_and_help(run, tmp_path, command, options, allowed):
    check(run, tmp_path, command, allowed, **options)


@pytest.mark.parametrize("command,options,allowed", [
    ("issue edit https://github.com/i098/sanctum/issues/2 --title x", {}, True),
    ("issue edit https://github.com/i098/sanctum/issues/2 -R upstream/firstmate --title x", {}, True),
    ("issue edit https://github.com/upstream/firstmate/issues/2 -R i098/sanctum --title x", {"approved": UPSTREAM}, True),
    ("issue edit 1 2 -R i098/sanctum --title x", {}, True),
    ("issue edit 1 https://github.com/upstream/firstmate/issues/2 -R i098/sanctum --title x", {}, False),
    ("issue edit https://github.com/i098/sanctum/issues/2 http://github.com/upstream/firstmate/pull/3 --title x", {}, False),
    ("issue comment https://github.com/upstream/firstmate/issues/1 -R i098/sanctum --body x", {}, False),
    ("issue edit 1 -R i098/sanctum --add-blocked-by https://github.com/upstream/firstmate/issues/2", {}, False),
    ("issue edit 1 -R i098/sanctum --add-blocking 3,https://github.com/upstream/firstmate/issues/2", {}, False),
    ("issue edit 1 -R i098/sanctum --add-blocking https://github.com/i098/sanctum/issues/2", {}, True),
    ("issue edit 1 -R i098/sanctum --parent 2", {}, False),
    ("issue edit 1 -R i098/sanctum --remove-parent", {}, False),
    ("issue edit 1 -R i098/sanctum --parent 2", {"approved": "i098/other"}, True),
    ("issue edit 1 -R i098/sanctum --title x --remove-parent=false", {}, True),
])
def test_selectors_and_relationship_targets(run, tmp_path, command, options, allowed):
    check(run, tmp_path, command, allowed, **options)


@pytest.mark.parametrize("command,options,allowed", [
    ("api repos/upstream/firstmate/issues", {}, True),
    ("api -X GET repos/upstream/firstmate/issues -f page=1", {}, True),
    ("api repos/upstream/firstmate/issues -f title=x", {}, False),
    ("api repos/upstream/firstmate/issues -f title=x", {"approved": UPSTREAM}, True),
    ("api -X POST repos/upstream/firstmate/issues", {}, False),
    ("api --method=PATCH repos/upstream/firstmate/issues/1", {}, False),
    ("api -XDELETE repos/upstream/firstmate/issues/comments/1", {}, False),
    ("api -X POST repos/i098/sanctum/issues -f title=x", {}, True),
    ("api -X POST /repos/i098/sanctum/issues/1/comments -f body=x", {}, True),
    ("api 'repos/{owner}/{repo}/issues'", {}, True),
    ("api -X POST 'repos/{owner}/{repo}/issues' -f title=x", {}, False),
    ("api -X PATCH '$ENDPOINT' -f title=x", {}, False),
    ("api -X PATCH 'repos/{owner}/{repo}/pulls/42' -f body=x", {}, True),
    ("api -X POST repos/upstream/firstmate/pulls/42/comments -f body=x", {}, True),
    ("api -X POST 'repos/{owner}/{repo}/commits/abc/comments' -f body=x", {}, True),
    ("api -X PATCH https://api.github.com/repos/upstream/firstmate/comments/1 -f body=x", {}, True),
    ("api --unknown-flag -X POST repos/i098/sanctum/issues", {}, False),
])
def test_rest_api_methods_and_paths(run, tmp_path, command, options, allowed):
    check(run, tmp_path, command, allowed, **options)


@pytest.mark.parametrize("arguments", [
    "-X POST repos/i098/sanctum/issues/1/sub_issues -F sub_issue_id=123",
    "-X DELETE repos/i098/sanctum/issues/1/sub_issue -F sub_issue_id=123",
    "-X POST repos/i098/sanctum/issues/1/dependencies/blocked_by --input payload.json",
])
@pytest.mark.parametrize("approved,allowed", [(None, False), ("i098/other", True)])
def test_rest_relationship_ids_require_approval(run, tmp_path, arguments, approved, allowed):
    check(run, tmp_path, f"api {arguments}", allowed, approved=approved)


CREATE_ISSUE = 'query=mutation { createIssue(input: {repositoryId: "x"}) { clientMutationId } }'


@pytest.mark.parametrize("arguments,approved,allowed", [
    (f"--field {shlex.quote(CREATE_ISSUE)}", None, False),
    (f"-f {shlex.quote(CREATE_ISSUE)}", UPSTREAM, True),
    ("--input payload.json", None, False),
    ("--input payload.json", CONTRACT, True),
    ("-F query=@query.graphql", None, False),
    ("-f 'query=query { viewer { login } }'", None, True),
    ("-f 'query=mutation { mergePullRequest(input: {}) { clientMutationId } }'", None, True),
])
def test_graphql_issue_writes_and_opaque_input_need_approval(run, tmp_path, arguments, approved, allowed):
    check(run, tmp_path, f"api graphql {arguments}", allowed, approved=approved)


@pytest.mark.parametrize("script,argv", [
    ("gh-axi issue create -R i098/sanctum --title x", ["issue", "create", "--title", "x", "--repo", CONTRACT]),
    ("gh-axi pr view 42", ["pr", "view", "42"]),
    ("gh-axi api POST repos/i098/sanctum/issues --field title=x",
     ["api", "-X", "POST", "repos/i098/sanctum/issues", "--field", "title=x"]),
    ("GH_REPO=i098/sanctum gh-axi issue create --title x",
     ["issue", "create", "--title", "x", "--repo", CONTRACT]),
    ("gh-axi api repos/upstream/firstmate/issues --field page=1",
     ["api", "-X", "GET", "repos/upstream/firstmate/issues", "--field", "page=1"]),
])
def test_gh_axi_transport_reaches_real_gh_with_translated_argv(run, tmp_path, script, argv):
    result = run(script)
    assert result.returncode == 0, result.stderr
    assert result.calls == [{"argv": argv, "cwd": str(tmp_path / "work"), "probe": None}]


@pytest.mark.parametrize("script", [
    "gh-axi issue create -R upstream/firstmate --title x",
    "gh-axi api POST repos/upstream/firstmate/issues --field title=x",
    "GH_REPO=upstream/firstmate gh-axi issue create --title x",
])
def test_gh_axi_writes_block_before_real_gh(run, script):
    assert_blocked(run(script))


def test_approved_upstream_write_ignores_unrelated_body_repository(run, tmp_path):
    check(
        run, tmp_path,
        "issue create -R upstream/firstmate --title fix "
        "--body 'See https://github.com/python/cpython/issues/1'",
        True, approved=UPSTREAM,
    )


@pytest.mark.parametrize("script,expected", [
    ("cat <<'EOF'\ngh-axi issue create --title example\nEOF", "gh-axi issue create --title example\n"),
    ("printf '%s' 'gh issue create --title example'", "gh issue create --title example"),
])
def test_printing_issue_examples_does_not_invoke_guard(run, script, expected):
    result = run(script)
    assert (result.returncode, result.stdout, result.calls) == (0, expected, [])


@pytest.mark.parametrize("command", [
    "issue view 1 --comments",
    "issue list --app x",
    "issue view 1 -R upstream/firstmate --comments",
])
def test_read_only_issue_flags_pass_to_real_gh(run, tmp_path, command):
    check(run, tmp_path, command, True)


@pytest.mark.parametrize("command", [
    "issue create -R i098/sanctum --future-option value --title incident",
    "issue edit 1 -R i098/sanctum --future-boolean --title incident",
])
def test_unknown_write_flags_still_block_before_real_gh(run, tmp_path, command):
    check(run, tmp_path, command, False)


@pytest.mark.parametrize("approved,allowed", [(None, False), (CONTRACT, True)])
def test_observed_gh_axi_subissue_calls_require_mutation_approval(run, tmp_path, approved, allowed):
    lookup = [
        "api", "graphql", "-f",
        'query=query { repository(owner: "i098", name: "sanctum") { parent: issue(number: 1) { id number } c0: issue(number: 2) { id number } } }',
    ]
    mutation = [
        "api", "graphql", "-f",
        'query=mutation { addSubIssue(input: { issueId: "I_parent", subIssueId: "I_child" }) { subIssue { number } } }',
    ]
    script = shlex.join(["gh", *lookup]) + "; " + shlex.join(["gh", *mutation])
    result = run(script, approved=approved)
    assert result.returncode == (0 if allowed else 2)
    expected = [lookup, mutation] if allowed else [lookup]
    assert [call["argv"] for call in result.calls] == expected
    assert all(call["cwd"] == str(tmp_path / "work") for call in result.calls)
    if not allowed:
        assert "Blocked:" in result.stderr
