import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

SPEC = importlib.util.spec_from_file_location(
    "skills", Path(__file__).parents[1] / "scripts/skills.py"
)
skills = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(skills)
SKILL_ROOTS = skills.KINDS["skills"][2]
RULES = ".omp/agent/rules"


def skill(root, kind, name, body):
    path = root / kind / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(body)
    return path


def rule(root, kind, name, body):
    path = root / kind / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_install_both_sets_private_wins_and_hand_added_skills_stay(tmp_path):
    source, home = tmp_path / "blueprint/skills", tmp_path / "home"
    skill(source, "public", "shared", "public shared")
    skill(source, "public", "only-public", "public only")
    helper = skill(source, "private", "shared", "private shared") / "run.sh"
    helper.write_text("#!/bin/sh\n")
    helper.chmod(0o755)
    skill(source, "private", "only-private", "private only")
    hand = home / ".claude/skills/only-public"
    hand.mkdir(parents=True)
    (hand / "SKILL.md").write_text("operator")

    result = skills.install(home, tmp_path)
    assert result["changed"]
    assert result["skipped"] == [str(hand)]
    for root in SKILL_ROOTS:
        base = home / root
        assert (base / "shared/SKILL.md").read_text() == "private shared"
        assert (base / "shared/run.sh").stat().st_mode & 0o111
        assert (base / "only-private/SKILL.md").read_text() == "private only"
    assert (home / ".omp/agent/skills/only-public/SKILL.md").read_text() == "public only"
    assert (hand / "SKILL.md").read_text() == "operator"

    assert not skills.install(home, tmp_path)["changed"]

    # An installed skill whose source is gone is removed; the hand-added one stays.
    (source / "private/only-private/SKILL.md").unlink()
    (source / "private/only-private").rmdir()
    (home / ".omp/agent/skills/hand-made").mkdir()
    assert skills.install(home, tmp_path)["changed"]
    for root in SKILL_ROOTS:
        assert not (home / root / "only-private").exists()
    assert (home / ".omp/agent/skills/hand-made").is_dir()
    assert (hand / "SKILL.md").read_text() == "operator"


def test_grouped_skills_install_by_name_and_share_one_copy_of_the_group_file(tmp_path):
    source, home = tmp_path / "blueprint/skills", tmp_path / "home"
    group = source / "public/ui"
    for name in ("app", "site"):
        skill(group, ".", name, name)
        (group / name / "shared.md").symlink_to("../shared.md")
    (group / "shared.md").write_text("basics")
    skill(source, "public", "plain", "plain")
    skill(source / "public/plain", ".", "inner", "inner")  # a folder inside a skill is not a group

    assert skills.install(home, tmp_path)["installed"]["skills"] == ["app", "plain", "site", "ui"]
    for root in SKILL_ROOTS:
        base = home / root
        for name in ("app", "site"):
            assert (base / name / "SKILL.md").read_text() == name
            assert (base / name / "shared.md").resolve() == (base / "ui/shared.md").resolve()
        assert not (base / "ui/shared.md").is_symlink()
        assert not (base / "inner").exists()
    assert not skills.install(home, tmp_path)["changed"]

    # the group's file changes once and both skills read the change
    (group / "shared.md").write_text("newer")
    assert skills.install(home, tmp_path)["changed"]
    assert (home / SKILL_ROOTS[0] / "site/shared.md").read_text() == "newer"


@pytest.mark.parametrize("clash", ["flat", "group"])
def test_a_grouped_skill_that_reuses_a_name_stops_the_install(tmp_path, clash):
    source, home = tmp_path / "blueprint/skills", tmp_path / "home"
    skill(source / "public/ui", ".", "app", "grouped")
    if clash == "flat":
        skill(source, "public", "app", "flat")
    else:
        skill(source / "public/web", ".", "app", "other group")
    with pytest.raises(ValueError, match="app"):
        skills.install(home, tmp_path)
    assert not home.exists()


