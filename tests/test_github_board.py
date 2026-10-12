import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


board = load("github_board", "blueprint/maintenance/github-board.py")
ship = load("ship_config_github_board", "scripts/ship.py")

BOARD = {"repo": "owner/board", "project": 3}


@pytest.fixture
def configuration():
    document = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    document["crewship"]["github_board"] = dict(BOARD)
    return document


def test_the_board_block_is_accepted(configuration):
    assert ship.validate_config(configuration) is configuration


@pytest.mark.parametrize(
    "change",
    [
        {"repo": "no-owner"},
        {"repo": "owner/board; rm -rf"},
        {"project": 0},
        {"project": "3"},
        {"token": "secret"},
    ],
)
def test_a_bad_board_block_is_rejected(configuration, change):
    configuration["crewship"]["github_board"].update(change)
    with pytest.raises(ValueError, match="github_board"):
        ship.validate_config(configuration)


def test_the_board_needs_the_firstmate_profile(configuration):
    configuration["crewship"]["profiles"]["firstmate"] = False
    with pytest.raises(ValueError, match="github_board requires the firstmate profile"):
        ship.validate_config(configuration)


class FakeGitHub:
    """Answers the calls github-board.py makes, with no network."""

    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "graphql":
            query = args[2]
            if "repositoryOwner" in query:
                names = ("Queued", "In Progress", "In review", "Done")
                options = [{"id": f"option-{name}", "name": name} for name in names]
                return {"data": {"repositoryOwner": {"projectV2": {
                    "id": "project", "field": {"id": "status", "options": options}}}}}
            count = query.count("addProjectV2ItemById")
            return {"data": {f"a{i}": {"item": {"id": f"item-{i}"}} for i in range(count)}}
        if args[0].endswith("/issues"):
            number = sum(call[0].endswith("/issues") for call in self.calls)
            return {"number": number, "node_id": f"issue-{number}"}
        return {}

    def take(self):
        calls, self.calls = self.calls, []
        return calls


def write_backlog(home, queued, in_flight, done):
    def rows(keys):
        return "".join(f"- [ ] {key} - work {key} (repo: r) (kind: ship)\n  note {key}\n" for key in keys)

    (home / "data/backlog.md").write_text(
        f"## In flight\n{rows(in_flight)}## Queued\n{rows(queued)}## Done\n{rows(done)}"
    )


def status_updates(calls):
    return [call[2] for call in calls if call[0] == "graphql" and "updateProjectV2" in call[2]]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(board, "STATE", tmp_path / "board-state.json")
    home = tmp_path / "firstmate"
    (home / "data").mkdir(parents=True)
    (home / "state").mkdir()
    return home


def test_sync_maps_states_batches_comments_and_skips_an_unchanged_run(home):
    github = FakeGitHub()
    write_backlog(home, queued=["a"], in_flight=["b", "c"], done=["d"])
    (home / "state/b.status").write_text("working [at=1]: started\n")
    (home / "state/c.status").write_text("working [at=1]: started\ndone [at=2]: PR ready\n")

    board.sync(home, "owner/board", 3, github)
    calls = github.take()
    created = [call for call in calls if call[0] == "repos/owner/board/issues"]
    # One issue per open item, in backlog order; d was done before the board saw it.
    assert [call[2] for call in created] == ["title=b: work b", "title=c: work c", "title=a: work a"]
    assert "    note a\n" in created[2][4]
    comments = {call[0]: call[2] for call in calls if call[0].endswith("/comments")}
    assert comments == {
        "repos/owner/board/issues/1/comments": "body=    working [at=1]: started\n",
        "repos/owner/board/issues/2/comments":
            "body=    working [at=1]: started\n    done [at=2]: PR ready\n",
    }
    # Every Status change goes in one batched mutation.
    [update] = status_updates(calls)
    assert [update.count(f'"option-{name}"') for name in ("Queued", "In Progress", "In review")] == [1, 1, 1]
    assert sum(call[0] == "graphql" for call in calls) == 3

    board.sync(home, "owner/board", 3, github)
    assert github.take() == []

    write_backlog(home, queued=[], in_flight=["b", "c"], done=["a", "d"])
    with (home / "state/b.status").open("a") as status:
        status.write("paused [at=3]: waiting\nworking [at=4]: resumed\n")
    board.sync(home, "owner/board", 3, github)
    calls = github.take()
    assert [call for call in calls if call[0].endswith("/comments")] == [[
        "repos/owner/board/issues/1/comments",
        "-f", "body=    paused [at=3]: waiting\n    working [at=4]: resumed\n",
    ]]
    assert ["-X", "PATCH", "repos/owner/board/issues/3", "-f", "state=closed"] in calls
    [update] = status_updates(calls)
    assert update.count("updateProjectV2ItemFieldValue") == 1 and '"option-Done"' in update


