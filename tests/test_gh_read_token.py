import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
MAINTENANCE = ROOT / "blueprint/maintenance"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


tok = load("gh_read_token", "blueprint/maintenance/gh-read-token")
guard = load("gh_guard", "blueprint/maintenance/gh")
cf = load("cf_runner_app", "blueprint/maintenance/cf-runner.py")
pool = load("ci_pool_app", "blueprint/maintenance/ci-pool.py")


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Apps for the repositories o/my-repo and o/other, with a stubbed signer and stubbed GitHub; `calls` records token requests."""
    for repo, number in (("MY_REPO", 1), ("OTHER", 2)):
        monkeypatch.setenv(f"GITHUB_APP_{repo}_ID", str(number))
        monkeypatch.setenv(f"GITHUB_APP_{repo}_INSTALLATION_ID", str(number * 100))
        monkeypatch.setenv(f"GITHUB_APP_{repo}_KEY_PATH", f"/{repo}.pem")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("CREWSHIP_SUPER_ENV", str(tmp_path / "missing.env"))
    calls = []
    monkeypatch.setattr(tok, "sign", lambda message, key: b"sig")

    def request(jwt, installation):
        calls.append((jwt, installation))
        return {"token": f"ghs_{len(calls)}", "expires_at": "2026-01-01T01:00:00Z"}

    monkeypatch.setattr(tok, "request_token", request)
    return calls


EXPIRY = 1767229200  # 2026-01-01T01:00:00Z


def test_token_is_signed_for_the_repository_app_and_refreshed_five_minutes_before_expiry(app):
    assert tok.token("o/my-repo", now=EXPIRY - 3600) == "ghs_1"
    claims = json.loads(tok.base64.urlsafe_b64decode(app[0][0].split(".")[1] + "=="))
    assert claims == {"iat": EXPIRY - 3660, "exp": EXPIRY - 3060, "iss": "1"}
    assert app[0][1] == "100"
    assert tok.token("o/my-repo", now=EXPIRY - 301) == "ghs_1"
    assert tok.token("o/my-repo", now=EXPIRY - 300) == "ghs_2"
    assert len(app) == 2


def test_each_repository_has_its_own_app_and_cache(app):
    assert tok.token("o/my-repo", now=EXPIRY - 3600) == "ghs_1"
    assert tok.token("other", now=EXPIRY - 3600) == "ghs_2"
    assert [installation for _, installation in app] == ["100", "200"]
    assert tok.token("o/my-repo", now=EXPIRY - 3600) == "ghs_1"
    assert stat.S_IMODE(tok.cache_path("o/my-repo").stat().st_mode) == 0o600


def test_a_repository_without_an_app_has_no_token_and_exits_3(app, monkeypatch, tmp_path, capsys):
    assert tok.token("o/unknown") is None
    (tmp_path / "super.env").write_text("GITHUB_APP_FILE_ONLY_ID=1\nGITHUB_APP_FILE_ONLY_INSTALLATION_ID='2'\nGITHUB_APP_FILE_ONLY_KEY_PATH=/k\nOTHER=x\n")
    monkeypatch.setenv("CREWSHIP_SUPER_ENV", str(tmp_path / "super.env"))
    assert tok.settings("o/file-only") == {"id": "1", "installation": "2", "key": "/k"}
    monkeypatch.setattr(sys, "argv", ["gh-read-token", "o/unknown"])
    assert tok.main() == 3


def test_a_refused_token_exits_1_without_a_token_on_stdout(app, monkeypatch, capsys):
    def refuse(jwt, installation):
        raise OSError("HTTP Error 401")

    monkeypatch.setattr(tok, "request_token", refuse)
    monkeypatch.setattr(sys, "argv", ["gh-read-token", "o/my-repo"])
    assert tok.main() == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "argv, repo",
    [
        (["gh", "api", "repos/o/my-repo/pulls?state=open"], "o/my-repo"),
        (["gh", "api", "https://api.github.com/repos/o/other/actions/runs"], "o/other"),
        (["gh", "api", "-X", "GET", "repos/{owner}/{repo}/pulls"], "from the directory"),
    ],
)
def test_command_repository_comes_from_the_endpoint_or_the_directory(monkeypatch, argv, repo):
    monkeypatch.setattr(tok, "origin_repo", lambda: "from the directory")
    assert tok.command_repo(argv) == repo


READ = [sys.executable, "-c", "import os,sys; t=os.environ.get('GH_TOKEN'); print(t); sys.exit(0 if t != 'ghs_1' else 1)", "repos/o/my-repo/pulls"]


def test_run_uses_the_app_token_and_replays_the_output(app, capfd, monkeypatch):
    monkeypatch.setattr(tok, "request_token", lambda jwt, installation: {"token": "ok", "expires_at": "2026-01-01T01:00:00Z"})
    assert tok.run(READ) == 0
    assert capfd.readouterr().out == "ok\n"


def test_run_repeats_a_failed_read_as_the_user(app, capfd, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "user")
    # The app token ghs_1 makes the command fail; the user's environment answers.
    assert tok.run(READ) == 0
    assert capfd.readouterr().out == "user\n"


def test_run_for_a_repository_without_an_app_runs_the_command_once_unchanged(app, monkeypatch, capfd):
    monkeypatch.setenv("GH_TOKEN", "user")
    assert tok.run([*READ[:-1], "repos/o/unknown/pulls"]) == 0
    assert capfd.readouterr().out == "user\n"
    assert app == []


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["api", "repos/o/r/pulls"], True),
        (["api", "-X", "GET", "/repos/o/r/pulls?state=open"], True),
        (["api", "https://api.github.com/repos/o/r/actions/runs"], True),
        (["api", "--method", "POST", "repos/o/r/issues"], False),
        (["api", "repos/o/r/issues", "-f", "title=x"], False),
        (["api", "-X", "DELETE", "repos/o/r/actions/runners/1"], False),
        (["api", "user"], False),
        (["api", "notifications"], False),
        (["api", "graphql", "-f", "query=x"], False),
        (["pr", "list"], False),
    ],
)
def test_wrapper_sends_only_repository_reads_through_the_app(argv, expected):
    assert guard.app_read(argv, "gh") is expected
    assert guard.app_read(argv, "gh-axi") is False


def test_runner_dispatch_reads_with_the_app_and_writes_as_the_user(monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return type("Done", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    monkeypatch.setattr(cf.subprocess, "run", fake_run)
    cf.gh("repos/o/a/actions/runs")
    cf.gh("--method", "DELETE", "repos/o/a/actions/runners/3")
    cf.gh("--method", "POST", "repos/o/a/actions/runners/generate-jitconfig", payload={"name": "x"})
    helper = str(MAINTENANCE / "gh-read-token")
    assert seen[0][:4] == [helper, "run", "gh", "api"]
    assert seen[1][:2] == ["gh", "api"] and seen[2][:2] == ["gh", "api"]


def test_runner_watch_reads_the_runner_list_with_the_app(monkeypatch):
    seen = []
    monkeypatch.setattr(pool, "command_json", lambda argv: seen.append(argv) or {"runners": []})
    pool.github_runners("o/a")
    assert seen == [[str(MAINTENANCE / "gh-read-token"), "run", "gh", "api", "repos/o/a/actions/runners?per_page=100"]]
    assert os.access(MAINTENANCE / "gh-read-token", os.X_OK)
