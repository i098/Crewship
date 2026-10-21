"""Run the installed gh and gh-axi guard wrappers through PATH and bash in front of recording stubs."""

import importlib.util
import json
import os
import shlex
import shutil
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
R = ["--repo", CONTRACT]

STUB = f"""#!{sys.executable}
import json, os, sys
record = {{"argv": sys.argv[1:], "cwd": os.getcwd(), "probe": os.environ.get("GH_PROBE")}}
if os.environ.get("GH_STUB_STDIN"):
    record["stdin"] = sys.stdin.read()
with open(os.environ["GH_STUB_CALLS"], "a") as calls:
    calls.write(json.dumps(record) + "\\n")
sys.exit(int(os.environ.get("GH_STUB_STATUS", "0")))
"""

LOOKUP = "query=query { repository { parent: issue(number: 1) { id } } }"
TYPES = "query=query { repository { issueTypes(first: 25) { nodes { id name } } } }"
TYPE_MUTATION = "query=mutation($id:ID!){updateIssue(input:{id:$id,issueTypeId:null}){issue{id}}}"

AXI = f"#!{sys.executable}\n" + r"""
import json, os, subprocess, sys
LOOKUP, TYPES, TYPE_MUTATION = AXI_CONSTANTS
argv = sys.argv[1:]
with open(os.environ["AXI_STARTS"], "a") as starts:
    starts.write(json.dumps(argv) + "\n")
if "--help" in argv or argv in (["--version"], ["-v"], ["-V"]):
    print("help")
    sys.exit(0)
rest, repo, i = [], None, 0
while i < len(argv):
    word = argv[i]
    if word in ("-R", "--repo", "--hostname") and i + 1 < len(argv):
        repo = argv[i + 1] if word != "--hostname" else repo
        i += 2
        continue
    if word.startswith(("-R=", "--repo=")):
        repo = word.split("=", 1)[1]
    elif not word.startswith("--hostname="):
        rest.append(word)
    i += 1
repo = repo or os.environ.get("GH_REPO")
context = ["--repo", repo] if repo else []

def gh(*args, context=context):
    code = subprocess.run(["gh", *args, *context]).returncode
    if code:
        sys.exit(code)

if rest[:1] == ["api"]:
    args, method = rest[1:], None
    for index, word in enumerate(args):
        if word == "-X":
            method = args[index + 1]
            del args[index:index + 2]
            break
        if word.startswith("-X="):
            method = word[3:]
            del args[index]
            break
    if args and args[0].upper() in ("GET", "HEAD", "POST", "PATCH", "PUT", "DELETE"):
        method = args.pop(0)
    gh("api", args.pop(0), "--method", (method or "GET").upper(), *args)
elif rest[:2] == ["issue", "subissue"] and rest[2:3] in (["add"], ["remove"]):
    gh("api", "graphql", "-f", LOOKUP, context=[])
    name = "addSubIssue" if rest[2] == "add" else "removeSubIssue"
    gh("api", "graphql", "-f", "query=mutation { %s(input: {}) { clientMutationId } }" % name, context=[])
elif rest[:1] == ["issue"] and ("--type" in rest or "--no-type" in rest):
    if "--type" in rest:
        gh("api", "graphql", "-f", TYPES, context=[])
        del rest[rest.index("--type"):rest.index("--type") + 2]
    else:
        rest.remove("--no-type")
    gh(*rest)
    gh("api", "graphql", "-f", "id=I_1", "-f", TYPE_MUTATION, context=[])
elif rest[:2] == ["issue", "transfer"]:
    gh("issue", "transfer", rest[2], rest[rest.index("--to-repo") + 1])
else:
    if rest[:1] == ["issue"] and rest[1:2] in (["close"], ["reopen"], ["lock"], ["unlock"], ["pin"], ["unpin"]):
        gh("issue", "view", rest[2], "--json", "state")
    gh(*rest)
""".replace("AXI_CONSTANTS", repr((LOOKUP, TYPES, TYPE_MUTATION)))


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    real = home / ".local/share/crewship/tools/gh/2.0.0/x86_64/gh_2.0.0/bin/gh"
    real.parent.mkdir(parents=True)
    real.write_text(STUB)
    real.chmod(0o755)
    provisions.install_gh_guard(home, real)
    axi = tmp_path / "packages/gh-axi/dist/bin/gh-axi.js"
    axi.parent.mkdir(parents=True)
    axi.write_text(AXI)
    axi.chmod(0o755)
    provisions.install_gh_guard(home, axi, "gh-axi")
    (tmp_path / "work").mkdir()
    return home