def test_a_missing_backlog_makes_no_calls(home):
    github = FakeGitHub()
    board.sync(home, "owner/board", 3, github)
    assert github.calls == []


@pytest.mark.parametrize("repo, project", [("owner/other", 3), ("owner/board", 4)])
def test_a_changed_repo_or_project_starts_fresh_instead_of_reusing_issue_numbers(home, repo, project):
    github = FakeGitHub()
    write_backlog(home, queued=["a"], in_flight=[], done=[])
    board.sync(home, "owner/board", 3, github)
    github.take()

    board.sync(home, repo, project, github)
    calls = github.take()
    assert [call[0] for call in calls if call[0].endswith("/issues")] == [f"repos/{repo}/issues"]
    assert not [call for call in calls if "PATCH" in call]

    board.sync(home, repo, project, github)
    assert github.take() == []


def test_a_failed_gh_call_reports_gh_stderr(monkeypatch):
    def failing(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="missing scope: project\n")

    monkeypatch.setattr(board.subprocess, "run", failing)
    with pytest.raises(SystemExit, match="missing scope: project"):
        board.gh(["graphql", "-f", "query=secret query text"])


def test_a_status_option_missing_from_the_project_stops_before_any_status_change(home):
    github = FakeGitHub()
    write_backlog(home, queued=[], in_flight=["b"], done=[])

    def without_in_progress(args):
        answer = github(args)
        if args[0] == "graphql" and "repositoryOwner" in args[2]:
            field = answer["data"]["repositoryOwner"]["projectV2"]["field"]
            field["options"] = [o for o in field["options"] if o["name"] != "In Progress"]
        return answer

    with pytest.raises(SystemExit, match="In progress"):
        board.sync(home, "owner/board", 3, without_in_progress)
    assert status_updates(github.take()) == []


def _apply(tmp_path, home, github_board):
    playbook = tmp_path / "playbook.yml"
    if not playbook.exists():
        (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
        playbook.write_text(yaml.safe_dump([{
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/github_board.yml")}],
            "handlers": [{"name": "Reload", "ansible.builtin.debug": {"msg": "reload"},
                          "listen": "reload user systemd"}],
        }]))
    crewship_cfg = {"user": "coder", "home": str(home)}
    if github_board:
        crewship_cfg["github_board"] = github_board
    variables = {
        "crewship_cfg": crewship_cfg,
        "crewship_local_bin": str(home / ".local/bin"),
        "crewship_user_units": str(home / ".config/systemd/user"),
        "crewship_firstmate_dir": str(home / "Dev/firstmate"),
        "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
        "crewship_manage_services": False,
        "crewship_user_systemd_env": {},
    }
    result = subprocess.run(
        [Path(sys.executable).parent / "ansible-playbook", "-i", "localhost,", str(playbook),
         "--extra-vars", json.dumps(variables)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout
    return result.stdout


def test_apply_is_idempotent_and_removing_the_key_removes_the_timer(tmp_path):
    home = tmp_path / "home"
    units = home / ".config/systemd/user"
    files = [
        units / "github-board.service",
        units / "github-board.timer",
        units / "timers.target.wants/github-board.timer",
        home / ".local/bin/github-board.py",
    ]

    _apply(tmp_path, home, BOARD)
    assert all(path.exists() for path in files)
    service = (units / "github-board.service").read_text()
    assert f'github-board.py "{home}/Dev/firstmate" owner/board 3\n' in service
    assert "changed=0" in _apply(tmp_path, home, BOARD)

    _apply(tmp_path, home, None)
    assert not any(path.exists() or path.is_symlink() for path in files)
    assert "changed=0" in _apply(tmp_path, home, None)
