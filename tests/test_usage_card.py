"""fm-usage-remind decision logic (stubbed fm-usage-brief and fm-imessage) and fm-usage-brief averaging."""

import importlib.machinery
import importlib.util
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import jinja2
import pytest

MAINT = Path(__file__).parents[1] / "blueprint/maintenance"


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(MAINT / name))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


@pytest.fixture
def host(tmp_path):
    home = tmp_path / "firstmate"
    (home / "state/inbox").mkdir(parents=True)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "calls"
    for name, body in {
        "fm-usage-brief": 'echo "brief $*" >> "$CALLS"; : > "$2"',
        "fm-imessage": 'echo "imessage $*" >> "$CALLS"',
    }.items():
        (bin_ / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_ / name).chmod(0o755)

    class Host:
        def note(self, age=10, text="[iMessage from the owner; answer with fm-imessage] hi"):
            path = home / "state/inbox/a.note"
            path.write_text(text)
            os.utime(path, (time.time() - age,) * 2)

        def stamp(self, age):
            (home / "state/.usage-remind-last").write_text(str(int(time.time() - age)))

        @property
        def sends(self):
            return calls.read_text().splitlines() if calls.exists() else []

        def run(self, **env):
            return subprocess.run(
                [str(MAINT / "fm-usage-remind")],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "FM_HOME": str(home), "CALLS": str(calls), **env},
            )

    Host.home = home
    return Host()


def test_no_note_sends_nothing(host):
    assert host.run().returncode == 0
    assert host.sends == []


def test_recent_owner_note_sends_card_and_stamps(host):
    host.note()
    assert host.run().returncode == 0
    assert [s.split()[0] for s in host.sends] == ["brief", "imessage"]
    assert (host.home / "state/.usage-remind-last").exists()


@pytest.mark.parametrize(("age", "sent"), [(3500, False), (3700, True)])
def test_once_per_interval(host, age, sent):
    host.note()
    host.stamp(age)
    host.run()
    assert bool(host.sends) is sent


def test_every_variable_overrides_interval(host):
    host.note()
    host.stamp(100)
    host.run()
    assert host.sends == []
    host.run(EVERY="50")
    assert len(host.sends) == 2


@pytest.mark.parametrize(("age", "text"), [(300, "[iMessage from the owner] hi"), (10, "a stalled wake")])
def test_old_or_foreign_note_sends_nothing(host, age, text):
    host.note(age, text)
    host.run()
    assert host.sends == []


def test_usage_averages_accounts_and_takes_soonest_reset(monkeypatch):
    brief = load("fm-usage-brief")
    now = 1_000_000.0

    def limit(used, reset):
        return {"scope": {"windowId": "5h"}, "amount": {"used": used}, "window": {"resetsAt": (now + reset) * 1000}}

    reports = {
        "reports": [
            {"provider": "anthropic", "limits": [limit(10, 7200), limit(30, 3600)]},
            {"provider": "anthropic", "limits": [{**limit(99, 60), "scope": {"windowId": "5h", "tier": "opus"}}]},
            {"provider": "other", "limits": [limit(90, 60)]},
        ]
    }
    monkeypatch.setattr(brief.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(reports), ""))
    assert brief.usage(now) == [("Claude", "5h", 20, "1h 0m")]


def test_text_card_maps_line_kinds():
    page, height = load("fm-text-card").render("Title & co\n# Sec\n- item\nkey: val\nplain <b>\n\nend")
    assert "<h1>Title &amp; co</h1>" in page
    assert "<h2>Sec</h2>" in page and 'class="b"' in page and 'class="k">key' in page
    assert "plain &lt;b&gt;" in page and 'class="gap"' in page
    assert height > 0


def test_chrome_falls_back_to_omp_puppeteer(tmp_path, monkeypatch):
    card = load("fm-text-card")
    old, new = (tmp_path / ".omp/puppeteer/chrome" / v / "chrome-linux64/chrome" for v in ("linux-1.0", "linux-2.0"))
    for path in (old, new):
        path.parent.mkdir(parents=True)
        path.touch()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CHROME", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert card.chrome() == str(new)
    monkeypatch.setenv("CHROME", "/custom/chrome")
    assert card.chrome() == "/custom/chrome"
    monkeypatch.delenv("CHROME")
    monkeypatch.setenv("HOME", str(tmp_path / "none"))
    with pytest.raises(SystemExit):
        card.chrome()


def test_stall_nudge_service_runs_usage_remind_after_nudge_failure():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(MAINT.parents[1] / "blueprint/ansible/templates"))
    env.filters["comment"] = lambda s: "# " + s
    unit = env.get_template("fm-main-stall-nudge.service.j2")
    text = unit.render(
        ansible_managed="", crewship_stall_nudge_script="/bin/nudge", crewship_local_bin="/bin", crewship_herdr_bin="h",
        crewship_stall_nudge_session="s", crewship_firstmate_dir="f", crewship_stall_nudge_note_max=1,
        crewship_stall_nudge_wake_max=1, crewship_stall_nudge_board_max=1, crewship_stall_nudge_gap=1,
        crewship_stall_nudge_pane="p", crewship_usage_remind_every=1, crewship_usage_disks=["/", "/data"],
    )
    execs = [line.partition("=")[2] for line in text.splitlines() if line.startswith("ExecStart=")]
    assert execs == ["-/bin/nudge", "-/bin/fm-usage-remind"]
    # systemd splits an Environment= line on unquoted whitespace, so a multi-disk value must survive that split.
    env_vars = dict(a.split("=", 1) for line in text.splitlines() if line.startswith("Environment=") for a in shlex.split(line.partition("=")[2]))
    assert env_vars["USAGE_DISKS"] == "/ /data"
