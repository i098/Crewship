import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_pr.py"


@pytest.fixture
def check_pr(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    import check_pr

    return check_pr


BODY = "Refs #12\n\nReview plan: run the new test.\n"
SHOT = (
    "\n## Review evidence\n\nBefore: none, new view\n"
    "![After](https://github.com/user-attachments/assets/672de857-f49e-4def-95f8-b576d8290bb6)\n"
)


def test_commit_subjects(check_pr):
    assert check_pr.check_commits(["feat(ci): add x", "fix!: drop y"]) == []
    assert check_pr.check_commits(["no-mistakes(review): Reuse CI issue-reference check"]) == []
    assert len(check_pr.check_commits(["Merge branch cleanup into utils"])) == 1
    for bad in [
        "Update thing",
        "fix(CI): x",
        "fix: done.",
        "feat:x",
        "wip: x",
        "no-mistakes: x",
        "fix: " + "a" * 100,
    ]:
        assert len(check_pr.check_commits([bad])) == 1, bad


def test_body_needs_issue_first_and_plan(check_pr):
    assert check_pr.check_body(BODY, False) == []
    assert len(check_pr.check_body("Summary\nRefs #12\nReview plan: x", False)) == 1
    assert len(check_pr.check_body("Refs #12\n", False)) == 1
    assert len(check_pr.check_body("```\nRefs #1\nReview plan: x\n```\n", False)) == 2
    errors = check_pr.check_body("Refs #12\nMerge fixes #12.\nReview plan: x", False)
    assert any("a merge never closes an issue" in e for e in errors)


def test_ui_needs_hosted_image_in_review_evidence(check_pr):
    assert check_pr.check_body(BODY, True)
    assert check_pr.check_body(BODY + SHOT.replace("github.com", "example.com"), True)
    assert check_pr.check_body(BODY + SHOT.replace("Review evidence", "Test evidence"), True)
    assert check_pr.check_body(BODY + SHOT, True) == []


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def _run(check_pr, repo, monkeypatch, *argv):
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["check_pr.py", *argv])
    return check_pr.main()


def test_main_checks_base_range_and_detects_ui(check_pr, tmp_path, monkeypatch, capsys):
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "a.txt").write_text("a")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Old bad subject")
    site = tmp_path / "site"
    site.mkdir()
    tui = tmp_path / "tools/runs-tui"
    tui.mkdir(parents=True)
    (tui / "runs-tui.ts").write_text("view source\n")
    _git(tmp_path, "config", "diff.relative", "true")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "feat(ui): style")
    body = tmp_path / "body.md"
    body.write_text(BODY)
    assert _run(check_pr, site, monkeypatch, str(body), "--base", "HEAD~1") == 1
    assert "## Review evidence" in capsys.readouterr().err
    body.write_text(BODY + SHOT)
    assert _run(check_pr, site, monkeypatch, str(body), "--base", "HEAD~1") == 0
    (tmp_path / "b.txt").write_text("b")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "Merge branch cleanup into utils")
    body.write_text(BODY)
    assert _run(check_pr, tmp_path, monkeypatch, str(body), "--base", "HEAD~1", "--no-ui") == 1
    assert _run(check_pr, tmp_path, monkeypatch, str(body), "--base", "nope") == 2


def test_main_rejects_closing_keyword_in_the_title(check_pr, tmp_path, monkeypatch, capsys):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "commit", "--allow-empty", "-m", "Base")
    body = tmp_path / "body.md"
    body.write_text(BODY)
    argv = (str(body), "--base", "HEAD", "--no-ui", "--title", "fix: x (closes #7)")
    assert _run(check_pr, tmp_path, monkeypatch, *argv) == 1
    assert "a merge never closes an issue" in capsys.readouterr().err


def test_main_rejects_closing_keyword_in_a_commit_message(check_pr, tmp_path, monkeypatch, capsys):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "commit", "--allow-empty", "-m", "Base")
    body = tmp_path / "body.md"
    body.write_text(BODY)
    _git(tmp_path, "commit", "--allow-empty", "-m", "feat(ci): use Refs in bodies (closes #1445)")
    assert _run(check_pr, tmp_path, monkeypatch, str(body), "--base", "HEAD~1", "--no-ui") == 1
    assert "a merge never closes an issue" in capsys.readouterr().err
    _git(tmp_path, "commit", "--allow-empty", "-m", "feat: y", "-m", "Closes #7")
    assert _run(check_pr, tmp_path, monkeypatch, str(body), "--base", "HEAD~1", "--no-ui") == 1
    assert "a merge never closes an issue" in capsys.readouterr().err
