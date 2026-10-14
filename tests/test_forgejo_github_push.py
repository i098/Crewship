"""blueprint/maintenance/forgejo-github-push: what the post-receive hook pushes to GitHub.

A local bare repository stands in for GitHub, and a systemd-run stub runs the queued
push at once, so each test sees exactly what the hook would send.
"""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "blueprint/maintenance/forgejo-github-push"
# Runs the command after the options, as the transient unit would.
SYSTEMD_RUN = '#!/bin/sh\nwhile [ "${1#--}" != "$1" ]; do shift; done\nexec "$@"\n'
ZERO = "0" * 40


def git(*args, cwd=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def setup(tmp_path, enabled=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "systemd-run").write_text(SYSTEMD_RUN)
    (bin_dir / "systemd-run").chmod(0o755)
    work = tmp_path / "work"
    git("init", "-q", "-b", "main", str(work))
    for name in ("forgejo.git", "github.git"):
        git("init", "-q", "--bare", "-b", "main", str(tmp_path / name))
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "base",
        cwd=work,
    )
    base = git("rev-parse", "HEAD", cwd=work)
    # GitHub already has main and a branch only it knows.
    git(
        "push",
        "-q",
        str(tmp_path / "github.git"),
        "main",
        "main:refs/heads/github-only/keep",
        cwd=work,
    )
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "next",
        cwd=work,
    )
    head = git("rev-parse", "HEAD", cwd=work)
    for ref in ("main", "develop", "fm/x", "anything/y"):
        git("push", "-q", str(tmp_path / "forgejo.git"), f"HEAD:refs/heads/{ref}", cwd=work)
    if enabled:
        git(
            "config",
            "crewship.github-push",
            str(tmp_path / "github.git"),
            cwd=tmp_path / "forgejo.git",
        )
    return base, head


def run_hook(tmp_path, lines):
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "GIT_DIR": str(tmp_path / "forgejo.git"),
    }
    return subprocess.run(
        [SCRIPT, "hook"], input="".join(lines), env=env, capture_output=True, text=True
    )


def refs_of(repo):
    listing = git("for-each-ref", "--format=%(refname)\t%(objectname)", cwd=repo)
    return dict(line.split("\t") for line in listing.splitlines())


def hook(tmp_path, lines):
    assert run_hook(tmp_path, lines).returncode == 0
    return refs_of(tmp_path / "github.git")


def commit(repo, message, *parents):
    tree = git("rev-parse", f"{parents[0]}^{{tree}}", cwd=repo)
    args = [a for p in parents for a in ("-p", p)]
    return git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit-tree",
        tree,
        *args,
        "-m",
        message,
        cwd=repo,
    )


def test_pushes_every_received_branch_but_never_the_default_branch_tags_or_deletions(tmp_path):
    base, head = setup(tmp_path)
    refs = hook(
        tmp_path,
        [
            f"{base} {head} refs/heads/main\n",
            f"{ZERO} {head} refs/heads/fm/x\n",
            f"{ZERO} {head} refs/heads/anything/y\n",
            f"{ZERO} {head} refs/tags/v1\n",
            f"{head} {ZERO} refs/heads/fix/gone\n",
        ],
    )
    assert refs == {
        "refs/heads/main": base,
        "refs/heads/github-only/keep": base,
        "refs/heads/fm/x": head,
        "refs/heads/anything/y": head,
    }


def test_never_pushes_main_even_when_the_default_branch_is_another(tmp_path):
    base, head = setup(tmp_path)
    git("symbolic-ref", "HEAD", "refs/heads/develop", cwd=tmp_path / "forgejo.git")
    refs = hook(
        tmp_path,
        [
            f"{base} {head} refs/heads/main\n",
            f"{base} {head} refs/heads/develop\n",
            f"{ZERO} {head} refs/heads/fm/x\n",
        ],
    )
    assert refs == {
        "refs/heads/main": base,
        "refs/heads/github-only/keep": base,
        "refs/heads/fm/x": head,
    }


def test_a_repository_without_the_opt_in_pushes_nothing(tmp_path):
    base, head = setup(tmp_path, enabled=False)
    refs = hook(tmp_path, [f"{ZERO} {head} refs/heads/fm/x\n"])
    assert refs == {"refs/heads/main": base, "refs/heads/github-only/keep": base}


