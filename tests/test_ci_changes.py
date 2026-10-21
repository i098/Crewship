import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

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


def outputs(directory, event="pull_request"):
    returncode, text = classify(directory, event)
    assert returncode == 0
    return dict(line.split("=", 1) for line in text.splitlines())


def commit_change(directory, old, new):
    def git(*args):
        subprocess.run(["git", *args], cwd=directory, check=True, capture_output=True)

    git("init", "--quiet")
    git("config", "user.name", "CI test")
    git("config", "user.email", "ci-test")
    if old:
        source = directory / old
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("content\n")
        git("add", ".")
    git("commit", "--quiet", "--allow-empty", "-m", "base")
    if old:
        source.unlink()
    paths = [new] if isinstance(new, str) else new or []
    for path in paths:
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("content\n")
    git("add", ".")
    git("commit", "--quiet", "-m", "change")


@pytest.mark.parametrize(("old", "new", "expected"), [
    (None, "README.txt", "false"),
    (None, "docs/nested/example.py", "false"),
    (None, "changelog.d/250.changed.md", "false"),
    (None, "nested/notes.md", "false"),
    (None, "site/public/harbor.js", "false"),
    (None, ("site/public/harbor.js", "scripts/example.py"), "true"),
    (None, ("docs/probe.md", "site/public/harbor.js"), "false"),
    (None, "site-lookalike/example.py", "true"),
    ("code.py", "site/public/code.py", "true"),
    ("site/public/code.py", "code.py", "true"),
    (None, "blueprint/skills/public/example/SKILL.md", "true"),
    (None, "blueprint/rules/public/example.md", "true"),
    (None, "blueprint/config/README.md", "true"),
    (None, ".github/workflows/ci.yml", "true"),
    (None, "nested/README.txt", "true"),
    (None, "docs-lookalike/file.py", "true"),
    (None, "bad\nname.py", "true"),
    ("code.py", "docs/code.py", "true"),
    ("docs/code.py", "code.py", "true"),
    ("docs/old.md", "docs/new.md", "false"),
    ("blueprint/skills/old.md", None, "true"),
    ("docs/old.md", None, "false"),
])
def test_changed_paths(tmp_path, old, new, expected):
    commit_change(tmp_path, old, new)
    assert outputs(tmp_path)["code"] == expected


@pytest.mark.parametrize(("new", "scope"), [
    ("apps/imessage/bridge.ts", "imessage"),
    (("apps/imessage/bridge.ts", "apps/imessage/memory.ts"), "imessage"),
    (("apps/imessage/bridge.ts", "docs/imessage.md", "changelog.d/1.fixed.md"), "imessage"),
    ("apps/imessage/NOTES.md", "all"),
    (("apps/imessage/bridge.ts", "scripts/ship.py"), "all"),
    (("apps/imessage/bridge.ts", "blueprint/config/default.yml"), "all"),
    (("apps/imessage/bridge.ts", "tests/conftest.py"), "all"),
    (("apps/imessage/bridge.ts", "blueprint/ansible/site.yml"), "all"),
    (("apps/imessage/bridge.ts", "pyproject.toml"), "all"),
    (("apps/imessage/bridge.ts", ".github/workflows/ci.yml"), "all"),
    (("apps/imessage/bridge.ts", "site/public/harbor.js"), "all"),
    ("imessage-lookalike/bridge.ts", "all"),
    ("docs/imessage.md", "all"),
])
def test_imessage_only_changes_narrow_the_python_tests(tmp_path, new, scope):
    commit_change(tmp_path, None, new)
    assert outputs(tmp_path)["scope"] == scope


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_non_pr_runs_without_a_checkout(tmp_path, event):
    assert classify(tmp_path, event) == (0, "code=true\nscope=all\n")


def test_missing_base_fails_without_skip_output(tmp_path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True, capture_output=True)
    code, output = classify(tmp_path)
    assert code != 0
    assert output == ""


def workflow_context(event, changes, code, *, python="success", runtime="success"):
    return {
        "github": SimpleNamespace(event_name=event),
        "needs": SimpleNamespace(
            changes=SimpleNamespace(result=changes, outputs=SimpleNamespace(code=code)),
            python_checks=SimpleNamespace(result=python),
            runtime_smoke=SimpleNamespace(result=runtime),
        ),
        "always": lambda: True,
    }


def expression_value(expression, context):
    expression = expression.removeprefix("${{").removesuffix("}}").strip()
    expression = expression.replace("&&", " and ").replace("||", " or ")
    return eval(f"({expression})", {"__builtins__": {}}, context)


def job_runs(job, context):
    dependencies = job.get("needs", [])
    if isinstance(dependencies, str):
        dependencies = [dependencies]
    condition = job.get("if", "True")
    if "always()" not in condition and any(
        getattr(context["needs"], name).result != "success" for name in dependencies
    ):
        return False
    return expression_value(condition, context)


def run_gate(job, context):
    step = job["steps"][0]
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
        env={key: expression_value(value, context) for key, value in step["env"].items()},
        capture_output=True,
        text=True,
    ).returncode


@pytest.mark.parametrize("changes", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("code", ["true", "false", "", "invalid"])
def test_required_check_rejects_prerequisite_failure(changes, code):
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    job = jobs["config-and-python"]
    context = workflow_context("pull_request", changes, code)
    valid = changes == "success" and code in {"true", "false"}
    assert job_runs(job, context) == (not valid or code == "true")
    if job_runs(job, context):
        assert (run_gate(job, context) == 0) == valid


@pytest.mark.parametrize("event", ["pull_request", "push", "workflow_dispatch"])
@pytest.mark.parametrize("code", ["true", "false"])
def test_heavy_job_event_policy(event, code):
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    context = workflow_context(event, "success", code)
    for name in ["config-and-python", "python_checks", "runtime_smoke",
                 "crewboard", "harbor-webkit", "container-smoke"]:
        assert job_runs(jobs[name], context) == (code == "true")
    assert job_runs(jobs["quality-gate"], context) == (
        event == "pull_request" and code == "true"
    )


@pytest.mark.parametrize("python", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("runtime", ["success", "failure", "cancelled", "skipped"])
def test_required_gate_preserves_both_workload_results(python, runtime):
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    context = workflow_context("pull_request", "success", "true", python=python, runtime=runtime)
    gate = jobs["config-and-python"]
    assert job_runs(gate, context)
    assert (run_gate(gate, context) == 0) == (python == runtime == "success")
