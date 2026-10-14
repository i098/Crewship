"""blueprint/fleet/doctor/worktree-prune.sh against real git repositories in a temporary pool."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "blueprint/fleet/doctor/worktree-prune.sh"
DAY = 86400
NEEDS_FDU = pytest.mark.skipif(shutil.which("fdu") is None, reason="fdu is not installed")


def git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def put(path: Path, text="x", age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if age_days:
        age(path, age_days)


def age(path: Path, days: int):
    """Backdate a file, or a whole directory tree: stale means nothing inside changed either."""
    stamp = time.time() - days * DAY
    for base, dirs, files in os.walk(path, topdown=False):
        for name in [*files, *dirs, ""]:
            target = os.path.join(base, name)
            if not os.path.islink(target):
                os.utime(target, (stamp, stamp))


@pytest.fixture
def pool(tmp_path):
    """tmp/pools/proj-1/3/repo: a git worktree directory in the Treehouse layout."""
    repo = tmp_path / "pools/proj-1/3/repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    put(repo / ".gitignore", "node_modules/\n.venv/\ndist/\nbuild/\n.env\nsecrets/\n")
    put(repo / "tracked.txt", "keep")
    put(repo / "src/tracked.py", "keep")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo


def run(tmp_path, *args, scan="find", **env):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fdu = bin_dir / "fdu"
    fdu.unlink(missing_ok=True)
    if scan == "fdu":
        fdu.symlink_to(shutil.which("fdu"))
    elif scan == "lying-fdu":  # reports a size, and would name every file as a candidate
        fdu.write_text(
            '#!/bin/sh\necho "$*" >> "$0.log"\n'
            'echo \'{"reports": [{"summary": {"bytes": 4242, "ignored": {"bytes": 1}}}]}\'\n'
            "echo tracked.txt\n"
        )
        fdu.chmod(0o755)
    elif scan == "broken-fdu":
        fdu.write_text("#!/bin/sh\nexit 1\n")
        fdu.chmod(0o755)
    return subprocess.run(
        [str(SCRIPT), *args],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path / "home"),
            "WORKTREE_PRUNE_POOLS": str(tmp_path / "pools"),
            **env,
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )


# Discovery is always find; fdu, when on PATH, only reports sizes. Nothing may depend on it.
SCANS = ["find", "broken-fdu", "lying-fdu", pytest.param("fdu", marks=NEEDS_FDU)]


@pytest.mark.parametrize("scan", SCANS)
def test_only_the_stale_ignored_build_directory_goes(tmp_path, pool, scan):
    put(pool / "node_modules/pkg/index.js", age_days=30)
    age(pool / "node_modules", 30)
    put(pool / "untracked.txt", "mine", age_days=30)  # not ignored: unlanded work
    put(pool / ".env", "TOKEN=1", age_days=30)  # ignored but not build output
    put(pool / "secrets/key", "k", age_days=30)  # ignored but not on the name list
    put(pool / "dist/bundle.js", age_days=1)  # ignored build output, still fresh
    put(pool / ".venv/lib/a.py", age_days=30)
    put(pool / ".venv/lib/touched-yesterday.py", age_days=1)  # one fresh file keeps the tree

    out = run(tmp_path, scan=scan).stdout

    assert not (pool / "node_modules").exists()
    assert f"removed {pool}/node_modules" in out
    for kept in (
        "tracked.txt",
        "src/tracked.py",
        "untracked.txt",
        ".env",
        "secrets/key",
        "dist/bundle.js",
        ".venv/lib/a.py",
        ".gitignore",
    ):
        assert (pool / kept).is_file(), kept
    assert (
        subprocess.run(
            ["git", "-C", str(pool), "status", "--porcelain"], capture_output=True, text=True
        ).stdout.strip()
        == "?? untracked.txt"
    )


@pytest.mark.parametrize("scan", SCANS)
def test_dry_run_lists_the_directory_and_removes_nothing(tmp_path, pool, scan):
    put(pool / "node_modules/pkg/index.js", age_days=30)
    age(pool / "node_modules", 30)

    out = run(tmp_path, "--dry-run", scan=scan).stdout

    assert f"would remove {pool}/node_modules" in out
    assert (pool / "node_modules/pkg/index.js").is_file()


@pytest.mark.parametrize("scan", SCANS)
def test_a_directory_with_tracked_or_nested_repository_content_stays(tmp_path, pool, scan):
    put(pool / "build/forced.txt", "tracked despite the ignore rule", age_days=30)
    git(pool, "add", "-f", "build/forced.txt")
    git(pool, "commit", "-qm", "force-add")
    put(pool / "build/cache.bin", age_days=30)
    nested = pool / "dist/vendored"
    nested.mkdir(parents=True)
    git(nested, "init", "-q")  # a nested repository may hold unpushed commits
    put(nested / "f.txt", age_days=30)
    age(pool / "dist", 30)
    age(pool / "build", 30)

    run(tmp_path, scan=scan)

    assert (pool / "build/forced.txt").is_file()
    assert (pool / "build/cache.bin").is_file()
    assert (nested / ".git").is_dir()


@pytest.mark.parametrize("scan", SCANS)
def test_nothing_outside_a_pool_worktree_is_touched(tmp_path, pool, scan):
    outside = tmp_path / "elsewhere/repo"
    outside.mkdir(parents=True)
    git(outside, "init", "-q")
    put(outside / ".gitignore", "node_modules/\n")
    put(outside / "node_modules/a.js", age_days=30)
    age(outside / "node_modules", 30)
    # A pool entry that is a symlink to that repository, and an ignored symlink inside the worktree.
    (tmp_path / "pools/proj-1/4").mkdir()
    (tmp_path / "pools/proj-1/4/repo").symlink_to(outside)
    (pool / "dist").symlink_to(outside / "node_modules")
    # A repository that is not under <pool>/<n>/<repo> at all.
    stray = tmp_path / "pools/stray"
    stray.mkdir()
    git(stray, "init", "-q")
    put(stray / ".gitignore", "node_modules/\n")
    put(stray / "node_modules/a.js", age_days=30)
    age(stray / "node_modules", 30)

    run(tmp_path, scan=scan)

    assert (outside / "node_modules/a.js").is_file()
    assert (stray / "node_modules/a.js").is_file()
    assert (pool / "dist").is_symlink()


@pytest.mark.parametrize("scan", SCANS)
def test_a_build_named_directory_that_git_does_not_ignore_stays(tmp_path, pool, scan):
    put(
        pool / "target/notes.md",
        "untracked work in a directory named like build output",
        age_days=30,
    )
    age(pool / "target", 30)

    run(tmp_path, scan=scan)

    assert (pool / "target/notes.md").is_file()


@pytest.mark.parametrize("scan", SCANS)
def test_a_stale_directory_inside_a_live_build_directory_stays(tmp_path, pool, scan):
    """pnpm keeps node_modules/.pnpm/<pkg>/node_modules: old, but part of a node_modules in use."""
    put(pool / "node_modules/.pnpm/yargs/node_modules/yargs/index.js", age_days=30)
    age(pool / "node_modules/.pnpm", 30)
    put(pool / "node_modules/.bin/tool", age_days=1)

    run(tmp_path, scan=scan)

    assert (pool / "node_modules/.pnpm/yargs/node_modules/yargs/index.js").is_file()


def test_sizes_come_from_fdu_when_installed_and_from_du_otherwise(tmp_path, pool):
    put(pool / "node_modules/pkg/index.js", "x" * 3000, age_days=30)
    age(pool / "node_modules", 30)

    stub = run(tmp_path, "--dry-run", scan="lying-fdu").stdout
    assert f"would remove {pool}/node_modules (4.2KB)" in stub  # fdu's number
    assert "sizes: fdu" in stub
    assert "--view summary" in (tmp_path / "bin/fdu.log").read_text()

    for scan in ("find", "broken-fdu"):
        out = run(tmp_path, "--dry-run", scan=scan).stdout
        assert f"would remove {pool}/node_modules (3.0KB)" in out, scan  # du's number
    assert "sizes: du" in run(tmp_path, "--dry-run", scan="find").stdout


@NEEDS_FDU
def test_real_fdu_and_du_report_the_same_size(tmp_path, pool):
    put(pool / "node_modules/pkg/index.js", "x" * 5000, age_days=30)
    age(pool / "node_modules", 30)

    def line(scan):
        out = run(tmp_path, "--dry-run", scan=scan).stdout
        return next(row for row in out.splitlines() if row.startswith("would"))

    assert line("fdu") == line("find")


def test_the_age_threshold_is_configurable(tmp_path, pool):
    put(pool / "node_modules/pkg/index.js", age_days=3)
    age(pool / "node_modules", 3)

    run(tmp_path)
    assert (pool / "node_modules").exists()
    run(tmp_path, WORKTREE_PRUNE_AGE_DAYS="2")
    assert not (pool / "node_modules").exists()


def test_a_nested_clone_is_judged_by_its_own_repository(tmp_path, pool):
    """A directory the outer repository ignores but the clone inside it tracks stays."""
    put(pool / ".gitignore", "node_modules/\nprojects/\n")
    clone = pool / "projects/app"
    clone.mkdir(parents=True)
    git(clone, "init", "-q")
    put(clone / "dist/tracked.js", "shipped", age_days=30)
    git(clone, "add", "-f", "dist/tracked.js")
    git(clone, "commit", "-qm", "init")
    put(clone / ".gitignore", "node_modules/\n")
    put(clone / "node_modules/a.js", age_days=30)
    age(clone / "dist", 30)
    age(clone / "node_modules", 30)

    run(tmp_path, WORKTREE_PRUNE_NAMES="dist node_modules")

    assert (clone / "dist/tracked.js").is_file()
    assert not (clone / "node_modules").exists()


def test_a_name_that_could_escape_is_refused(tmp_path, pool):
    for bad in ("../x", ".git", "a/b"):
        result = subprocess.run(
            [str(SCRIPT)],
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(tmp_path),
                "WORKTREE_PRUNE_POOLS": str(tmp_path / "pools"),
                "WORKTREE_PRUNE_NAMES": bad,
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2, bad
