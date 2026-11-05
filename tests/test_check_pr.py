import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_pr.py"
SPEC = importlib.util.spec_from_file_location("check_pr", SCRIPT)
check_pr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_pr)

BODY = "Closes #12\n\nReview plan: run the new test.\n"
SHOT = "![after](https://example.com/a.png)\n"


def test_commit_subjects():
    ok = ["feat(ci): add x", "fix!: drop y", "Merge pull request #1 from a/b"]
    assert check_pr.check_commits(ok) == []
    for bad in ["Update thing", "fix(CI): x", "fix: done.", "feat:x", "wip: x", "fix: " + "a" * 100]:
        assert len(check_pr.check_commits([bad])) == 1, bad


def test_body_needs_issue_first_and_plan():
    assert check_pr.check_body(BODY, False) == []
    assert len(check_pr.check_body("Summary\nCloses #12\nReview plan: x", False)) == 1
    assert len(check_pr.check_body("Closes #12\n", False)) == 1
    assert len(check_pr.check_body("```\nCloses #1\nReview plan: x\n```\n", False)) == 2


def test_ui_needs_hosted_image():
    assert len(check_pr.check_body(BODY, True)) == 1
    assert len(check_pr.check_body(BODY + "![x](shots/a.png)\n", True)) == 1
    assert check_pr.check_body(BODY + SHOT, True) == []
    assert check_pr.check_body(BODY + '<img src="https://e.com/a.png">', True) == []


def test_ui_paths():
    hit = check_pr.UI_PATH.search
    assert hit("apps/genui-web/app.tsx") and hit("site/index.md") and hit("a/b.css")
    assert not hit("scripts/ship.py") and not hit("docs/ci-pool.md")
