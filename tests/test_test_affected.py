import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "test-affected"


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _mode(repo):
    fake = repo.parent / (repo.name + "-bin")
    fake.mkdir(exist_ok=True)
    (fake / "cf-sandbox").write_text(
        '#!/bin/sh\nfor a; do case $a in --testmon*) echo "$a";; esac; done\n'
    )
    (fake / "cf-sandbox").chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake}:{os.environ['PATH']}",
        "CF_TESTMON_DIR": str(repo.parent / (repo.name + "-tm")),
    }
    out = subprocess.run(
        [str(SCRIPT)], cwd=repo, env=env, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _repo(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "work")
    return tmp_path


def test_python_only_change_selects(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.py").write_text("x = 2\n")
    assert _mode(repo) == "--testmon"


def test_untracked_non_python_file_runs_everything(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.py").write_text("x = 2\n")
    (repo / "play.yml").write_text("- hosts: all\n")
    assert _mode(repo) == "--testmon-noselect"


def test_committed_non_python_change_runs_everything(tmp_path):
    repo = _repo(tmp_path)
    (repo / "run.sh").write_text("true\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "sh")
    assert _mode(repo) == "--testmon-noselect"


def test_unknown_merge_base_runs_everything(tmp_path):
    _git(tmp_path, "init", "-b", "feature")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "base")
    assert _mode(tmp_path) == "--testmon-noselect"


def test_git_failure_runs_everything(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.py").write_text("x = 2\n")
    (repo / ".git" / "index").write_text("corrupt")
    assert _mode(repo) == "--testmon-noselect"
