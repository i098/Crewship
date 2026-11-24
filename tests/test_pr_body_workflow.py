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


def test_workflow_checkout_retains_the_pr_merge_base(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/pr-body.yml").read_text())
    steps = workflow["jobs"]["pr-body"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    checkout_inputs = checkout.get("with", {})
    assert not checkout_inputs.get("ref"), "Use the pull_request event's synthetic merge checkout"
    depth = checkout_inputs.get("fetch-depth", 1)
    body_step = next(step for step in steps if "PR_BODY" in step.get("env", {}))
    assert body_step["env"]["PR_BASE"] == "${{ github.event.pull_request.base.sha }}"
    assert body_step["env"]["PR_HEAD"] == "${{ github.event.pull_request.head.sha }}"
    source = tmp_path / "source"
    source.mkdir()

    def git(*args):
        subprocess.run(
            ["git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@t", *args],
            check=True,
            capture_output=True,
        )

    git("init", "-b", "main")
    git("commit", "--allow-empty", "-m", "Common ancestor")
    git("branch", "pr")
    (source / "site/public").mkdir(parents=True)
    (source / "site/public/harbor.css").write_text("body { color: red; }\n")
    git("add", ".")
    git("commit", "-m", "Stylesheet on base")
    git("checkout", "pr")
    git("cherry-pick", "--no-commit", "main")
    git("commit", "-m", "Same stylesheet change on PR")
    git("checkout", "main")
    for path in ("scripts/check_pr_body.py", ".github/PULL_REQUEST_TEMPLATE.md"):
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / path).read_bytes())
    git("add", ".")
    git("commit", "-m", "Roll out new body checker")
    git("merge", "--no-ff", "-m", "Synthetic pull request merge", "pr")

    worktree = tmp_path / "checkout"
    clone_depth = ["--depth", str(depth)] if depth else []
    git("clone", *clone_depth, source.as_uri(), str(worktree))
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", body_step["run"]],
        cwd=worktree,
        env={
            **os.environ,
            "PR_BODY": VALID_BODY,
            "PR_TITLE": "docs: roll out the body checker",
            "PR_BASE": "HEAD^1",
            "PR_HEAD": "HEAD^2",
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 1, result.stderr
    assert "Include exactly one ## Review evidence section." in result.stderr


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
    indexnow = repo / "site/public/e3c5c1952d33a0d51288552a3907210a.txt"
    indexnow.parent.mkdir(parents=True)
    indexnow.write_text("verification key\n")
    (indexnow.parent / "google2a77445d3f9ccb0e.html").write_text("site verification\n")
    git("add", "site")
    git("commit", "-m", "Site verification files")
    env = {**os.environ, "GIT_DIR": str(repo / ".git"), "GIT_WORK_TREE": str(repo)}
    before = "![Before](https://github.com/user-attachments/assets/347457ab-5159-470e-913b-b2023f215543)"
    after = "![After](https://github.com/user-attachments/assets/672de857-f49e-4def-95f8-b576d8290bb6)"
    heading = "\n## Review evidence\n\n"

    def check(body, error="", title=""):
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
            cwd=ROOT,
            env={
                **env,
                "PR_BODY": body,
                "PR_TITLE": title,
                "PR_BASE": "HEAD^",
                "PR_HEAD": "HEAD",
            },
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
    check("Refs #695\n", "Include exactly one ## Summary section.")

    for path in (
        "site/public/about.html",
        "site/public/harbor.js",
        "site/build.py",
        "tools/runs-tui/runs-tui.ts",
        "tools/tui-theme/theme.ts",
    ):
        source = repo / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("view source\n")
        git("add", path)
        git("commit", "-m", f"Change {path}")
        check(VALID_BODY, "Include exactly one ## Review evidence section.")

    git("commit", "--allow-empty", "-m", "feat: name the issue (fixes #7)")
    check(VALID_BODY, "a merge never closes an issue")
    git("commit", "--allow-empty", "-m", "docs: note the rule")
    check(VALID_BODY, "a merge never closes an issue", "fix: x (closes #7)")
    git("commit", "--allow-empty", "-m", "feat: y", "-m", "Closes #7")
    check(VALID_BODY, "a merge never closes an issue")

    test_source = repo / "tools/runs-tui/runs-tui.test.ts"
    test_source.write_text("test source\n")
    git("add", str(test_source))
    git("commit", "-m", "Test change only")
    check(VALID_BODY)

    sample = repo / "blueprint/skills/public/openmontage/scenes/beat.tsx"
    sample.parent.mkdir(parents=True)
    sample.write_text("video sample\n")
    git("add", str(sample))
    git("commit", "-m", "Change a video sample")
    check(VALID_BODY)

    (repo / "site/public/harbor.css").write_text("body { color: red; }\n")
    git("add", "site/public/harbor.css")
    git("commit", "-m", "UI change")
    check(VALID_BODY, "Include exactly one ## Review evidence section.")
    misplaced = VALID_BODY.replace("```text", before + "\n" + after + "\n\n```text", 1)
    check(misplaced + heading + "Screenshots pending.", "screenshot")
    check(
        VALID_BODY + f'\n<PRE class="example">\n{heading}\n{before}\n{after}\n</PRE>\n',
        "Include exactly one ## Review evidence section.",
    )
    check(
        VALID_BODY + f"\n<!-- Heading -->## Review evidence\n{before}\n{after}\n",
        "Include exactly one ## Review evidence section.",
    )
    same_upload = after.replace("After", "Before").replace("672de857", "672DE857")
    for evidence in (
        after,
        "Before: none, new view",
        f"{same_upload}\n{after}",
        f"{before}\n{same_upload}\n{after}",
        f"{before}\n{after}\n{before.replace('Before', 'After')}",
        f"Before: none, new view\n{same_upload}\n{after}",
        f"Before: none, new view\n{before}\n{after}",
        f"<pre>\n{before}\n{after}\n</pre>",
        f"<pre>\nBefore: none, new view\n</pre>\n{after}",
        f"<!-- Base revision -->{before}\n{after}",
        f"{before}\n<!-- Head revision -->{after}",
        f"<!-- New view -->Before: none, new view\n{after}",
        f'<div align="center">{before}\n{after}',
        f"<!--\n{before}\n-->\n{after}",
        f"<!-- Base revision\n-->{before}\n{after}",
        f"```md\n{before}\n{after}\n```",
        f"    {before}\n    {after}",
        f"{before}\n{after[:-1]}",
        f"Before: none, new view\n{after.replace('github.com', 'example.com')}",
    ):
        check(VALID_BODY + heading + evidence, "screenshot")
    check(VALID_BODY + heading + before + "\n" + after)
    check(VALID_BODY + heading + before + "<!-- Base -->\n" + after)
    check(VALID_BODY + heading + f"<pre>\n## Sample\n</pre>\n\n{before}\n{after}")
    for tag in ("script", "style", "textarea"):
        block = f'<{tag}>\n"<!--"\n{before}\n{after}\n</{tag}>\n\n'
        check(VALID_BODY + heading + block, "screenshot")
        check(VALID_BODY + heading + block + before + "\n" + after)
    check(VALID_BODY + heading + "Before: none, new view\n" + after)
    check(
        VALID_BODY + heading + before + "\n" + after + heading,
        "Include exactly one ## Review evidence section.",
    )

    git("mv", "site/public/harbor.css", "styles.txt")
    git("commit", "-m", "Remove the stylesheet")
    check(VALID_BODY, "Include exactly one ## Review evidence section.")