@pytest.fixture
def run(home, tmp_path):
    calls, starts = tmp_path / "calls.jsonl", tmp_path / "axi-starts.jsonl"
    base = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("CREWSHIP_GITHUB_", "GH_"))
    }
    base["PATH"] = f"{home / '.local/bin'}:{base['PATH']}"
    base["GH_STUB_CALLS"] = str(calls)
    base["AXI_STARTS"] = str(starts)

    def run(script, *, contract=CONTRACT, approved=None, stdin=None, **extra):
        env = {**base, **extra}
        if contract:
            env["CREWSHIP_GITHUB_REPO"] = contract
        if approved:
            env["CREWSHIP_GITHUB_APPROVED_REPO"] = approved
        calls.unlink(missing_ok=True)
        starts.unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", "-c", script], cwd=tmp_path / "work", env=env, input=stdin,
            capture_output=True, text=True, timeout=30,
        )
        result.calls = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        result.starts = [json.loads(line) for line in starts.read_text().splitlines()] if starts.exists() else []
        return result

    return run


def assert_blocked(result):
    assert result.calls == [], result.stderr
    assert result.starts == [], result.stderr
    assert result.returncode == 2
    assert "Blocked:" in result.stderr


def assert_ran(result, command, work):
    assert result.returncode == 0, result.stderr
    assert [call["argv"] for call in result.calls] == [shlex.split(command)]
    assert result.calls[0]["cwd"] == str(work)
    assert result.starts == []


def check(run, tmp_path, command, allowed, **options):
    result = run(f"gh {command}", **options)
    if allowed:
        assert_ran(result, command, tmp_path / "work")
    else:
        assert_blocked(result)


def axi(run, command, calls, **options):
    result = run(f"gh-axi {command}", **options)
    if calls is None:
        assert_blocked(result)
    else:
        assert result.returncode == 0, result.stderr
        assert result.starts == [shlex.split(command)]
        assert [call["argv"] for call in result.calls] == calls
    return result


def test_both_commands_resolve_to_managed_wrappers(home, run):
    result = run("command -v gh gh-axi")
    assert result.stdout.split() == [str(home / ".local/bin/gh"), str(home / ".local/bin/gh-axi")]
    guard = home / ".local/share/crewship/gh-guard"
    assert (home / ".local/bin/gh-axi").resolve() == guard / "gh-axi"
    assert (guard / "gh-axi-real").resolve().name == "gh-axi.js"


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


@pytest.mark.parametrize("name", ["gh", "gh-axi"])
def test_real_link_cannot_recurse_through_local_bin(home, run, name):
    real = home / f".local/share/crewship/gh-guard/{name}-real"
    real.unlink()
    real.symlink_to(home / f".local/bin/{name}")
    result = run(f"{name} issue list")
    assert result.returncode == 2
    assert (result.calls, result.starts) == ([], [])


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
    assert (result.calls, result.starts) == ([], []), result.stderr
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
    assert result.starts == []
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


AXI_WRITES = [
    "issue create --title x", "issue edit 1 --title x", "issue comment 1 --body x", "issue close 1",
    "issue reopen 1", "issue delete 1", "issue lock 1", "issue unlock 1", "issue pin 1", "issue unpin 1",
    "issue transfer 1 --to-repo i098/sanctum", "issue subissue add 1 2", "issue subissue remove 1 2",
    "issue create --title x --type Bug", "issue edit 1 --type Bug", "issue edit 1 --no-type",
]


@pytest.mark.parametrize("command", AXI_WRITES)
@pytest.mark.parametrize("target,env", [
    ("", {}),
    ("", {"GH_REPO": CONTRACT}),
    ("-R upstream/firstmate", {}),
    ("--repo=upstream/firstmate", {}),
    ("-R=upstream/firstmate", {"GH_REPO": CONTRACT}),
    ("-R i098/sanctum -R upstream/firstmate", {}),
    ("--repo i098/sanctum --repo=upstream/firstmate", {}),
])
def test_gh_axi_writes_without_matching_repo_flag_block_before_real_gh_axi(run, command, target, env):
    axi(run, f"{command} {target}", None, approved=CONTRACT, **env)


