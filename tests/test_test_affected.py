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


def test_default_data_dir_is_per_checkout(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "cf-sandbox").write_text('#!/bin/sh\necho "$TESTMON_DATAFILE"\n')
    (fake / "cf-sandbox").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "CF_TESTMON_DIR"}
    env |= {"PATH": f"{fake}:{os.environ['PATH']}", "HOME": str(tmp_path / "home")}
    files = []
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        repo = _repo(tmp_path / name)
        out = subprocess.run(
            [str(SCRIPT)], cwd=repo, env=env, check=True, capture_output=True, text=True
        )
        files.append(out.stdout.strip())
    assert files[0] != files[1]
    assert all(f.startswith(str(tmp_path / "home")) for f in files)


def test_stale_own_data_dir_survives_and_is_seeded(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "cf-sandbox").write_text('#!/bin/sh\necho "$TESTMON_DATAFILE"\n')
    (fake / "cf-sandbox").chmod(0o755)
    home = tmp_path / "home"
    env = {k: v for k, v in os.environ.items() if k != "CF_TESTMON_DIR"}
    env |= {"PATH": f"{fake}:{os.environ['PATH']}", "HOME": str(home)}
    repo = _repo(tmp_path)
    run = lambda: subprocess.run(  # noqa: E731
        [str(SCRIPT)], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()
    datafile = Path(run())
    cache = home / ".cache" / "crewship-testmon"
    (cache / "seed").write_text("seed")
    datafile.unlink(missing_ok=True)
    subprocess.run(["touch", "-d", "20 days ago", str(datafile.parent)], check=True)
    assert Path(run()) == datafile
    assert datafile.parent.is_dir()
    assert datafile.read_text() == "seed"
