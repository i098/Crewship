"""blueprint/config/omp-quality-gate.ts, run under bun with a fake omp extension API.

Fake `sentrux` and `fallow` commands on PATH print canned output and log each
call, so no real tool and no network is involved.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BUN = shutil.which("bun")

pytestmark = pytest.mark.skipif(not BUN, reason="needs bun")

# Each fake prints the file named by $FAKE_<TOOL>_OUT and exits with $FAKE_<TOOL>_RC.
FAKE = """#!/bin/sh
echo "$(basename "$0") $*" >> "$FAKE_CALLS"
tool=$(basename "$0" | tr a-z A-Z)
eval "out=\\${FAKE_${tool}_OUT:-}; rc=\\${FAKE_${tool}_RC:-0}"
[ -n "$out" ] && cat "$out"
exit "$rc"
"""

DRIVER = """
import ext from %(ext)s;
import { appendFileSync } from "node:fs";
const handlers = {};
ext({ on: (event, handler) => (handlers[event] = handler) });
const ctx = { cwd: %(cwd)s };
const results = [];
for (const step of %(steps)s) {
  if (step === "start") await handlers.agent_start({ type: "agent_start" }, ctx);
  else if (step === "edit") appendFileSync(%(cwd)s + "/work.txt", "change\\n");
  else if (step === "stop" || step === "stop-again") {
    const event = { type: "session_stop", stop_hook_active: step === "stop-again", signal: new AbortController().signal };
    results.push(await handlers.session_stop(event, ctx));
  } else if (step === "next") {
    let message;
    for (let i = 0; i < 100 && !message; i++) {
      message = (await handlers.before_agent_start({ type: "before_agent_start" }, ctx)).message;
      if (!message) await Bun.sleep(50);
    }
    results.push(message ?? null);
  }
}
console.log(JSON.stringify(results));
"""


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A committed git repository with a sentrux baseline and fakes on PATH."""
    work = tmp_path / "repo"
    (work / ".sentrux").mkdir(parents=True)
    (work / ".sentrux/baseline.json").write_text("{}\n")
    (work / "work.txt").write_text("start\n")
    git(work, "init", "-q")
    git(work, "add", "-A")
    git(work, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "init")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("sentrux", "fallow"):
        (bin_dir / tool).write_text(FAKE)
        (bin_dir / tool).chmod(0o755)
    return work


def drive(repo, steps, gate="", env=None, tools=("sentrux", "fallow")):
    """Run the steps; return the handler results and the fake tool calls."""
    bin_dir = repo.parent / "bin"
    for tool in ("sentrux", "fallow"):
        if tool not in tools:
            (bin_dir / tool).unlink(missing_ok=True)
    calls = repo.parent / "calls"
    calls.write_text("")
    out = repo.parent / "gate.out"
    out.write_text(gate)
    environment = {
        "HOME": str(repo.parent),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "FAKE_CALLS": str(calls),
        "FAKE_SENTRUX_OUT": str(out),
        **(env or {}),
    }
    code = DRIVER % {
        "ext": json.dumps(str(ROOT / "blueprint/config/omp-quality-gate.ts")),
        "cwd": json.dumps(str(repo)),
        "steps": json.dumps(steps),
    }
    run = subprocess.run([BUN, "-e", code], capture_output=True, text=True, env=environment)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout), calls.read_text().splitlines()


def blocked(result):
    return result.get("continue") is True and "additionalContext" in result


DEGRADED = "Quality:      7000 -> 6990\n✗ Coupling up\nDEGRADED\n"


@pytest.mark.parametrize(
    ("gate", "env", "blocks"),
    [
        (DEGRADED, {}, True),
        ("Quality:      7000 -> 6700\n✓ No degradation detected\n", {}, True),
        ("Quality:      7000 -> 6800\n✓ No degradation detected\n", {}, False),
        ("Quality:      1200 -> 1200\n✓ No degradation detected\n", {}, False),
        ("Quality:      7000 -> 6700\n", {"FM_QUALITY_MAX_DROP": "400"}, False),
        (DEGRADED, {"SENTRUX_GATE": "advisory"}, False),
        ("segmentation fault\n\x00\x01 not a report\n", {}, False),
    ],
    ids=["degraded", "drop-over", "drop-under", "low-score", "raised-limit", "advisory", "garbage"],
)
def test_blocking_rule(repo, gate, env, blocks):
    [result], _ = drive(repo, ["start", "edit", "stop"], gate, env)
    assert blocked(result) is blocks
    if blocks:
        assert "sentrux gate --save ." in result["additionalContext"]