def test_install_rules_private_wins_and_hand_added_rules_stay(tmp_path):
    source, home = tmp_path / "blueprint/rules", tmp_path / "home"
    rule(source, "public", "shared", "public shared")
    rule(source, "public", "only-public", "public only")
    rule(source, "public", "README", "not a rule")
    rule(source, "private", "shared", "private shared")
    gone = rule(source, "private", "only-private", "private only")
    rules = home / RULES
    rules.mkdir(parents=True)
    (rules / "hand-made.md").write_text("operator")

    result = skills.install(home, tmp_path)
    assert result["changed"]
    assert result["installed"]["rules"] == ["only-private.md", "only-public.md", "shared.md"]
    assert result["skipped"] == []
    assert (rules / "shared.md").read_text() == "private shared"
    assert (rules / "only-public.md").read_text() == "public only"
    assert (rules / "only-private.md").read_text() == "private only"
    assert not (rules / "README.md").exists()
    for root in SKILL_ROOTS:
        assert not (home / root / "shared.md").exists()

    assert not skills.install(home, tmp_path)["changed"]

    # An installed rule whose source is gone is removed; the hand-added one stays.
    gone.unlink()
    assert skills.install(home, tmp_path)["changed"]
    assert not (rules / "only-private.md").exists()
    assert (rules / "hand-made.md").read_text() == "operator"
    assert not skills.install(home, tmp_path)["changed"]



@pytest.fixture
def browser_rules_repo(tmp_path):
    repo = tmp_path / "repo"
    script = repo / "scripts/skills.py"
    script.parent.mkdir(parents=True)
    script.write_bytes((skills.REPO / "scripts/skills.py").read_bytes())
    for name in ("drive-the-browser-yourself", "fleet-browser-default-tier"):
        rule(repo / "blueprint/rules", "public", name, f"public {name}")
        rule(repo / "blueprint/rules", "private", name, f"private {name}")
    rule(repo / "blueprint/rules", "public", "always-on-skills", "general rule")
    return repo


