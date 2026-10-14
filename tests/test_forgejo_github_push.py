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
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base", cwd=work)
    base = git("rev-parse", "HEAD", cwd=work)
    # GitHub already has main and a branch only it knows.
    git("push", "-q", str(tmp_path / "github.git"), "main", "main:refs/heads/github-only/keep", cwd=work)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "next", cwd=work)
    head = git("rev-parse", "HEAD", cwd=work)
    for ref in ("main", "fm/x", "anything/y"):
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


def test_a_repository_without_the_opt_in_pushes_nothing(tmp_path):
    base, head = setup(tmp_path, enabled=False)
    refs = hook(tmp_path, [f"{ZERO} {head} refs/heads/fm/x\n"])
    assert refs == {"refs/heads/main": base, "refs/heads/github-only/keep": base}