@pytest.mark.parametrize("command", [
    "issue close https://github.com/i098/sanctum/issues/1",
    "issue create -R i098/sanctum --title x --body --repo upstream/firstmate",
    "issue create -R i098/sanctum --title x --body --repo=upstream/firstmate",
    "issue comment 1 -R i098/sanctum --body -R upstream/firstmate",
    "issue close 1 -R i098/sanctum --comment -R=upstream/firstmate",
    "issue create -R '' --title x",
    "issue transfer 1 -R i098/sanctum",
    "issue transfer 1 -R i098/sanctum --to-repo upstream/firstmate",
    "issue transfer 1 -R i098/sanctum --to-repo upstream/firstmate --to-repo i098/sanctum",
    "issue create --title x --version",
    "issue create --title x -h",
    "issue create --title x --help=true",
])
def test_gh_axi_hidden_or_wrong_targets_block_before_real_gh_axi(run, command):
    axi(run, command, None, GH_REPO=CONTRACT)


@pytest.mark.parametrize("command,calls,env", [
    ("issue create -R i098/sanctum --title x", [["issue", "create", "--title", "x", *R]], {}),
    ("issue create -R upstream/firstmate -R i098/sanctum --title x", [["issue", "create", "--title", "x", *R]], {}),
    ("issue edit 1 --repo=i098/sanctum --title x", [["issue", "edit", "1", "--title", "x", *R]], {}),
    ("issue comment 1 -R=i098/sanctum --body x", [["issue", "comment", "1", "--body", "x", *R]], {}),
    ("issue delete 1 -R i098/sanctum", [["issue", "delete", "1", *R]], {"GH_REPO": UPSTREAM}),
    ("issue transfer 1 -R i098/sanctum --to-repo i098/sanctum --to-repo upstream/firstmate",
     [["issue", "transfer", "1", CONTRACT, *R]], {}),
    *[(f"issue {op} 1 -R i098/sanctum",
       [["issue", "view", "1", "--json", "state", *R], ["issue", op, "1", *R]], {"GH_REPO": UPSTREAM})
      for op in ("close", "reopen", "lock", "unlock", "pin", "unpin")],
])
def test_gh_axi_explicit_contract_writes_reach_real_gh_axi(run, command, calls, env):
    axi(run, command, calls, **env)


def sub_mutation(name):
    return ["api", "graphql", "-f", f"query=mutation {{ {name}(input: {{}}) {{ clientMutationId }} }}"]


TYPE_CALLS = ["api", "graphql", "-f", "id=I_1", "-f", TYPE_MUTATION]
GRAPHQL_PATHS = [
    ("issue subissue add 1 2", [["api", "graphql", "-f", LOOKUP], sub_mutation("addSubIssue")]),
    ("issue subissue remove 1 2", [["api", "graphql", "-f", LOOKUP], sub_mutation("removeSubIssue")]),
    ("issue create --title x --type Bug",
     [["api", "graphql", "-f", TYPES], ["issue", "create", "--title", "x", *R], TYPE_CALLS]),
    ("issue edit 1 --type Bug", [["api", "graphql", "-f", TYPES], ["issue", "edit", "1", *R], TYPE_CALLS]),
    ("issue edit 1 --no-type", [["issue", "edit", "1", *R], TYPE_CALLS]),
]


@pytest.mark.parametrize("command,calls", GRAPHQL_PATHS)
@pytest.mark.parametrize("approved", [None, "i098/other", UPSTREAM])
def test_gh_axi_internal_graphql_paths_need_source_repo_approval(run, command, calls, approved):
    axi(run, f"{command} -R i098/sanctum", None, approved=approved)


@pytest.mark.parametrize("command,calls", GRAPHQL_PATHS)
def test_gh_axi_internal_graphql_paths_run_with_exact_approval(run, command, calls):
    axi(run, f"{command} -R i098/sanctum", calls, approved=CONTRACT)


def test_gh_axi_upstream_writes_need_matching_approval(run):
    command = "issue transfer 1 -R i098/sanctum --to-repo upstream/firstmate"
    axi(run, command, None, approved="upstream/other")
    axi(run, command, [["issue", "transfer", "1", UPSTREAM, *R]], approved=UPSTREAM)
    axi(run, "issue subissue add 1 2 -R upstream/firstmate", None, approved=CONTRACT)
    axi(
        run, "issue subissue add 1 2 -R upstream/firstmate",
        [["api", "graphql", "-f", LOOKUP], sub_mutation("addSubIssue")], approved=UPSTREAM,
    )
    axi(
        run, "issue create -R upstream/firstmate --title fix --body 'See https://github.com/python/cpython/issues/1'",
        [["issue", "create", "--title", "fix", "--body", "See https://github.com/python/cpython/issues/1",
          "--repo", UPSTREAM]],
        approved=UPSTREAM,
    )


