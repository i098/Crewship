import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def classify(directory, event="pull_request"):
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    script = next(s["run"] for s in workflow["jobs"]["changes"]["steps"] if s.get("id") == "diff")
    output = directory / "output"
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=directory,
        env={
            **os.environ,
            "EVENT_NAME": event,
            "RUNNER_TEMP": str(directory),
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
    )
    return result.returncode, output.read_text() if output.exists() else ""


@pytest.mark.parametrize(("old", "new", "expected"), [
    (None, "README.txt", "false"),
    (None, "docs/nested/example.py", "false"),
    (None, "changelog.d/250.changed.md", "false"),
    (None, "nested/notes.md", "false"),
    (None, "skills/public/example/SKILL.md", "true"),
    (None, "rules/public/example.md", "true"),
    (None, "config/README.md", "true"),
    (None, ".github/workflows/ci.yml", "true"),
    (None, "nested/README.txt", "true"),
    (None, "docs-lookalike/file.py", "true"),
    (None, "bad\nname.py", "true"),
    ("code.py", "docs/code.py", "true"),
    ("docs/code.py", "code.py", "true"),
    ("docs/old.md", "docs/new.md", "false"),
    ("skills/old.md", None, "true"),
    ("docs/old.md", None, "false"),
])
def test_changed_paths(tmp_path, old, new, expected):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "--quiet")
    git("config", "user.name", "CI test")
    git("config", "user.email", "ci-test")
    if old:
        source = tmp_path / old
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("content\n")
        git("add", ".")
    git("commit", "--quiet", "--allow-empty", "-m", "base")
    if old:
        source.unlink()
    if new:
        target = tmp_path / new
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("content\n")
    # Mix in a docs change so one code path must still run heavy CI.
    (tmp_path / "README.md").write_text("docs\n")
    git("add", ".")
    git("commit", "--quiet", "-m", "change")
    assert classify(tmp_path) == (0, f"code={expected}\n")


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_non_pr_runs_without_a_checkout(tmp_path, event):
    assert classify(tmp_path, event) == (0, "code=true\n")


def test_missing_base_fails_without_skip_output(tmp_path):
    code, output = classify(tmp_path)
    assert code != 0
    assert output == ""
