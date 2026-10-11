"""tasks/firstmate.yml keeps the checkout at origin/main plus patches/firstmate/.

Patch-layer tests drive the real task file with ansible-playbook against
throwaway repositories and two generated patches.
Crew board tests apply the carried patch to an exported upstream checkout.
"""

import getpass
import grp
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/firstmate-patch-layer.sh"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
OLD_NAME = yaml.safe_load((ROOT / "ansible/tasks/rename.yml").read_text())[0]["vars"]["crewship_renamed_word"]


def git(repo, *args):
    return subprocess.run(
        [*GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo, path, lines, message):
    (repo / path).write_text("".join(f"{line}\n" for line in lines))
    git(repo, "add", path)
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def host(tmp_path):
    upstream = tmp_path / "upstream.git"
    dev = tmp_path / "dev"
    patches = tmp_path / "patches"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(upstream)], check=True)
    subprocess.run(["git", "clone", "-q", str(upstream), str(dev)], check=True)
    lines = [f"line {n}" for n in range(1, 41)]
    commit(dev, "watch.sh", lines, "upstream: initial")
    git(dev, "push", "-q", "origin", "HEAD:main")
    git(dev, "checkout", "-q", "-b", "fix")
    lines[4] = "line 5 patched"
    commit(dev, "watch.sh", lines, "fix: first")
    lines[29] = "line 30 patched"
    commit(dev, "watch.sh", lines, "fix: second")
    git(dev, "format-patch", "-q", "-o", str(patches), "main..fix")
    git(dev, "checkout", "-q", "main")
    git(dev, "branch", "-q", "-D", "fix")
    return {
        "tmp": tmp_path,
        "upstream": upstream,
        "dev": dev,
        "patches": patches,
        "checkout": tmp_path / "firstmate",
        "first": next(patches.glob("0001-*.patch")),
    }


def apply(host):
    playbook = host["tmp"] / "firstmate.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {"ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/firstmate.yml")}
                    ],
                }
            ]
        )
    )
    variables = {
        # The dispatch-settings tasks ask for root; nothing here needs it.
        "ansible_become": False,
        "crewship_repo": str(ROOT),
        "crewship_become_target": False,
        "crewship_user_env": {},
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_firstmate_dir": str(host["checkout"]),
        "crewship_firstmate_patch_dir": str(host["patches"]),
        "crewship_firstmate_config_names": [],
        "crewship_cfg": {"user": getpass.getuser(), "firstmate": {"url": str(host["upstream"])}},
    }
    result = subprocess.run(
        [
            Path(sys.executable).parent / "ansible-playbook",
            "-i",
            "localhost,",
            str(playbook),
            "--extra-vars",
            json.dumps(variables),
        ],
        cwd=host["tmp"],
        capture_output=True,
        text=True,
    )
    recap = result.stdout.rsplit("changed=", 1)
    changed = int(recap[1].split()[0]) if len(recap) == 2 else None
    return result, changed


def push_upstream(host, path, lines, message):
    commit(host["dev"], path, lines, message)
    git(host["dev"], "push", "-q", "origin", "HEAD:main")
    return git(host["dev"], "rev-parse", "HEAD")


def layer(host, count):
    """Subjects of the top <count> commits on main, oldest first."""
    return git(host["checkout"], "log", "--reverse", "--format=%s", f"-{count}").splitlines()


def verify(host):
    target = git(host["checkout"], "rev-parse", "origin/main")
    return subprocess.run(
        ["bash", SCRIPT, "verify", host["checkout"], target, host["patches"]],
        capture_output=True,
        text=True,
    )


def test_fresh_clone_gets_the_layer_and_a_second_apply_changes_nothing(host):
    result, changed = apply(host)
    assert result.returncode == 0, result.stdout
    assert changed > 0
    checkout = host["checkout"]
    assert git(checkout, "rev-parse", "HEAD~2") == git(host["upstream"], "rev-parse", "main")
    assert layer(host, 2) == ["fix: first", "fix: second"]
    assert git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git(checkout, "rev-parse", "--abbrev-ref", "main@{upstream}") == "origin/main"
    assert git(checkout, "status", "--porcelain") == ""
    assert verify(host).returncode == 0
    head = git(checkout, "rev-parse", "HEAD")

    result, changed = apply(host)
    assert result.returncode == 0, result.stdout
    assert changed == 0
    assert git(checkout, "rev-parse", "HEAD") == head


