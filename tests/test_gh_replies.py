"""blueprint/maintenance/fm-gh-replies decision logic, with gh stubbed."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "blueprint/maintenance/fm-gh-replies"

# Answers `gh api -X GET <url>` from $ROUTES (url prefix -> JSON file); logs every call.
GH = """#!/usr/bin/env python3
import json, os, sys
url = sys.argv[-1]
open(os.environ["CALLS"], "a").write(url + "\\n")
for prefix, path in json.load(open(os.environ["ROUTES"])).items():
    if url.startswith(prefix):
        if path is None:
            sys.exit(1)
        sys.stdout.write(open(path).read())
        sys.exit(0)
sys.exit(1)
"""

FUTURE = "2999-01-01T00:00:00Z"


def user(login, kind="User"):
    return {"login": login, "type": kind}


@pytest.fixture
def host(tmp_path):
    (tmp_path / "bin").mkdir()
    gh = tmp_path / "bin/gh"
    gh.write_text(GH)
    gh.chmod(0o755)
    state = tmp_path / "state"
    calls = tmp_path / "calls"
    routes = {}

    class Host:
        dir = state

        def route(self, prefix, payload):
            path = tmp_path / f"r{len(routes)}.json"
            path.write_text(json.dumps(payload))
            routes[prefix] = str(path) if payload is not None else None
            (tmp_path / "routes.json").write_text(json.dumps(routes))

        def run(self):
            env = {
                **os.environ,
                "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
                "GH_REPLIES_ACCOUNT": "me",
                "GH_REPLIES_DIR": str(state),
                "CALLS": str(calls),
                "ROUTES": str(tmp_path / "routes.json"),
            }
            r = subprocess.run([SCRIPT], capture_output=True, text=True, env=env)
            assert r.returncode == 0, r.stderr
            return r.stdout.splitlines()

        def calls(self):
            return calls.read_text().splitlines() if calls.exists() else []

        def armed(self, since="2000-01-01T00:00:00Z"):
            state.mkdir(exist_ok=True)
            (state / "since").write_text(since)
            (state / "last-poll").unlink(missing_ok=True)

    return Host()


def notification(subject_type="Issue", comment="https://api/c/comments/1"):
    return [
        {
            "repository": {"full_name": "o/r"},
            "subject": {"type": subject_type, "url": "https://api/pr/1", "latest_comment_url": comment},
        }
    ]


def comment(login, kind="User", updated=FUTURE):
    return {"user": user(login, kind), "updated_at": updated, "html_url": "https://h/c1"}


def test_first_run_seeds_since_without_polling(host):
    assert host.run() == []
    assert (host.dir / "since").read_text()
    assert host.calls() == []


def test_polls_at_most_once_per_interval(host):
    host.armed()
    host.route("notifications", [])
    host.run()
    host.run()
    assert len(host.calls()) == 1


def test_reports_comment_by_other_person(host):
    host.armed()
    host.route("notifications", notification())
    host.route("https://api/c/comments/1", comment("alice"))
    assert host.run() == ["github reply: o/r comment by alice https://h/c1"]


@pytest.mark.parametrize("author,kind", [("me", "User"), ("ci[bot]", "Bot"), ("robot", "Bot")])
def test_ignores_self_and_bots(host, author, kind):
    host.armed()
    host.route("notifications", notification())
    host.route("https://api/c/comments/1", comment(author, kind))
    assert host.run() == []


def test_ignores_comment_older_than_since(host):
    host.armed(since="2999-06-01T00:00:00Z")
    host.route("notifications", notification())
    host.route("https://api/c/comments/1", comment("alice", updated=FUTURE[:4] + "-01-01T00:00:00Z"))
    assert host.run() == []


def test_reports_pr_review_once(host):
    host.armed()
    host.route("notifications", notification("PullRequest", comment=""))
    host.route(
        "https://api/pr/1/reviews",
        [{"id": 7, "state": "APPROVED", "user": user("bob"), "submitted_at": FUTURE, "html_url": "https://h/r7"}],
    )
    assert host.run() == ["github reply: o/r review approved by bob https://h/r7"]
    host.armed(since="2000-01-01T00:00:00Z")
    assert host.run() == []


def test_failed_notifications_call_keeps_since(host):
    host.armed()
    host.route("notifications", None)
    assert host.run() == []
    assert (host.dir / "since").read_text() == "2000-01-01T00:00:00Z"