def test_a_rebased_branch_replaces_what_the_hook_pushed_before(tmp_path):
    base, head = setup(tmp_path)
    forgejo = tmp_path / "forgejo.git"
    hook(tmp_path, [f"{ZERO} {head} refs/heads/fm/x\n"])
    rewritten = commit(forgejo, "rewritten", base)
    git("update-ref", "refs/heads/fm/x", rewritten, cwd=forgejo)
    assert hook(tmp_path, [f"{head} {rewritten} refs/heads/fm/x\n"])["refs/heads/fm/x"] == rewritten


def test_a_github_only_commit_survives_until_the_branch_merges_it(tmp_path):
    _, head = setup(tmp_path)
    forgejo, github = tmp_path / "forgejo.git", tmp_path / "github.git"
    hook(tmp_path, [f"{ZERO} {head} refs/heads/fm/x\n"])
    # A review suggestion made on GitHub, then an agent commit that lacks it.
    review = commit(github, "review", head)
    git("update-ref", "refs/heads/fm/x", review, cwd=github)
    agent = commit(forgejo, "agent", head)
    for ref in ("fm/x", "anything/y"):
        git("update-ref", f"refs/heads/{ref}", agent, cwd=forgejo)

    first = run_hook(
        tmp_path, [f"{head} {agent} refs/heads/fm/x\n", f"{head} {agent} refs/heads/anything/y\n"]
    )
    assert first.returncode != 0
    assert refs_of(github)["refs/heads/fm/x"] == review
    assert refs_of(github)["refs/heads/anything/y"] == agent

    again = commit(forgejo, "again", agent)
    git("update-ref", "refs/heads/fm/x", again, cwd=forgejo)
    second = run_hook(tmp_path, [f"{agent} {again} refs/heads/fm/x\n"])
    assert "warning: GitHub has commits on fm/x" in second.stderr
    assert second.returncode != 0
    assert refs_of(github)["refs/heads/fm/x"] == review

    # The agent fetches the GitHub branch and merges it; the next push goes through.
    git("fetch", "-q", str(github), "refs/heads/fm/x", cwd=forgejo)
    merged = commit(forgejo, "merge", again, review)
    git("update-ref", "refs/heads/fm/x", merged, cwd=forgejo)
    third = run_hook(tmp_path, [f"{again} {merged} refs/heads/fm/x\n"])
    assert third.returncode == 0
    assert "warning" not in third.stderr
    assert refs_of(github)["refs/heads/fm/x"] == merged


def test_a_branch_deleted_on_github_is_pushed_again(tmp_path):
    _, head = setup(tmp_path)
    forgejo, github = tmp_path / "forgejo.git", tmp_path / "github.git"
    hook(tmp_path, [f"{ZERO} {head} refs/heads/fm/x\n", f"{ZERO} {head} refs/heads/anything/y\n"])
    # anything/y gets a GitHub-only commit that Forgejo never merges.
    git("update-ref", "refs/heads/anything/y", commit(github, "review", head), cwd=github)
    agent = commit(forgejo, "agent", head)
    git("update-ref", "refs/heads/anything/y", agent, cwd=forgejo)
    assert run_hook(tmp_path, [f"{head} {agent} refs/heads/anything/y\n"]).returncode != 0

    # Both PRs merge and GitHub deletes their branches; the agents push again.
    for ref in ("fm/x", "anything/y"):
        git("update-ref", "-d", f"refs/heads/{ref}", cwd=github)
    later = commit(forgejo, "later", agent)
    for ref in ("fm/x", "anything/y"):
        git("update-ref", f"refs/heads/{ref}", later, cwd=forgejo)
    refs = hook(
        tmp_path,
        [f"{head} {later} refs/heads/fm/x\n", f"{agent} {later} refs/heads/anything/y\n"],
    )
    assert refs["refs/heads/fm/x"] == later
    assert refs["refs/heads/anything/y"] == later


def test_a_branch_that_github_has_behind_forgejo_is_pushed(tmp_path):
    base, head = setup(tmp_path)
    # fm/x was on GitHub before the repository was enabled.
    git("update-ref", "refs/heads/fm/x", base, cwd=tmp_path / "github.git")
    assert hook(tmp_path, [f"{base} {head} refs/heads/fm/x\n"])["refs/heads/fm/x"] == head
