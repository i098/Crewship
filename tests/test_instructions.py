import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "instructions", Path(__file__).parents[1] / "scripts/instructions.py"
)
instructions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(instructions)

BEGIN, END = instructions.BEGIN, instructions.END
CLAUDE, OMP, CODEX = (instructions.CLAUDE, instructions.OMP, instructions.CODEX)


@pytest.fixture
def host(tmp_path):
    home, text = tmp_path / "home", tmp_path / "AGENTS.md"
    home.mkdir()
    text.write_text("generic v1\n")
    return home, text


def block(body):
    return f"{BEGIN}\n{body}{END}\n"


def test_overwrite_backs_up_only_a_user_change_and_omp_imports_claude(host, tmp_path):
    home, text = host
    claude, omp, codex = (home / rel for rel in (CLAUDE, OMP, CODEX))
    claude.parent.mkdir(parents=True)
    claude.write_text("generic v1\n\n@RTK.md\n")  # already what Crewship writes: no backup
    (home / ".claude/RTK.md").write_text("rtk")
    dotfile = tmp_path / "dotfile"
    dotfile.write_text("dotfiles\n")
    codex.parent.mkdir()
    codex.symlink_to(dotfile)  # a user's link: kept as the backup, never written through

    result = instructions.install(home, text, "overwrite")
    [backup] = result["backups"]
    assert result["changed"] and Path(backup).readlink() == dotfile and dotfile.read_text() == "dotfiles\n"
    assert claude.read_text() == "generic v1\n\n@RTK.md\n"
    assert omp.read_text() == "@~/.claude/CLAUDE.md\n"
    assert codex.read_text() == "generic v1\n" and not codex.is_symlink()
    assert instructions.install(home, text, "overwrite") == {**result, "changed": False, "backups": []}

    # A new text replaces an untouched file in place; a hand-edited one is moved aside.
    codex.write_text("mine\n")
    text.write_text("generic v2\n")
    result = instructions.install(home, text, "overwrite")
    [backup] = result["backups"]
    assert Path(backup).parent == codex.parent and Path(backup).read_text() == "mine\n"
    assert codex.read_text() == "generic v2\n"
    assert not instructions.install(home, text, "overwrite")["changed"]


def test_skip_leaves_a_file_that_exists_and_writes_a_missing_one(host):
    home, text = host
    (home / ".codex").mkdir()
    (home / CODEX).write_text("mine\n")
    for _ in range(2):
        instructions.install(home, text, "skip")
        assert (home / CODEX).read_text() == "mine\n"
        assert (home / CLAUDE).read_text() == block("generic v1\n")
        assert (home / OMP).read_text() == block("@~/.claude/CLAUDE.md\n")


def test_append_keeps_the_user_text_and_one_block_replaced_in_place(host):
    home, text = host
    claude = home / CLAUDE
    claude.parent.mkdir(parents=True)
    claude.write_text("mine\n")
    result = instructions.install(home, text)
    assert result["changed"] and result["backups"] == []
    assert claude.read_text() == "mine\n\n" + block("generic v1\n")
    first = claude.read_text()
    assert not instructions.install(home, text)["changed"]

    claude.write_text(first + "after\n")  # the user adds text around the block
    text.write_text("generic v2\n")
    assert instructions.install(home, text)["changed"]
    assert claude.read_text() == "mine\n\n" + block("generic v2\n") + "after\n"
    assert claude.read_text().count(BEGIN) == 1
    assert not instructions.install(home, text)["changed"]


def test_append_turns_a_file_crewship_wrote_whole_into_a_block_without_a_backup(host):
    home, text = host
    instructions.install(home, text, "overwrite")
    result = instructions.install(home, text)
    assert result["changed"] and result["backups"] == []
    assert (home / CODEX).read_text() == block("generic v1\n")
    assert not list(home.rglob("*.bak"))
    assert instructions.install(home, text) == {**result, "changed": False}


def test_append_leaves_a_broken_marker_alone(host):
    home, text = host
    claude = home / CLAUDE
    claude.parent.mkdir(parents=True)
    claude.write_text(f"{BEGIN}\nhalf\n")
    result = instructions.install(home, text)
    assert claude.read_text() == f"{BEGIN}\nhalf\n"
    assert len(result["skipped"]) == 1 and CLAUDE in result["skipped"][0]


def test_auto_updates_only_a_host_that_already_has_managed_files(host):
    home, text = host
    assert instructions.install(home, text, enabled="auto")["installed"] == []
    assert not (home / CLAUDE).exists()
    instructions.install(home, text)
    text.write_text("generic v2\n")
    assert instructions.install(home, text, enabled="auto")["changed"]
    assert (home / CLAUDE).read_text() == block("generic v2\n")
    assert instructions.install(home, text, enabled="no") == {
        "changed": False, "installed": [], "backups": [], "skipped": []
    }


def test_a_failed_target_still_records_the_earlier_writes(host):
    home, text = host
    instructions.install(home, text, "overwrite")
    text.write_text("generic v2\n")
    (home / CODEX).unlink()
    (home / ".codex").rmdir()
    (home / ".codex").write_text("in the way")
    try:
        instructions.install(home, text, "overwrite")
    except OSError:
        pass
    (home / ".codex").unlink()
    text.write_text("generic v3\n")
    assert instructions.install(home, text, "overwrite")["backups"] == []


def test_default_instructions_route_memory_edits_through_backpass():
    text = instructions.TEXT.read_text()
    assert "only through backpass" in text and "`backpass apply`" in text