def apply_rules(repo, home, ladder, profiles=None):
    home.mkdir(parents=True, exist_ok=True)
    tasks = yaml.safe_load((skills.REPO / "blueprint/ansible/tasks/agents.yml").read_text())
    task = next(t for t in tasks if t.get("register") == "crewship_skills_run")
    template = NativeEnvironment()
    template.filters["bool"] = bool
    argv = template.from_string(task["ansible.builtin.command"]["argv"]).render(
        crewship_repo=str(repo),
        crewship_cfg={"home": str(home), "profiles": {"public_skills": True} if profiles is None else profiles},
        crewship_fleet_browsers_enabled=ladder,
    )
    argv[0] = sys.executable
    argv.append("--no-upstream")  # the default fetches from GitHub
    result = subprocess.run(argv, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


@pytest.fixture
def public_repo(tmp_path):
    repo = tmp_path / "repo"
    skill(repo / "blueprint/skills", "public", "shared", "public shared")
    skill(repo / "blueprint/skills", "public", "only-public", "public only")
    skill(repo / "blueprint/skills", "private", "shared", "private shared")
    rule(repo / "blueprint/rules", "public", "style", "public rule")
    return repo


def installed(home):
    names = {r: sorted(p.name for p in (home / r).glob("*")) for r in (*SKILL_ROOTS, RULES)}
    return {r: n for r, n in names.items() if n}


def test_public_off_installs_private_only_and_removes_nothing(public_repo, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = skills.install(home, public_repo, public="no")
    assert result["installed"] == {"skills": ["shared"], "rules": []}
    assert installed(home) == {r: ["shared"] for r in SKILL_ROOTS}
    skills.install(home, public_repo)
    assert "only-public" in installed(home)[SKILL_ROOTS[0]]
    # turning it off later stops updates but deletes nothing, even a public rule
    (public_repo / "blueprint/skills/public/only-public/SKILL.md").write_text("newer")
    result = skills.install(home, public_repo, public="no")
    assert not result["changed"]
    assert installed(home)[RULES] == ["style.md"]
    assert (home / SKILL_ROOTS[0] / "only-public/SKILL.md").read_text() == "public only"


def test_public_auto_keeps_an_existing_bundle_and_starts_nothing_on_a_new_host(public_repo, tmp_path):
    new, old = tmp_path / "new", tmp_path / "old"
    new.mkdir()
    old.mkdir()
    skills.install(new, public_repo, public="auto")
    assert installed(new) == {r: ["shared"] for r in SKILL_ROOTS}
    skills.install(old, public_repo)
    (public_repo / "blueprint/skills/public/only-public/SKILL.md").write_text("newer")
    assert skills.install(old, public_repo, public="auto")["changed"]
    assert (old / SKILL_ROOTS[0] / "only-public/SKILL.md").read_text() == "newer"


@pytest.mark.parametrize(
    "profiles, public",
    [({}, False), ({"public_skills": False}, False), ({"public_skills": True}, True)],
)
def test_the_playbook_passes_the_public_choice(browser_rules_repo, tmp_path, profiles, public):
    home = tmp_path / "home"
    result = apply_rules(browser_rules_repo, home, True, profiles)
    assert ("always-on-skills.md" in result["installed"]["rules"]) is public


def test_the_playbook_keeps_public_skills_a_host_already_has(browser_rules_repo, tmp_path):
    home = tmp_path / "home"
    apply_rules(browser_rules_repo, home, True)
    assert not apply_rules(browser_rules_repo, home, True, {})["changed"]
    assert (home / RULES / "always-on-skills.md").exists()


def test_browser_ladder_on_installs_both_rules(browser_rules_repo, tmp_path):
    home = tmp_path / "home"
    result = apply_rules(browser_rules_repo, home, True)
    assert result["installed"]["rules"] == [
        "always-on-skills.md", "drive-the-browser-yourself.md", "fleet-browser-default-tier.md"
    ]
    for name in ("drive-the-browser-yourself", "fleet-browser-default-tier"):
        assert (home / RULES / f"{name}.md").read_text() == f"private {name}"
    assert not apply_rules(browser_rules_repo, home, True)["changed"]


def test_browser_ladder_off_removes_only_owned_rules(browser_rules_repo, tmp_path):
    home = tmp_path / "home"
    result = apply_rules(browser_rules_repo, home, False)
    assert result["installed"]["rules"] == ["always-on-skills.md"]
    names = ("drive-the-browser-yourself.md", "fleet-browser-default-tier.md")
    assert all(not (home / RULES / name).exists() for name in names)
    apply_rules(browser_rules_repo, home, True)
    result = apply_rules(browser_rules_repo, home, False)
    assert result["changed"]
    assert all(not (home / RULES / name).exists() for name in names)
    owned = json.loads((home / skills.MANIFEST).read_text())
    assert owned[RULES] == ["always-on-skills.md"]
    assert (home / RULES / "always-on-skills.md").read_text() == "general rule"
    assert not apply_rules(browser_rules_repo, home, False)["changed"]

    hand_home = tmp_path / "hand-home"
    for name in names:
        rule(hand_home / ".omp/agent", "rules", Path(name).stem, "operator")
    apply_rules(browser_rules_repo, hand_home, True)
    apply_rules(browser_rules_repo, hand_home, False)
    assert all((hand_home / RULES / name).read_text() == "operator" for name in names)


def test_failed_copy_still_records_what_was_installed(tmp_path, monkeypatch):
    source, home = tmp_path / "blueprint/skills", tmp_path / "home"
    skill(source, "public", "a", "a")
    skill(source, "public", "b", "b")
    real = skills.shutil.copytree

    def flaky(src, dst, **kwargs):
        if Path(src).name == "b":
            raise OSError("disk full")
        return real(src, dst, **kwargs)

    monkeypatch.setattr(skills.shutil, "copytree", flaky)
    try:
        skills.install(home, tmp_path)
    except OSError:
        pass
    monkeypatch.setattr(skills.shutil, "copytree", real)

    result = skills.install(home, tmp_path)
    assert result["skipped"] == []
    for root in SKILL_ROOTS:
        assert (home / root / "b/SKILL.md").read_text() == "b"


def git(*argv):
    subprocess.run(["git", *argv], check=True, capture_output=True)


def test_no_private_source_fetches_nothing_and_leaves_private_alone(tmp_path, monkeypatch):
    source, home = tmp_path / "blueprint/skills", tmp_path / "home"
    skill(source, "private", "mine", "mine")
    monkeypatch.setattr(skills.subprocess, "run", lambda *a, **k: pytest.fail("fetched"))
    skills.install(home, tmp_path)
    assert [p.name for p in (source / "private").iterdir()] == ["mine"]
    assert not (home / skills.CACHE).exists()


def test_removing_private_source_removes_only_what_it_filled(tmp_path):
    source, home, local = tmp_path / "blueprint/skills", tmp_path / "home", tmp_path / "local"
    skill(local, ".", "filled", "filled")
    rule(local, "rules", "filled", "filled")
    skill(source, "private", "by-hand", "by hand")
    skills.install(home, tmp_path, str(local))
    assert (home / RULES / "filled.md").read_text() == "filled"
    result = skills.install(home, tmp_path)
    assert result["changed"]
    assert result["installed"] == {"skills": ["by-hand"], "rules": []}
    assert not (source / "private/filled").exists()
    assert not (tmp_path / "blueprint/rules/private/filled.md").exists()
    assert not (home / RULES / "filled.md").exists()
    assert (source / "private/by-hand/SKILL.md").read_text() == "by hand"
    for root in SKILL_ROOTS:
        assert not (home / root / "filled").exists()
        assert (home / root / "by-hand/SKILL.md").read_text() == "by hand"
    assert not skills.install(home, tmp_path)["changed"]


def test_private_git_source_fills_private_and_installs_idempotently(tmp_path):
    source, home, remote = tmp_path / "blueprint/skills", tmp_path / "home", tmp_path / "remote"
    skill(source, "public", "shared", "public shared")
    skill(source, "private", "by-hand", "by hand")
    skill(remote, ".", "shared", "remote shared")
    skill(remote, ".", "gone-later", "remote gone")
    skill(remote, ".", "by-hand", "remote by hand")
    rule(tmp_path / "blueprint/rules", "public", "shared", "public rule")
    rule(remote, "rules", "shared", "remote rule")
    git("init", "-q", "-b", "skills", str(remote))
    git("-C", str(remote), "add", ".")
    git("-C", str(remote), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    url = remote.as_uri()

    result = skills.install(home, tmp_path, url, "skills")
    assert result["changed"]
    assert result["skipped"] == [str(source / "private/by-hand")]
    assert (source / "private/by-hand/SKILL.md").read_text() == "by hand"
    for root in SKILL_ROOTS:
        assert (home / root / "shared/SKILL.md").read_text() == "remote shared"
        assert (home / root / "gone-later/SKILL.md").read_text() == "remote gone"
        assert (home / root / "by-hand/SKILL.md").read_text() == "by hand"
    assert (home / RULES / "shared.md").read_text() == "remote rule"

    assert not skills.install(home, tmp_path, url, "skills")["changed"]

    # A skill that leaves the source leaves blueprint/skills/private and every root.
    git("-C", str(remote), "rm", "-rq", "gone-later")
    git("-C", str(remote), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "y")
    assert skills.install(home, tmp_path, url, "skills")["changed"]
    assert not (source / "private/gone-later").exists()
    for root in SKILL_ROOTS:
        assert not (home / root / "gone-later").exists()
        assert (home / root / "shared/SKILL.md").read_text() == "remote shared"


def test_upstream_skill_installs_at_the_newest_commit_and_records_its_sha(tmp_path):
    home, remote = tmp_path / "home", tmp_path / "remote"
    skill(remote, "skills", "vision", "v1")
    git("init", "-q", "-b", "main", str(remote))

    def commit():
        git("-C", str(remote), "add", ".")
        git("-C", str(remote), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
        return subprocess.run(
            ["git", "-C", str(remote), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()

    sha = commit()
    upstream = {"vision": (remote.as_uri(), "skills/vision")}
    result = skills.install(home, tmp_path, upstream=upstream, public="no")
    assert result["changed"] and result["upstream"] == {"vision": sha}
    for root in SKILL_ROOTS:
        assert (home / root / "vision/SKILL.md").read_text() == "v1"
        assert (home / root / "vision/.crewship-source").read_text() == f"{remote.as_uri()}@{sha}\n"

    assert not skills.install(home, tmp_path, upstream=upstream, public="no")["changed"]

    (remote / "skills/vision/SKILL.md").write_text("v2")
    sha = commit()
    result = skills.install(home, tmp_path, upstream=upstream, public="no")
    assert result["changed"] and result["upstream"] == {"vision": sha}
    assert (home / SKILL_ROOTS[0] / "vision/SKILL.md").read_text() == "v2"


def test_private_local_directory_source_fills_private(tmp_path):
    source, home, local = tmp_path / "blueprint/skills", tmp_path / "home", tmp_path / "local"
    skill(local, ".", "solo", "local solo")
    result = skills.install(home, tmp_path, str(local))
    assert result["installed"]["skills"] == ["solo"]
    assert (source / "private/solo/SKILL.md").read_text() == "local solo"
    for root in SKILL_ROOTS:
        assert (home / root / "solo/SKILL.md").read_text() == "local solo"
    assert not skills.install(home, tmp_path, str(local))["changed"]
    # A missing local source fails and leaves every filled skill in place.
    with pytest.raises(FileNotFoundError):
        skills.install(home, tmp_path, str(tmp_path / "unmounted"))
    assert (source / "private/solo/SKILL.md").read_text() == "local solo"
    for root in SKILL_ROOTS:
        assert (home / root / "solo/SKILL.md").read_text() == "local solo"


def test_private_source_group_installs_by_name_and_reinstalls_unchanged(tmp_path):
    home, local = tmp_path / "home", tmp_path / "local"
    skill(local / "g", ".", "a", "grouped a")
    assert skills.install(home, tmp_path, str(local))["installed"]["skills"] == ["a", "g"]
    for root in SKILL_ROOTS:
        assert (home / root / "a/SKILL.md").read_text() == "grouped a"
    assert not skills.install(home, tmp_path, str(local))["changed"]


def test_a_private_group_replaces_the_whole_public_group(tmp_path):
    source, home = tmp_path / "blueprint/skills", tmp_path / "home"
    for name in ("app", "site"):
        skill(source / "public/ui", ".", name, f"public {name}")
    skill(source / "private/ui", ".", "app", "private app")
    assert skills.install(home, tmp_path)["installed"]["skills"] == ["app", "ui"]
    for root in SKILL_ROOTS:
        assert (home / root / "app/SKILL.md").read_text() == "private app"
        assert not (home / root / "site").is_symlink()


# Shapes of private detail, never the real values: a home directory, an email,
# a tailnet host, a non-loopback IPv4, a GitHub owner URL, a secrets file, and
# the word for the person who owns a fleet.
PRIVATE = re.compile(
    r"(/home/|/Users/|/root/|[\w.+-]+@[\w-]+\.[a-z]{2,}|\.ts\.net\b"
    r"|\b(?!127\.)\d{1,3}(\.\d{1,3}){3}\b|github\.com/[\w-]+|\w+\.env\b|\bcaptain\b)",
    re.IGNORECASE,
)


# The vendored skills (MIT) link their authors' public repositories or carry their license text.
# Those are credits, not private details; each exemption covers only its own folder.
VENDORED_OWNER = {
    "blueprint/skills/public/code-clarity/": "github.com/Lakr233",
    "blueprint/skills/public/pr-preview/": "sindresorhus@gmail.com",
}


def test_public_skills_and_rules_are_named_and_hold_no_private_details():
    shapes = ["/home/x", "a@b.io", "h.ts.net", "10.1.2.3", "github.com/x", "k.env", "Captain"]
    assert all(PRIVATE.search(s) for s in shapes)
    assert not PRIVATE.search("http://127.0.0.1:9222")
    repo = Path(__file__).parents[1]
    files = [
        p for d in ("blueprint/skills/public", "blueprint/rules/public") for p in (repo / d).rglob("*") if p.is_file()
    ]
    assert files
    for path in files:
        rel = path.relative_to(repo).as_posix()
        text = path.read_text()
        allowed = next((v for k, v in VENDORED_OWNER.items() if rel.startswith(k)), None)
        hits = [m.group(0) for m in PRIVATE.finditer(text) if m.group(0) != allowed]
        assert not hits, f"{rel}: {hits[0]!r}"
        if path.name == "SKILL.md":
            meta = yaml.safe_load(text.split("---")[1])
            assert meta["name"] == path.parent.name, path