def test_upstream_advance_rebuilds_the_layer_on_the_new_origin_main(host):
    assert apply(host)[0].returncode == 0
    old = git(host["checkout"], "rev-parse", "HEAD")
    new_main = push_upstream(host, "other.sh", ["echo new"], "upstream: unrelated")

    result, changed = apply(host)
    assert result.returncode == 0, result.stdout
    assert changed > 0
    assert git(host["checkout"], "rev-parse", "HEAD~2") == new_main
    assert layer(host, 3) == ["upstream: unrelated", "fix: first", "fix: second"]
    assert git(host["checkout"], "branch", "--contains", old) == ""
    assert verify(host).returncode == 0


def test_a_patch_upstream_already_has_is_skipped(host):
    assert apply(host)[0].returncode == 0
    git(host["dev"], "am", "-q", str(host["first"]))
    git(host["dev"], "push", "-q", "origin", "HEAD:main")
    new_main = git(host["dev"], "rev-parse", "HEAD")

    result, changed = apply(host)
    assert result.returncode == 0, result.stdout
    assert f"skipped, upstream already has it: {host['first'].name}" in result.stdout
    assert changed > 0
    assert git(host["checkout"], "rev-parse", "HEAD~1") == new_main
    assert layer(host, 1) == ["fix: second"]
    assert verify(host).returncode == 0


def test_a_patch_that_no_longer_applies_stops_and_leaves_the_checkout_as_it_was(host):
    assert apply(host)[0].returncode == 0
    before = git(host["checkout"], "rev-parse", "HEAD")
    lines = [f"line {n}" for n in range(1, 41)]
    lines[4] = "line 5 rewritten upstream"
    push_upstream(host, "watch.sh", lines, "upstream: conflicting edit")

    result, _ = apply(host)
    assert result.returncode != 0
    assert f"{host['first'].name} no longer applies" in result.stdout
    assert git(host["checkout"], "rev-parse", "HEAD") == before
    assert git(host["checkout"], "status", "--porcelain") == ""


def test_an_unknown_local_commit_is_still_refused(host):
    assert apply(host)[0].returncode == 0
    commit(host["checkout"], "mine.txt", ["local work"], "local: unpushed")
    before = git(host["checkout"], "rev-parse", "HEAD")
    push_upstream(host, "other.sh", ["echo new"], "upstream: unrelated")

    result, _ = apply(host)
    assert result.returncode != 0
    assert "Crewship-Patch" in result.stdout
    assert git(host["checkout"], "rev-parse", "HEAD") == before
    assert (host["checkout"] / "mine.txt").exists()


def test_a_layer_built_before_the_rename_is_rebuilt(host):
    assert apply(host)[0].returncode == 0
    checkout = host["checkout"]
    tip = git(checkout, "rev-parse", "HEAD~2")
    for sha in git(checkout, "rev-list", "--reverse", "HEAD~2..HEAD").splitlines():
        message = git(checkout, "log", "-1", "--format=%B", sha)
        old = message.replace("Crewship-Patch:", f"{OLD_NAME.title()}-Patch:")
        tip = subprocess.run(
            [*GIT, "-C", str(checkout), "commit-tree", f"{sha}^{{tree}}", "-p", tip],
            input=old, check=True, capture_output=True, text=True,
        ).stdout.strip()
    git(checkout, "reset", "-q", "--hard", tip)

    result, changed = apply(host)
    assert result.returncode == 0, result.stdout
    assert changed > 0
    assert layer(host, 2) == ["fix: first", "fix: second"]
    assert verify(host).returncode == 0