@pytest.mark.parametrize("text", [
    "-R upstream/firstmate", "https://github.com/upstream/firstmate/issues/2", "repos/upstream/firstmate/issues/2",
])
def test_gh_axi_body_repository_text_is_ignored(run, text):
    axi(
        run, f"issue create -R i098/sanctum --title x --body {shlex.quote(text)}",
        [["issue", "create", "--title", "x", "--body", text, *R]],
    )
    axi(run, f"issue create --title x --body {shlex.quote(text)}", None)


@pytest.mark.parametrize("command,env", [
    ("api POST repos/upstream/firstmate/issues --field title=x", {}),
    ("api post repos/upstream/firstmate/issues --field title=x", {}),
    ("api -X POST repos/upstream/firstmate/issues --field title=x", {}),
    ("api -X=PATCH repos/upstream/firstmate/issues/1 --field title=x", {}),
    ("api DELETE repos/upstream/firstmate/issues/comments/1", {}),
    ("api POST 'repos/{owner}/{repo}/issues' --field title=x", {}),
    ("api POST 'repos/{owner}/{repo}/issues' --field title=x", {"GH_REPO": CONTRACT}),
    ("api POST repos/i098/sanctum/issues/1/sub_issues --field sub_issue_id=1", {}),
    (f"api graphql --field {shlex.quote(CREATE_ISSUE)}", {}),
    ("api graphql --input payload.json", {}),
])
def test_gh_axi_api_writes_block_before_real_gh_axi(run, command, env):
    axi(run, command, None, **env)


@pytest.mark.parametrize("command,call,approved", [
    ("api repos/upstream/firstmate/issues --field page=1",
     ["api", "repos/upstream/firstmate/issues", "--method", "GET", "--field", "page=1"], None),
    ("api GET repos/upstream/firstmate/issues", ["api", "repos/upstream/firstmate/issues", "--method", "GET"], None),
    ("api POST repos/i098/sanctum/issues --field title=x",
     ["api", "repos/i098/sanctum/issues", "--method", "POST", "--field", "title=x"], None),
    ("api -X POST /repos/i098/sanctum/issues/1/comments --field body=x",
     ["api", "/repos/i098/sanctum/issues/1/comments", "--method", "POST", "--field", "body=x"], None),
    ("api PATCH repos/upstream/firstmate/pulls/1 --field body=x",
     ["api", "repos/upstream/firstmate/pulls/1", "--method", "PATCH", "--field", "body=x"], None),
    ("api graphql --field 'query=query { viewer { login } }'",
     ["api", "graphql", "--method", "GET", "--field", "query=query { viewer { login } }"], None),
    ("api POST repos/upstream/firstmate/issues --field title=x",
     ["api", "repos/upstream/firstmate/issues", "--method", "POST", "--field", "title=x"], UPSTREAM),
])
def test_gh_axi_api_reads_and_matching_writes_reach_real_gh_axi(run, command, call, approved):
    axi(run, command, [call], approved=approved)


@pytest.mark.parametrize("command,calls,env", [
    ("issue list", [["issue", "list"]], {}),
    ("issue list", [["issue", "list", "--repo", UPSTREAM]], {"GH_REPO": UPSTREAM}),
    ("issue view 1 -R upstream/firstmate --comments", [["issue", "view", "1", "--comments", "--repo", UPSTREAM]], {}),
    ("issue subissue list 1", [["issue", "subissue", "list", "1"]], {}),
    ("pr view 42", [["pr", "view", "42"]], {}),
    ("pr comment 42 --body x", [["pr", "comment", "42", "--body", "x"]], {}),
    ("--help", [], {}),
    ("--version", [], {}),
    ("issue create --title x --help", [], {}),
    ("issue subissue add 1 2 --help", [], {}),
])
def test_gh_axi_reads_and_bare_help_reach_real_gh_axi(run, command, calls, env):
    axi(run, command, calls, **env)


@pytest.mark.parametrize("command", ["issue create --title incident", "issue edit 1 --title incident"])
@pytest.mark.parametrize("flags", [
    "--type Bug --type ''",
    "--type=Bug --type=",
    "--type Bug --type=",
    "--type '' --type Bug",
    "--type=",
])
@pytest.mark.parametrize("approved", [None, UPSTREAM])
def test_every_type_flag_requires_approval_before_gh_axi_starts(run, command, flags, approved):
    axi(run, f"{command} -R i098/sanctum {flags}", None, approved=approved)


BOARD_STUB = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
calls = Path(os.environ["BOARD_STUB_CALLS"])
argv = sys.argv[1:]
with calls.open("a") as log:
    log.write(json.dumps(argv) + "\\n")
