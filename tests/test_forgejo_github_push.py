"""blueprint/maintenance/forgejo-github-push: what the post-receive hook pushes to GitHub.

A local bare repository stands in for GitHub, and a systemd-run stub runs the queued
push at once, so each test sees exactly what the hook would send.
"""

import os
import subprocess
import time
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
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base", cwd=work)
    base = git("rev-parse", "HEAD", cwd=work)
    # GitHub already has main and a branch only it knows.
    git("push", "-q", str(tmp_path / "github.git"), "main", "main:refs/heads/github-only/keep", cwd=work)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "next", cwd=work)
    head = git("rev-parse", "HEAD", cwd=work)
    for ref in ("main", "develop", "fm/x", "anything/y"):
        git("push", "-q", str(tmp_path / "forgejo.git"), f"HEAD:refs/heads/{ref}", cwd=work)
    if enabled:
        git("config", "crewship.github-push", str(tmp_path / "github.git"), cwd=tmp_path / "forgejo.git")
    return base, head


def hook(tmp_path, lines):
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "GIT_DIR": str(tmp_path / "forgejo.git"),
    }
    subprocess.run([SCRIPT, "hook"], input="".join(lines), env=env, check=True, text=True)
    listing = git("for-each-ref", "--format=%(refname)\t%(objectname)", cwd=tmp_path / "github.git")
    return dict(line.split("\t") for line in listing.splitlines())


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


def test_a_later_push_waits_for_the_one_in_flight_and_lands_last(tmp_path):
    setup(tmp_path)
    forgejo, github = tmp_path / "forgejo.git", tmp_path / "github.git"
    started, release = tmp_path / "started", tmp_path / "release"
    # GitHub holds the first push it receives until the test releases it.
    pre_receive = github / "hooks/pre-receive"
    pre_receive.write_text(
        f'#!/bin/sh\ncat >/dev/null\n[ -e "{started}" ] && exit 0\n: > "{started}"\n'
        f'while [ ! -e "{release}" ]; do sleep 0.05; done\n'
    )
    pre_receive.chmod(0o755)
    push = [SCRIPT, "push", str(forgejo), str(github), "+refs/heads/fm/x:refs/heads/fm/x"]
    first = subprocess.Popen(push)
    while not started.exists():
        time.sleep(0.05)
    work = tmp_path / "work"
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "amend", cwd=work)
    newer = git("rev-parse", "HEAD", cwd=work)
    git("push", "-q", "-f", str(forgejo), "HEAD:refs/heads/fm/x", cwd=work)
    second = subprocess.Popen(push)
    time.sleep(1)
    assert second.poll() is None
    release.touch()
    assert first.wait(timeout=30) == 0
    assert second.wait(timeout=30) == 0
    assert git("rev-parse", "refs/heads/fm/x", cwd=github) == newer