def test_an_edited_patch_rebuilds_the_layer_on_a_host_that_has_the_old_one(host):
    assert apply(host)[0].returncode == 0
    old = git(host["checkout"], "rev-parse", "HEAD")
    dev = host["dev"]
    git(dev, "checkout", "-q", "-b", "edit")
    lines = [f"line {n}" for n in range(1, 41)]
    lines[4] = "line 5 edited"
    commit(dev, "watch.sh", lines, "fix: first v2")
    edited = Path(git(dev, "format-patch", "-1", "-o", str(host["tmp"] / "edit")))
    git(dev, "checkout", "-q", "main")
    git(dev, "branch", "-q", "-D", "edit")
    host["first"].write_text(edited.read_text())

    result, changed = apply(host)
    assert result.returncode == 0, result.stdout
    assert changed > 0
    assert layer(host, 2) == ["fix: first v2", "fix: second"]
    assert git(host["checkout"], "branch", "--contains", old) == ""
    assert verify(host).returncode == 0
    assert apply(host)[1] == 0


def test_a_dropped_patch_rebuilds_the_layer_on_a_host_that_has_the_old_one(host):
    assert apply(host)[0].returncode == 0
    next(host["patches"].glob("0002-*.patch")).unlink()

    result, changed = apply(host)
    assert result.returncode == 0, result.stdout
    assert changed > 0
    assert git(host["checkout"], "rev-parse", "HEAD~1") == git(
        host["upstream"], "rev-parse", "main"
    )
    assert layer(host, 1) == ["fix: first"]
    assert verify(host).returncode == 0


def assert_default_socket(tmp_path, monkeypatch, env, render, enabled):
    """CREWBOARD_SOCKET unset or empty falls back to $XDG_RUNTIME_DIR/crewboard.sock."""
    runtime = tmp_path / "run"
    runtime.mkdir()
    env["XDG_RUNTIME_DIR"] = str(runtime)
    with socket.socket(socket.AF_UNIX) as board, monkeypatch.context() as context:
        # Bind relative to avoid the Unix socket path limit in deep worktrees.
        context.chdir(runtime)
        board.bind("crewboard.sock")
        board.listen()
        for value in (None, ""):
            if value is None:
                env.pop("CREWBOARD_SOCKET", None)
            else:
                env["CREWBOARD_SOCKET"] = value
            assert render() == enabled


@pytest.fixture
def crewboard_firstmate(tmp_path):
    """Exercise the carried patch against a supplied, read-only upstream tree."""
    source = os.environ.get("FIRSTMATE_TEST_SOURCE")
    if not source:
        pytest.skip("Set FIRSTMATE_TEST_SOURCE to an upstream Firstmate source tree")
    checkout = tmp_path / "source"
    archive = subprocess.run(
        ["git", "-C", source, "archive", "HEAD", "bin", "docs"],
        check=True, capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        tree.extractall(checkout, filter="data")
    scripts = ("fm-brief.sh", "fm-supervision-instructions.sh")
    for script in scripts:
        shutil.copyfile(checkout / "bin" / script, checkout / "bin" / f"baseline-{script}")
    patch = ROOT / "patches/firstmate/0003-brief-crewboard.patch"
    # Keep git apply from finding a parent repository and skipping these paths.
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=checkout, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=checkout, check=True)
    for script in scripts:
        subprocess.run(["bash", "-n", checkout / "bin" / script], check=True)
    return checkout