args = argv[1:]
if args[0] == "graphql" and "repositoryOwner" in args[2]:
    options = [{{"id": f"option-{{name}}", "name": name}} for name in ("Queued", "In progress", "In review", "Done")]
    answer = {{"data": {{"repositoryOwner": {{"projectV2": {{"id": "project", "field": {{"id": "status", "options": options}}}}}}}}}}
elif args[0] == "graphql":
    answer = {{"data": {{f"a{{i}}": {{"item": {{"id": f"item-{{i}}"}}}} for i in range(args[2].count("addProjectV2ItemById"))}}}}
elif args[0].endswith("/issues"):
    answer = {{"number": 1, "node_id": "issue-1"}}
else:
    answer = {{}}
print(json.dumps(answer))
"""


def rendered_board_service(tmp_path, home, repo):
    spec = importlib.util.spec_from_file_location("github_board_apply", ROOT / "tests/test_github_board.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._apply(tmp_path, home, {"repo": repo, "project": 3})
    env, command = {}, None
    for line in (home / ".config/systemd/user/github-board.service").read_text().splitlines():
        key, _, value = line.replace("%h", str(home)).partition("=")
        if key == "Environment":
            env.update(word.split("=", 1) for word in shlex.split(value))
        elif key == "ExecStart":
            command = shlex.split(value)
    return env, command


def test_the_rendered_board_service_syncs_its_repo_through_the_guard(tmp_path):
    home = tmp_path / "home"
    real = home / ".local/share/crewship/tools/gh/2.0.0/bin/gh"
    real.parent.mkdir(parents=True)
    real.write_text(BOARD_STUB)
    real.chmod(0o755)
    env, command = rendered_board_service(tmp_path, home, CONTRACT)
    assert env["PATH"].split(":")[0] == str(home / ".local/bin")
    provisions.install_gh_guard(home, real)
    calls = tmp_path / "board-calls.jsonl"
    env.update(HOME=str(home), BOARD_STUB_CALLS=str(calls))
    firstmate = Path(command[2])
    (firstmate / "data").mkdir(parents=True)
    (firstmate / "state").mkdir()
    state = home / ".local/state/github-board/state.json"

    def sync(section):
        (firstmate / "data/backlog.md").write_text(f"## {section}\n- [ ] a - work a (repo: r)\n")
        calls.unlink(missing_ok=True)
        result = subprocess.run([sys.executable, *command[1:]], env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        made = [json.loads(line) for line in calls.read_text().splitlines()]
        mutations = [call[3] for call in made if call[1] == "graphql" and call[3].startswith("query=mutation")]
        assert ["addProjectV2ItemById" in mutations[0], "updateProjectV2ItemFieldValue" in mutations[1]] == [True, True]
        return made, json.loads(state.read_text())

    made, saved = sync("In flight")
    assert made[0][:2] == ["api", f"repos/{CONTRACT}/issues"]
    assert saved["items"]["a"] == {"issue": 1, "node": "issue-1", "status": "In progress", "posted": 0}

    made, saved = sync("Done")
    assert ["api", "-X", "PATCH", f"repos/{CONTRACT}/issues/1", "-f", "state=closed"] in made
    assert saved == {"repo": CONTRACT, "project": 3,
                     "items": {"a": {"issue": 1, "node": "issue-1", "status": "Done", "posted": 0}}}

    calls.unlink()
    blocked = subprocess.run(["gh", "api", f"repos/{UPSTREAM}/issues", "-f", "title=x"],
                             env=env, capture_output=True, text=True, timeout=30)
    assert blocked.returncode == 2 and "Blocked:" in blocked.stderr
    assert not calls.exists()


@pytest.mark.parametrize("flags", [
    "--no-type --no-type=false",
    "--no-type=false --no-type",
    "--no-type --no-type=0",
    "--no-type --no-type=f",
])
@pytest.mark.parametrize("approved", [None, UPSTREAM])
def test_literal_no_type_cannot_be_cancelled_before_gh_axi_starts(run, flags, approved):
    axi(run, f"issue edit 1 -R i098/sanctum --title renamed {flags}", None, approved=approved)


@pytest.mark.skipif(shutil.which("bun") is None, reason="needs bun")
def test_process_guard_keeps_original_eval_json_matching():
    code = f"""
import extension from {json.dumps(str(ROOT / "blueprint/config/omp-no-pattern-kill.ts"))};
let handler;
extension({{ on: (_event, callback) => {{ handler = callback; }} }});
const result = await handler({{
    toolName: "eval", input: {{ code: 'import os\\nkillall = "example"' }}
}});
console.log(JSON.stringify(result));
"""
    result = subprocess.run(["bun", "-e", code], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {}
