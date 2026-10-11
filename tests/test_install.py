"""install.sh and the npm launcher print the usage before any install step."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BASH = shutil.which("bash")


def sandbox(tmp_path):
    """An empty PATH (no apt-get, git or sudo) and a read-only HOME: any install step fails."""
    (tmp_path / "bin").mkdir()
    home = tmp_path / "home"
    home.mkdir(mode=0o500)
    return {"PATH": str(tmp_path / "bin"), "HOME": str(home)}


def install(env, *args):
    # Script on stdin, the way `curl | bash` and the launcher run it.
    return subprocess.run(
        [BASH, "-s", "--", *args],
        input=(ROOT / "install.sh").read_text(),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


@pytest.mark.parametrize("args", [["--help"], ["-h"], ["--container", "--help"], ["--user", "--help"]])
def test_help_prints_usage_and_changes_nothing(tmp_path, args):
    result = install(sandbox(tmp_path), *args)
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.startswith("Usage: crewship ")
    assert not any((tmp_path / "home").iterdir())


@pytest.mark.parametrize("args", [["--bogus"], ["--user"], ["--container", "extra"]])
def test_bad_option_prints_usage_and_fails(tmp_path, args):
    result = install(sandbox(tmp_path), *args)
    assert result.returncode == 2
    assert f"bad option: {args[-1]}" in result.stderr
    assert "Usage: crewship " in result.stderr
    assert result.stdout == ""


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_launcher_help_matches_install_without_fetch(tmp_path):
    env = sandbox(tmp_path)
    # A fetch would throw, so only a local usage print can exit 0.
    stub = tmp_path / "no-fetch.js"
    stub.write_text("globalThis.fetch = () => { throw new Error('fetch called'); };\n")
    result = subprocess.run(
        [shutil.which("node"), "--require", str(stub), str(ROOT / "npm/crewship.js"), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout == install(env, "--help").stdout


# Release install, update and migration: the real build-release-artifact.sh and
# install.sh run against a curl shim that serves a local mirror of the GitHub URL layout.
CURL_SHIM = """#!/usr/bin/env bash
out=; fmt=
while (($#)); do
  case $1 in -o) out=$2; shift 2 ;; -w) fmt=$2; shift 2 ;; -*) shift ;; *) url=$1; shift ;; esac
done
code=200; redirect=
case $url in
  https://github.com/*/releases/latest) code=302; redirect=https://github.com/i098/Crewship/releases/tag/$(cat "$MIRROR/latest") ;;
  https://github.com/*/releases/download/*/*)
    if [ -f "$MIRROR/${url##*/}" ]; then cp "$MIRROR/${url##*/}" "$out"; else : >"$out"; code=404; fi ;;
  *) code=403; echo '{}' >"$out" ;;
esac
case $fmt in *redirect_url*) printf %s "$redirect" ;; *http_code*) printf %s "$code" ;; esac
"""
SHIP = """#!/usr/bin/env bash
echo "$1" >>"$HOME/calls"
if [ "$1" = dock ]; then mkdir -p .local && echo "dock-v$(cat VERSION)" >.local/host.yml; fi
"""


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


class Release:
    """A mirror holding releases v1.0.0 and v1.1.0 built by scripts/build-release-artifact.sh."""

    def __init__(self, tmp_path):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.mirror = tmp_path / "mirror"
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        (self.repo / "ship.sh").write_text(SHIP)
        (self.repo / "ship.sh").chmod(0o755)
        (self.repo / "onboard.sh").write_text("#!/usr/bin/env bash\n")
        (self.repo / "onboard.sh").chmod(0o755)
        git(self.repo, "init", "-q")
        for tag in ("v1.0.0", "v1.1.0"):
            (self.repo / "VERSION").write_text(tag[1:])
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-qm", tag)
            git(self.repo, "tag", tag)
            subprocess.run([BASH, str(ROOT / "scripts/build-release-artifact.sh"), tag, str(self.mirror)], cwd=self.repo, check=True)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in {"curl": CURL_SHIM, "apt-get": "#!/bin/sh\n", "dpkg-query": "#!/bin/sh\nprintf installed\n"}.items():
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        self.env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(self.home), "MIRROR": str(self.mirror)}

    def install(self, latest, *args):
        (self.mirror / "latest").write_text(latest)
        return subprocess.run(
            [BASH, "-s", "--", *args],
            input=(ROOT / "install.sh").read_text(),
            capture_output=True,
            text=True,
            env=self.env,
            timeout=60,
        )

    @property
    def crewship(self):
        return self.home / "Crewship"

    @property
    def releases(self):
        return self.home / ".local/share/crewship/releases"


@pytest.fixture
def release(tmp_path):
    return Release(tmp_path)


def test_fresh_install_unpacks_a_release_without_git(release):
    result = release.install("v1.0.0")
    assert result.returncode == 0, result.stderr
    assert release.crewship.is_symlink()
    assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
    assert not (release.crewship / ".git").exists()
    assert (release.crewship / ".local/host.yml").read_text() == "dock-v1.0.0\n"
    assert (release.home / "calls").read_text().split() == ["dock", "inspect", "chart", "launch"]


def test_update_keeps_host_files_and_removes_the_replaced_release(release):
    assert release.install("v1.0.0").returncode == 0
    (release.crewship / ".local/host.yml").write_text("mine\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.1.0").resolve()
    assert (release.crewship / "VERSION").read_text() == "1.1.0"
    assert (release.crewship / ".local/host.yml").read_text() == "mine\n"
    assert [p.name for p in release.releases.iterdir()] == ["v1.1.0"]
    assert "dock" not in (release.home / "calls").read_text().split()[4:]


def test_bad_checksum_leaves_the_install_untouched(release):
    assert release.install("v1.0.0").returncode == 0
    (release.mirror / "crewship-v1.1.0.tar.gz.sha256").write_text(f"{'0' * 64}  crewship-v1.1.0.tar.gz\n")
    result = release.install("v1.1.0")
    assert result.returncode != 0
    assert "does not match its .sha256" in result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
    assert [p.name for p in release.releases.iterdir()] == ["v1.0.0"]


def test_missing_artifact_says_to_retry_and_never_clones(release):
    result = release.install("v9.9.9")
    assert result.returncode != 0
    assert "the release v9.9.9 has no install artifact yet; try again in a few minutes" in result.stderr
    assert not release.crewship.exists()


def test_git_clone_migrates_to_a_release_and_a_backup(release):
    subprocess.run(["git", "clone", "-q", str(release.repo), str(release.crewship)], check=True)
    (release.crewship / ".local").mkdir()
    (release.crewship / ".local/host.yml").write_text("mine\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert release.crewship.is_symlink()
    assert (release.crewship / ".local/host.yml").read_text() == "mine\n"
    (backup,) = release.home.glob("Crewship.git-backup-*")
    assert (backup / ".git").is_dir()
    assert (backup / ".local/host.yml").read_text() == "mine\n"