@pytest.mark.parametrize(
    "arguments",
    [
        ["sample", "project", "--mode", "no-mistakes"],
        ["sample", "project", "--scout"],
        ["sample", "--secondmate", "--no-projects"],
    ],
)
def test_crewboard_brief_output(crewboard_firstmate, tmp_path, arguments, monkeypatch):
    checkout = crewboard_firstmate
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "FM_HOME": str(home)}
    env.pop("CREWBOARD_SOCKET", None)
    # An absent runtime dir keeps the default socket path from naming the real board.
    env["XDG_RUNTIME_DIR"] = str(tmp_path / "run")
    brief = home / "data/sample/brief.md"

    def render(script):
        subprocess.run(["bash", checkout / "bin" / script, *arguments], env=env, check=True)
        result = brief.read_bytes()
        brief.unlink()
        return result

    baseline = render("baseline-fm-brief.sh")
    regular = tmp_path / "regular"
    regular.touch()
    for value in (None, "", str(tmp_path / "absent"), str(regular)):
        if value is None:
            env.pop("CREWBOARD_SOCKET", None)
        else:
            env["CREWBOARD_SOCKET"] = value
        assert render("fm-brief.sh") == baseline

    with socket.socket(socket.AF_UNIX) as board:
        path = tmp_path / "board.sock"
        # Bind relative to avoid the Unix socket path limit in deep worktrees.
        with monkeypatch.context() as context:
            context.chdir(tmp_path)
            board.bind(path.name)
        board.listen()
        env["CREWBOARD_SOCKET"] = str(path)
        enabled = render("fm-brief.sh")
        assert_default_socket(tmp_path, monkeypatch, env, lambda: render("fm-brief.sh"), enabled)
        section = (
            b"\n\n# Crew board\n"
            b"The board permits direct peer coordination; report task states only to Firstmate through the status file.\n"
            b"Use `crewboard pub task/<peer-id> 'message'` for a peer and `crewboard pub fleet 'message'` for the crew.\n"
            b"Use `crewboard pub fm 'message'` for information that must not wake Firstmate.\n"
            b"Read `crewboard tail task/sample` and `crewboard tail fleet` at natural checkpoints, or subscribe in a separate pane.\n"
            b"Use `crewboard sub task/sample fleet` for that subscription; it waits for messages.\n"
            b"Firstmate observes the board and never relays messages. The steering inbox remains unchanged.\n"
            b"The board stores messages only in memory. Keep working, done, needs-decision, blocked, failed, and paused in the status file.\n"
        )
        anchor = baseline.index(b"\n\n#", baseline.index(b"# Firstmate instruction inbox\n"))
        assert enabled.count(b"# Crew board\n") == 1
        assert enabled == baseline[:anchor] + section + baseline[anchor:]


@pytest.mark.parametrize("harness", ["claude", "codex", "opencode", "pi", "grok", "cursor", "omp", "unknown"])
def test_crewboard_supervisor_output(crewboard_firstmate, tmp_path, harness, monkeypatch):
    checkout = crewboard_firstmate
    env = {**os.environ, "FM_HOME": str(tmp_path / "home")}
    env.pop("CREWBOARD_SOCKET", None)
    # An absent runtime dir keeps the default socket path from naming the real board.
    env["XDG_RUNTIME_DIR"] = str(tmp_path / "run")

    def render(script, *options):
        return subprocess.run(
            ["bash", checkout / "bin" / script, "--harness", harness, *options],
            env=env, check=True, capture_output=True,
        ).stdout

    baseline = render("baseline-fm-supervision-instructions.sh")
    regular = tmp_path / "regular"
    regular.touch()
    for value in (None, "", str(tmp_path / "absent"), str(regular)):
        if value is None:
            env.pop("CREWBOARD_SOCKET", None)
        else:
            env["CREWBOARD_SOCKET"] = value
        assert render("fm-supervision-instructions.sh") == baseline

    with socket.socket(socket.AF_UNIX) as board:
        path = tmp_path / "board.sock"
        # Bind relative to avoid the Unix socket path limit in deep worktrees.
        with monkeypatch.context() as context:
            context.chdir(tmp_path)
            board.bind(path.name)
        board.listen()
        env["CREWBOARD_SOCKET"] = str(path)
        enabled = render("fm-supervision-instructions.sh")
        assert_default_socket(tmp_path, monkeypatch, env, lambda: render("fm-supervision-instructions.sh"), enabled)
        note = b"- Crew board: open a separate pane and run crewboard sub '*'; observe, never relay. The status file remains the durable ledger.\n"
        assert enabled.count(note) == 1
        anchor = baseline.index(b"- Ordinary wake:")
        assert enabled == baseline[:anchor] + note + baseline[anchor:]
        assert render("fm-supervision-instructions.sh", "--repair-line") == render(
            "baseline-fm-supervision-instructions.sh", "--repair-line"
        )
