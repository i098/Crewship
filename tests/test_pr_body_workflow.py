import os
import subprocess
from pathlib import Path

import yaml
from test_pr_body import VALID_BODY, checker

ROOT = Path(__file__).resolve().parents[1]


def test_publication_policy_selects_a_template_accepted_by_the_checker():
    policy = yaml.safe_load((ROOT / ".no-mistakes.yaml").read_text())["pr"]
    assert policy["publish_intent"] is False
    assert policy["appendix"] == "collapsed"
    template = (ROOT / policy["template"]).read_text()
    assert checker.check_body(VALID_BODY, template) == []


def test_body_edits_run_the_small_workflow_without_restarting_the_build():
    workflow = yaml.safe_load((ROOT / ".github/workflows/pr-body.yml").read_text())
    events = workflow.get("on", workflow.get(True))
    pull_request = events["pull_request"]
    assert {"opened", "edited", "synchronize", "reopened"} <= set(pull_request["types"])
    assert not {"paths", "paths-ignore", "branches", "branches-ignore"} & pull_request.keys()
    assert "if" not in workflow["jobs"]["pr-body"]
    assert workflow["permissions"] == {"contents": "read"}
    build = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    build_events = build.get("on", build.get(True))
    assert "edited" not in build_events["pull_request"]["types"]


def test_workflow_command_checks_the_body_without_evaluating_its_contents(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/pr-body.yml").read_text())
    step = next(
        step for step in workflow["jobs"]["pr-body"]["steps"] if "PR_BODY" in step.get("env", {})
    )
    marker = tmp_path / "must-not-exist"
    for body, expected in ((VALID_BODY + f"\n$(touch {marker})\n", 0), ("Closes #695\n", 1)):
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
            cwd=ROOT,
            env={**os.environ, "PR_BODY": body},
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == expected, result.stderr
        assert not marker.exists()
