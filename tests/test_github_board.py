import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from retired_probe import GROUP_VARS, PROBE

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
    """Answers the REST calls github-board.py makes and keeps a Project board, with no network."""

    def __init__(self, owner_type="User"):
        self.calls, self.owner_type = [], owner_type
        self.options = ["Queued", "In Progress", "In review", "Done"]
        self.items = [{"id": 1, "content_type": "DraftIssue", "content": None}]

    def __call__(self, args):
        self.calls.append(args)
        path = args[2] if args[0] == "-X" else args[0]
        if path.count("/") == 1 and path.startswith("users/"):
            return {"type": self.owner_type}
        if path.endswith("/fields?per_page=100"):
            options = [{"id": f"option-{name}", "name": {"raw": name}} for name in self.options]
            status = {"id": 9, "name": "Status", "data_type": "single_select", "options": options}
            return [[{"id": 8, "name": "Title", "data_type": "title"}], [status]]
        if path.endswith("/items?per_page=100"):
            return [self.items[:1], self.items[1:]]
        if path.endswith("/items"):
            added = dict(arg.split("=", 1) for arg in args[2::2])
            url = "https://api.github.com/repos/{owner}/{repo}/issues/{number}".format(**added)
            item = {"id": 100 + len(self.items), "content_type": "Issue", "content": {"url": url}}
            self.items.append(item)
            return {"id": item["id"]}
        if "/projectsV2/" in path:
            [item] = [item for item in self.items if path.endswith(f"/items/{item['id']}")]
            assert args[3:] == ["-F", "fields[][id]=9", "-f", args[6]]
            item["status"] = args[6].removeprefix("fields[][value]=option-")
            return {}
        if path.endswith("/issues"):
            return {"number": sum(call[0].endswith("/issues") for call in self.calls)}
        return {}

    def board(self):
        """{issue number: Status} for every issue on the Project."""
        return {int(item["content"]["url"].rsplit("/", 1)[1]): item.get("status")
                for item in self.items if item["content_type"] == "Issue"}

    def take(self):
        calls, self.calls = self.calls, []
        return calls


def write_backlog(home, queued, in_flight, done):
    def rows(keys):
        return "".join(f"- [ ] {key} - work {key} (repo: r) (kind: ship)\n  note {key}\n" for key in keys)

    (home / "data/backlog.md").write_text(
        f"## In flight\n{rows(in_flight)}## Queued\n{rows(queued)}## Done\n{rows(done)}"
    )


def project_writes(calls):
    return [call for call in calls
            if "/projectsV2/" in " ".join(call) and ("-X" in call or "-f" in call)]


def saved():
    return json.loads(board.STATE.read_text())["items"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(board, "STATE", tmp_path / "board-state.json")
    home = tmp_path / "firstmate"
    (home / "data").mkdir(parents=True)
    (home / "state").mkdir()
    return home


@pytest.mark.parametrize("owner_type, family", [("User", "users"), ("Organization", "orgs")])
def test_sync_maps_states_batches_comments_and_skips_an_unchanged_run(home, owner_type, family):
    github = FakeGitHub(owner_type)
    project = f"{family}/owner/projectsV2/3"
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
    assert not [call for call in calls if "graphql" in call]
    assert [call for call in calls if call[0] == f"{project}/items"] == [
        [f"{project}/items", "-f", "type=Issue", "-f", "owner=owner", "-f", "repo=board",
         "-F", f"number={n}"]
        for n in (1, 2, 3)
    ]
    assert ["-X", "PATCH", f"{project}/items/101", "-F", "fields[][id]=9",
            "-f", "fields[][value]=option-In Progress"] in calls
    assert github.board() == {1: "In Progress", 2: "In review", 3: "Queued"}
    assert saved() == {
        "a": {"issue": 3, "posted": 0, "status": "Queued"},
        "b": {"issue": 1, "posted": 1, "status": "In progress"},
        "c": {"issue": 2, "posted": 2, "status": "In review"},
    }

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
    assert project_writes(calls) == [["-X", "PATCH", f"{project}/items/103", "-F", "fields[][id]=9",
                                      "-f", "fields[][value]=option-Done"]]
    assert github.board() == {1: "In Progress", 2: "In review", 3: "Done"}
    assert saved()["a"] == {"issue": 3, "posted": 0, "status": "Done"}


def test_an_issue_already_on_the_board_is_not_added_again(home):
    github = FakeGitHub()
    url = "https://api.github.com/repos/Owner/Board/issues/1"
    github.items.append({"id": 50, "content_type": "Issue", "content": {"url": url}})
    write_backlog(home, queued=["a"], in_flight=[], done=[])

    board.sync(home, "owner/board", 3, github)
    assert project_writes(github.take()) == [["-X", "PATCH", "users/owner/projectsV2/3/items/50",
                                              "-F", "fields[][id]=9", "-f", "fields[][value]=option-Queued"]]
    assert github.board() == {1: "Queued"}


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
    assert not [call for call in calls if "PATCH" in call and call[2].startswith("repos/")]

    board.sync(home, repo, project, github)
    assert github.take() == []


def test_a_failed_gh_call_reports_gh_stderr(monkeypatch):
    def failing(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="missing scope: project\n")

    monkeypatch.setattr(board.subprocess, "run", failing)
    with pytest.raises(SystemExit, match="missing scope: project"):
        board.gh(["users/owner/projectsV2/3/fields?per_page=100", "--paginate", "--slurp"])


def test_a_status_option_missing_from_the_project_stops_before_any_status_change(home):
    github = FakeGitHub()
    github.options.remove("In Progress")
    write_backlog(home, queued=[], in_flight=["b"], done=[])

    with pytest.raises(SystemExit, match="In progress"):
        board.sync(home, "owner/board", 3, github)
    assert project_writes(github.take()) == []
    assert github.board() == {}


def _apply(tmp_path, home, github_board):
    playbook = tmp_path / "playbook.yml"
    if not playbook.exists():
        (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
        playbook.write_text(yaml.safe_dump([{
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "vars_files": GROUP_VARS,
            "tasks": [PROBE, {"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/github_board.yml")}],
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
        "crewship_path_checker": str(ROOT / "scripts/check_paths.py"),
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
