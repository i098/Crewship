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
    assert set(pull_request["types"]) == {"opened", "edited", "synchronize", "reopened"}
    assert not {"paths", "paths-ignore", "branches", "branches-ignore"} & pull_request.keys()
    assert "if" not in workflow["jobs"]["pr-body"]
    assert workflow["permissions"] == {"contents": "read"}
    build = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    build_events = build.get("on", build.get(True))
    assert "edited" not in build_events["pull_request"]["types"]


def test_workflow_checks_the_body_and_detects_ui_without_a_label(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/pr-body.yml").read_text())
    step = next(
        step for step in workflow["jobs"]["pr-body"]["steps"] if "PR_BODY" in step.get("env", {})
    )
    marker = tmp_path / "must-not-exist"
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=True,
            capture_output=True,
        )

    git("init")
    git("commit", "--allow-empty", "-m", "Base")
    git("commit", "--allow-empty", "-m", "Non-UI change")
    env = {**os.environ, "GIT_DIR": str(repo / ".git"), "GIT_WORK_TREE": str(repo)}
    before = "![Before](https://github.com/user-attachments/assets/347457ab-5159-470e-913b-b2023f215543)"
    after = "![After](https://github.com/user-attachments/assets/672de857-f49e-4def-95f8-b576d8290bb6)"
    heading = "\n## Review evidence\n\n"

    def check(body, error=""):
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
            cwd=ROOT,
            env={**env, "PR_BODY": body},
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == int(bool(error)), result.stderr
        if error:
            assert error in result.stderr
        assert not marker.exists()

    check(VALID_BODY + f"\n$(touch {marker})\n")
    check(VALID_BODY + heading + "<!-- No UI changes. -->\n")
    check("Closes #695\n", "Include exactly one ## Summary section.")

    (repo / "ui.css").write_text("body { color: red; }\n")
    git("add", "ui.css")
    git("commit", "-m", "UI change")
    check(VALID_BODY, "Include exactly one ## Review evidence section.")
    misplaced = VALID_BODY.replace("```text", before + "\n" + after + "\n\n```text", 1)
    check(misplaced + heading + "Screenshots pending.", "screenshot")
    for evidence in (
        after,
        "Before: none, new view",
        f"<!--\n{before}\n-->\n{after}",
        f"```md\n{before}\n{after}\n```",
        f"    {before}\n    {after}",
        f"{before}\n{after[:-1]}",
        f"Before: none, new view\n{after.replace('github.com', 'example.com')}",
    ):
        check(VALID_BODY + heading + evidence, "screenshot")
    check(VALID_BODY + heading + before + "\n" + after)
    check(VALID_BODY + heading + "Before: none, new view\n" + after)
    check(
        VALID_BODY + heading + before + "\n" + after + heading,
        "Include exactly one ## Review evidence section.",
    )

    git("mv", "ui.css", "styles.txt")
    git("commit", "-m", "Remove the stylesheet")
    check(VALID_BODY, "Include exactly one ## Review evidence section.")
