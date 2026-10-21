import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/new-issue"
loader = importlib.machinery.SourceFileLoader("new_issue", str(SCRIPT))
spec = importlib.util.spec_from_loader("new_issue", loader)
new_issue = importlib.util.module_from_spec(spec)
loader.exec_module(new_issue)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_missing_or_empty_required_field_is_refused():
    with pytest.raises(ValueError, match="proposal"):
        new_issue.build("feature", "T", {"problem": "p"})
    with pytest.raises(ValueError, match="problem"):
        new_issue.build("feature", "T", {"problem": "  ", "proposal": "x"})


def test_headings_follow_form_order_and_labels_come_from_template():
    labels, body = new_issue.build("feature", "T", {"proposal": "B", "problem": "A"})
    assert labels == ["enhancement"]
    assert body.index("### Problem") < body.index("### Proposal")


def test_bug_form_fences_logs_and_marks_empty_optional():
    labels, body = new_issue.build("bug", "T", {"what-happened": "w", "steps": "s", "version": "v", "logs": "boom"})
    assert labels == ["bug"]
    assert "### Host\n\n_No response_" in body
    assert "```text\nboom\n```" in body


@pytest.mark.parametrize("title", ["feat: x", "fix(ui)!: x", "Chore: x"])
def test_conventional_prefix_title_is_rejected(title):
    with pytest.raises(ValueError, match="prefix"):
        new_issue.build("feature", title, {"problem": "p", "proposal": "q"})


def test_dry_run_prints_title_labels_body_from_file_field(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("from file")
    r = run("feature", "--title", "Do it", "--field", f"problem=@{f}", "--field", "proposal=q", "--dry-run")
    assert r.returncode == 0
    assert r.stdout.startswith("title: Do it\nlabels: enhancement\n\n### Problem\n\nfrom file")


def test_cli_refuses_missing_field():
    r = run("feature", "--title", "Do it", "--field", "problem=p", "--dry-run")
    assert r.returncode != 0 and "proposal" in r.stderr


@pytest.mark.parametrize("error_body", ["", '{"message":"Validation Failed","errors":[{"field":"title","code":"invalid"}]}\n'])
def test_create_failure_reports_child_output(tmp_path, monkeypatch, error_body):
    summary = "gh: Validation Failed (HTTP 422)\n"
    gh = tmp_path / "gh"
    gh.write_text(f"#!/bin/sh\nprintf '%s' '{error_body}'\nprintf '%s' '{summary}' >&2\nexit 1\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    result = run("feature", "-R", "i098/Crewship", "--title", "Do it", "--field", "problem=p", "--field", "proposal=q")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == summary + error_body


def recording_gh(tmp_path, monkeypatch):
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\nfrom pathlib import Path\n"
        f"Path({str(tmp_path / 'argv')!r}).write_text(json.dumps(sys.argv[1:]))\n"
        f"Path({str(tmp_path / 'stdin')!r}).write_text(sys.stdin.read())\n"
        "print(json.dumps({'html_url': 'https://example.test/1'}))\n"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    return tmp_path / "argv", tmp_path / "stdin"


FIELDS = ("--title", "Do it", "--field", "problem=p", "--field", "proposal=q")


@pytest.mark.parametrize("flag", ["-R", "--repo"])
def test_create_posts_to_supplied_repository(tmp_path, monkeypatch, flag):
    argv, stdin = recording_gh(tmp_path, monkeypatch)

    result = run("feature", flag, "i098/Crewship", *FIELDS)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "https://example.test/1\n"
    assert json.loads(argv.read_text()) == ["api", "-X", "POST", "repos/i098/Crewship/issues", "--input", "-"]
    payload = json.loads(stdin.read_text())
    assert payload["title"] == "Do it" and payload["labels"] == ["enhancement"]


@pytest.mark.parametrize(
    "repo", [None, "", "i098", "{owner}/{repo}", ":owner/:repo", "i098/Crewship/x", "../x", "i098/..", "a b/c", "i098/Crewship\n"]
)
def test_missing_or_invalid_repository_never_starts_gh(tmp_path, monkeypatch, repo):
    argv, _ = recording_gh(tmp_path, monkeypatch)
    target = () if repo is None else ("--repo", repo)

    result = run("feature", *target, *FIELDS)

    assert result.returncode != 0
    assert "--repo" in result.stderr
    assert not argv.exists()


@pytest.mark.parametrize("target", [(), ("--repo", "i098/Crewship")])
def test_dry_run_never_starts_gh(tmp_path, monkeypatch, target):
    argv, _ = recording_gh(tmp_path, monkeypatch)

    result = run("feature", *target, *FIELDS, "--dry-run")

    assert result.returncode == 0
    assert result.stdout.startswith("title: Do it\nlabels: enhancement\n")
    assert not argv.exists()