def test_missing_sentrux_does_not_block(repo):
    [result], _ = drive(repo, ["start", "edit", "stop"], DEGRADED, tools=("fallow",))
    assert result == {}


def test_no_baseline_does_not_block_or_run_sentrux(repo):
    (repo / ".sentrux/baseline.json").unlink()
    [result], calls = drive(repo, ["start", "edit", "stop"], DEGRADED)
    assert result == {}
    assert calls == []


def test_a_turn_without_file_changes_is_not_gated(repo):
    [result], calls = drive(repo, ["start", "stop"], DEGRADED)
    assert result == {}
    assert calls == []


def test_blocks_once_per_turn_end_then_again_on_the_next_prompt(repo):
    steps = ["start", "edit", "stop", "start", "edit", "stop-again", "start", "edit", "stop"]
    first, continuation, next_prompt = drive(repo, steps, DEGRADED)[0]
    assert blocked(first)
    assert continuation == {}
    assert blocked(next_prompt)


def test_advisory_findings_surface_at_the_next_prompt_and_never_block(repo):
    (repo / "package.json").write_text("{}\n")
    (repo / ".sentrux/rules.toml").write_text("[constraints]\n")
    findings = repo.parent / "fallow.out"
    findings.write_text("unused-file:b.ts\n")
    env = {"FAKE_FALLOW_OUT": str(findings), "FAKE_FALLOW_RC": "1", "SENTRUX_GATE": "advisory"}
    (result, message), calls = drive(repo, ["start", "edit", "stop", "next"], "", env)
    assert result == {}
    assert "fallow audit --changed-since HEAD" in calls
    assert "sentrux check ." in calls
    assert "unused-file:b.ts" in message["content"]


def test_advisory_needs_uncommitted_changes_and_does_not_stack(repo):
    (repo / "package.json").write_text("{}\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-qm", "pkg")
    _, calls = drive(repo, ["start", "stop"])
    assert not any(call.startswith("fallow") for call in calls)
    _, calls = drive(repo, ["start", "edit", "stop", "start", "stop"])
    assert sum(call.startswith("fallow") for call in calls) == 1


def ci(repo, gate, rc=0, tools=True):
    out = repo.parent / "gate.out"
    out.write_text(gate)
    environment = {
        "PATH": f"{repo.parent / 'bin'}:/usr/bin:/bin" if tools else "/usr/bin:/bin",
        "FAKE_CALLS": os.devnull,
        "FAKE_SENTRUX_OUT": str(out),
        "FAKE_SENTRUX_RC": str(rc),
    }
    return subprocess.run(
        [BUN, str(ROOT / "blueprint/config/omp-quality-gate.ts")],
        cwd=repo,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_ci_entry_point_exits_1_on_a_block(repo):
    run = ci(repo, DEGRADED)
    assert run.returncode == 1
    assert "DEGRADED" in run.stderr


def test_ci_entry_point_passes_on_a_verdict_without_a_block(repo):
    run = ci(repo, "Quality:      7000 -> 6990\n✓ No degradation detected\n")
    assert run.returncode == 0
    assert "no block" in run.stdout


def test_ci_entry_point_fails_closed_without_sentrux(repo):
    run = ci(repo, "", tools=False)
    assert run.returncode == 1
    assert "did not run" in run.stderr


def test_ci_entry_point_fails_closed_on_a_crash(repo):
    run = ci(repo, "error while loading shared libraries: libgtk-3.so.0\n", rc=127)
    assert run.returncode == 1
    assert "no verdict (exit 127)" in run.stderr


def test_ci_entry_point_fails_closed_without_a_baseline(repo):
    (repo / ".sentrux/baseline.json").unlink()
    run = ci(repo, "Quality:      7000 -> 6990\n")
    assert run.returncode == 1
    assert "baseline.json is missing" in run.stderr
