import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_pr.py"
SPEC = importlib.util.spec_from_file_location("check_pr", SCRIPT)
check_pr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_pr)

BODY = "Closes #12\n\nReview plan: run the new test.\n"
SHOT = "![after](https://example.com/a.png)\n"


def test_commit_subjects():
    assert check_pr.check_commits(["feat(ci): add x", "fix!: drop y"]) == []
    assert len(check_pr.check_commits(["Merge branch cleanup into utils"])) == 1
    for bad in [
        "Update thing",
        "fix(CI): x",
        "fix: done.",
        "feat:x",
        "wip: x",
        "fix: " + "a" * 100,
    ]:
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


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _run(repo, monkeypatch, *argv):
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["check_pr.py", *argv])
    return check_pr.main()


def test_main_checks_base_range_and_detects_ui(tmp_path, monkeypatch, capsys):
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "a.txt").write_text("a")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Old bad subject")
    (tmp_path / "ui.css").write_text("x")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "feat(ui): style")
    body = tmp_path / "body.md"
    body.write_text(BODY)
    assert _run(tmp_path, monkeypatch, str(body), "--base", "HEAD~1") == 1
    assert "screenshot" in capsys.readouterr().err
    body.write_text(BODY + SHOT)
    assert _run(tmp_path, monkeypatch, str(body), "--base", "HEAD~1") == 0
    (tmp_path / "b.txt").write_text("b")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Merge branch cleanup into utils")
    body.write_text(BODY)
    assert _run(tmp_path, monkeypatch, str(body), "--base", "HEAD~1", "--no-ui") == 1
    assert _run(tmp_path, monkeypatch, str(body), "--base", "nope") == 2
