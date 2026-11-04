import importlib.machinery
import importlib.util
import subprocess
import time
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "blueprint/maintenance/slk"
loader = importlib.machinery.SourceFileLoader("slk_notify", str(SOURCE))
slk = importlib.util.module_from_spec(importlib.util.spec_from_loader("slk_notify", loader))
loader.exec_module(slk)


@pytest.mark.parametrize(
    "args, expected",
    [
        (
            ["export", "-channel", "dev", "-workspace", "acme", "-since", "2026-01-01"],
            "read acme dev",
        ),
        (["export", "--channel=dm-bob", "--workspace=acme"], "read acme dm-bob"),
        (["export", "-channel", "dev"], "read default dev"),
        (["export", "--help"], None),
        (["--list-workspaces"], None),
        (["--add-workspace"], None),
        ([], "opened the Slack TUI"),
    ],
)
def test_parse(args, expected):
    assert slk.parse(args) == expected


@pytest.fixture
def host(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "slk").write_bytes(SOURCE.read_bytes())
    (bin_dir / "slk").chmod(0o755)
    real = bin_dir / "slk-real"
    real.write_text('#!/bin/sh\ncat >/dev/null\necho "real $*"\nexit 7\n')
    real.chmod(0o755)
    log = tmp_path / "texts"
    fm = tmp_path / "tools/fm-imessage"
    fm.parent.mkdir()
    fm.write_text(f'#!/bin/sh\nshift\necho "$*" >> {log}\n')
    fm.chmod(0o755)
    env = {
        "PATH": f"{fm.parent}:/usr/bin:/bin",
        "FM_TASK_ID": "worker-1",
    }

    def run(*args, env_extra=None):
        merged = {**env, **(env_extra or {})}
        result = subprocess.run(
            [str(bin_dir / "slk"), *args], text=True, capture_output=True, env=merged
        )
        return result

    run.log = log
    return run


def texts(log):
    time.sleep(0.2)
    return log.read_text().splitlines() if log.exists() else []


def test_export_passes_through_and_notifies(host):
    first = host("export", "-workspace", "acme", "-channel", "dev")
    assert (first.returncode, first.stdout) == (7, "real export -workspace acme -channel dev\n")
    assert texts(host.log) == ["slk read: worker-1 read acme dev"]


def test_two_reads_in_a_row_send_two_texts(host):
    host("export", "-workspace", "acme", "-channel", "dev")
    host("export", "-workspace", "acme", "-channel", "ops")
    assert sorted(texts(host.log)) == [
        "slk read: worker-1 read acme dev",
        "slk read: worker-1 read acme ops",
    ]


@pytest.mark.parametrize(
    "flag",
    ["--list-workspaces", "--dump-sections", "--version", "--help", "--add-workspace", "--remove-workspace"],
)
def test_non_read_never_notifies(host, flag):
    result = host(flag)
    assert result.stdout == f"real {flag}\n"
    assert texts(host.log) == []


def test_bare_tui_notifies(host):
    result = host()
    assert (result.returncode, result.stdout) == (7, "real \n")
    assert texts(host.log) == ["slk read: worker-1 opened the Slack TUI"]


def test_missing_fm_imessage_does_not_break_slk(host):
    result = host("export", "-workspace", "a", "-channel", "c", env_extra={"PATH": "/usr/bin:/bin"})
    assert (result.returncode, result.stdout) == (7, "real export -workspace a -channel c\n")
