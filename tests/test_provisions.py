import hashlib
import importlib.util
import io
import json
import runpy
import ssl
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "provisions", Path(__file__).parents[1] / "scripts/provisions.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class Download(io.BytesIO):
    def __init__(self, body, url="https://downloads.example.test/tool"):
        super().__init__(body)
        self.url = url

    def geturl(self):
        return self.url


def asset(payload, checksum=None):
    return {
        "version": "1.0.0",
        "assets": {
            "linux-x86_64": {
                "url": "https://downloads.example.test/tool",
                "sha256": checksum or hashlib.sha256(payload).hexdigest(),
                "format": "file",
                "binaries": {"tool": "tool"},
            }
        },
    }


def test_verified_install_runs_and_second_install_changes_nothing(tmp_path, monkeypatch):
    payload = b"#!/bin/sh\nprintf 'tool 1.0.0\\n'\n"
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(payload))
    spec = asset(payload)
    assert installer.install_asset(tmp_path, "tool", spec, "linux-x86_64")
    command = tmp_path / ".local/bin/tool"
    assert subprocess.check_output([command], text=True).strip() == "tool 1.0.0"
    assert not installer.install_asset(tmp_path, "tool", spec, "linux-x86_64")


@pytest.mark.parametrize(
    ("key", "arch"), [("linux-x86_64", "x86_64"), ("linux-aarch64", "arm64")]
)
def test_neovim_keeps_its_runtime_tree_and_installs_once(tmp_path, monkeypatch, key, arch):
    archive = io.BytesIO()
    root = f"nvim-linux-{arch}"
    files = {
        f"{root}/bin/nvim": b"#!/bin/sh\nprintf 'NVIM v9.9.9\\n'\n",
        f"{root}/lib/nvim/parser/python.so": b"parser",
        f"{root}/share/nvim/runtime/syntax/python.vim": b"syntax",
    }
    with tarfile.open(fileobj=archive, mode="w:gz") as stream:
        for name, payload in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            stream.addfile(member, io.BytesIO(payload))
    payload = archive.getvalue()
    upstream(monkeypatch)
    spec = installer.resolve_latest(key, {"nvim"})["nvim"]
    assert spec["version"] == "9.9.9"
    assert spec["assets"][key]["sha256"] == "a" * 64
    assert spec["assets"][key]["format"] == "tar"
    spec["assets"][key]["sha256"] = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(payload))
    assert installer.install_asset(tmp_path, "nvim", spec, key)
    command = tmp_path / ".local/bin/nvim"
    assert command.is_symlink()
    assert subprocess.check_output([command, "--version"], text=True).strip() == "NVIM v9.9.9"
    installed = command.resolve().parents[2]
    for name, content in files.items():
        assert (installed / name).read_bytes() == content
    assert not installer.install_asset(tmp_path, "nvim", spec, key)


def test_bad_checksum_never_installs_command(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(b"corrupt"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        installer.install_asset(tmp_path, "tool", asset(b"expected"), "linux-x86_64")
    assert not (tmp_path / ".local/bin/tool").exists()


def test_unmanaged_command_is_preserved(tmp_path, monkeypatch):
    command = tmp_path / ".local/bin/tool"
    command.parent.mkdir(parents=True)
    command.write_bytes(b"user-owned")
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(b"new"))
    with pytest.raises(ValueError, match="unmanaged command"):
        installer.install_asset(tmp_path, "tool", asset(b"new"), "linux-x86_64")
    assert command.read_bytes() == b"user-owned"


def test_local_binary_drift_is_not_silently_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(b"original"))
    spec = asset(b"original")
    installer.install_asset(tmp_path, "tool", spec, "linux-x86_64")
    (tmp_path / ".local/bin/tool").write_bytes(b"changed locally")
    with pytest.raises(ValueError, match="drifted"):
        installer.install_asset(tmp_path, "tool", spec, "linux-x86_64")


@pytest.mark.parametrize("kind", ["tar", "zip"])
def test_archive_traversal_cannot_escape_staging(tmp_path, kind):
    archive = tmp_path / "archive"
    destination = tmp_path / "staging"
    destination.mkdir()
    if kind == "tar":
        with tarfile.open(archive, "w") as stream:
            member = tarfile.TarInfo("../escaped")
            member.size = 1
            stream.addfile(member, io.BytesIO(b"x"))
        error = tarfile.FilterError
    else:
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("../escaped", b"x")
        error = ValueError
    with pytest.raises(error):
        installer.extract(archive, destination, kind, "tool")
    assert not (tmp_path / "escaped").exists()


def test_download_rejects_plain_http(tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        installer.download("http://example.test/tool", "0" * 64, tmp_path / "download")


def http_error(code):
    return installer.urllib.error.HTTPError(
        "https://downloads.example.test/tool", code, "x", {}, None
    )


def test_download_retries_a_transient_server_error(tmp_path, monkeypatch):
    payload = b"payload"
    replies = [http_error(500), installer.urllib.error.URLError("reset"), Download(payload)]
    pauses = []

    def urlopen(*args, **kwargs):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(installer.time, "sleep", pauses.append)
    target = tmp_path / "download"
    installer.download(
        "https://downloads.example.test/tool", hashlib.sha256(payload).hexdigest(), target
    )
    assert target.read_bytes() == payload
    assert pauses == [1, 2]


@pytest.mark.parametrize(("failure", "calls"), [(http_error(404), 1), (http_error(503), 3)])
def test_download_never_retries_a_client_error_and_gives_up_after_three_attempts(
    tmp_path, monkeypatch, failure, calls
):
    seen = []

    def urlopen(*args, **kwargs):
        seen.append(args)
        raise failure

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(installer.time, "sleep", lambda seconds: None)
    with pytest.raises(installer.urllib.error.HTTPError):
        installer.download("https://downloads.example.test/tool", "0" * 64, tmp_path / "download")
    assert len(seen) == calls


def test_fetch_retries_a_tls_eof_and_keeps_a_client_error_final(monkeypatch):
    replies = [ssl.SSLEOFError("EOF"), installer.urllib.error.URLError("reset"), Download(b"ok")]

    def urlopen(*args, **kwargs):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(installer.time, "sleep", lambda seconds: None)
    assert installer.fetch("https://nodejs.org/dist/index.json", "node release") == b"ok"

    replies[:] = [http_error(403)]
    with pytest.raises(ValueError, match="HTTP 403"):
        installer.fetch("https://api.github.com/repos/x/y/releases/latest", "x release")
    assert replies == []


# What each fake GitHub release publishes for linux-x86_64: tag and asset name.
RELEASES = {
    "herdrdev/herdr": ("v9.9.9", "herdr-linux-x86_64"),
    "oven-sh/bun": ("bun-v9.9.9", "bun-linux-x64-baseline.zip"),
    "cli/cli": ("v9.9.9", "gh_9.9.9_linux_amd64.tar.gz"),
    "neovim/neovim": ("v9.9.9", "nvim-linux-x86_64.tar.gz", "nvim-linux-arm64.tar.gz"),
    "kunchenguid/no-mistakes": ("v9.9.10-beta.1", "no-mistakes-v9.9.10-beta.1-linux-amd64.tar.gz"),
    "kunchenguid/treehouse": ("v9.9.9", "treehouse-v9.9.9-linux-amd64.tar.gz"),
    "astral-sh/uv": ("9.9.9", "uv-x86_64-unknown-linux-gnu.tar.gz"),
    "aristocratos/btop": ("v9.9.9", "btop-x86_64-unknown-linux-musl.tar.gz"),
    "sentrux/sentrux": ("v9.9.9", "sentrux-linux-x86_64", "grammars-linux-x86_64.tar.gz"),
    "fallow-rs/fallow": ("v9.9.9", "fallow-linux-x64-musl"),
    "cloudflare/cloudflared": ("9.9.9", "cloudflared-linux-amd64"),
    "facebook/pyrefly": (
        "9.9.9",
        "pyrefly-linux-x86_64-musl.tar.gz",
        "pyrefly-linux-x86_64-musl.tar.gz.sha256",
    ),
    "chojs23/concord": ("v9.9.9", "concord-x86_64-unknown-linux-gnu.tar.xz"),
    "gammons/slk": ("v9.9.9", "slk_9.9.9_linux_x86_64.tar.gz"),
    "h4ckf0r0day/obscura": ("v9.9.9", "obscura-x86_64-linux.tar.gz"),
    "jimididit/koncreet": ("v9.9.9", "koncreet.tar.gz"),
    "jj-vcs/jj": ("v9.9.9", "jj-v9.9.9-x86_64-unknown-linux-musl.tar.gz"),
    "googleworkspace/cli": (
        "v9.9.9",
        "google-workspace-cli-x86_64-unknown-linux-musl.tar.gz",
        "google-workspace-cli-x86_64-unknown-linux-musl.tar.gz.sha256",
    ),
}


def codeberg(url, unverified):
    """Fake Forgejo's Codeberg releases and each binary's .sha256 file.

    The newest is v9.9.9, listed after an older LTS point release that was published later.
    """
    if url.endswith(".sha256"):
        checksum = "" if unverified == "forgejo" else "9" * 64
        return Download(f"{checksum}  {url.rsplit('/', 1)[1].removesuffix('.sha256')}\n".encode())
    assert url == installer.FORGEJO_RELEASES, url

    def release(version):
        assets = [
            {"name": name + suffix, "browser_download_url": f"https://codeberg.org/{name}{suffix}"}
            for name in (f"forgejo-{version}-linux-amd64", f"forgejo-{version}-linux-arm64")
            for suffix in ("", ".sha256", ".asc")
        ]
        return {"tag_name": f"v{version}", "assets": assets}

    return Download(json.dumps([release("9.0.10"), release("9.9.9")]).encode())


def upstream(monkeypatch, unverified=None, seen=None):
    """Fake GitHub, nodejs.org, rustup, npm and PyPI; `unverified` publishes no SHA-256 for that source.

    Every repository's latest stable release is v9.9.9. no-mistakes also lists a
    newer prerelease, and a still newer draft above it, as GitHub's release list does.
    """

    def urlopen(request, **kwargs):
        url = request.full_url
        if seen is not None:
            seen.append((url, request.get_header("Authorization")))
        if url.startswith("https://api.github.com/repos/"):
            repo, _, listing = url.removeprefix("https://api.github.com/repos/").partition(
                "/releases"
            )
            digest = None if repo == unverified else "sha256:" + "a" * 64

            def release(tag, *names, draft=False):
                assets = [
                    {
                        "name": name,
                        "browser_download_url": f"https://github.com/{name}",
                        "digest": digest,
                    }
                    for name in names
                ]
                return {"tag_name": tag, "draft": draft, "assets": assets}

            if listing == "?per_page=10":
                assert repo == "kunchenguid/no-mistakes", f"{repo} is on the stable channel"
                tag, name = RELEASES[repo]
                body = [
                    release("v9.9.11", "no-mistakes-v9.9.11-linux-amd64.tar.gz", draft=True),
                    release(tag, name),
                    release("v9.9.9", "no-mistakes-v9.9.9-linux-amd64.tar.gz"),
                ]
            else:
                assert listing == "/latest", url
                assert repo != "kunchenguid/no-mistakes", "no-mistakes is on the prerelease channel"
                body = release(*RELEASES[repo])
        elif url == "https://nodejs.org/dist/index.json":
            body = [{"version": "v9.99.0"}, {"version": "v30.1.0"}]
        elif url == "https://nodejs.org/dist/v30.1.0/SHASUMS256.txt":
            sums = "" if unverified == "node" else "b" * 64 + "  node-v30.1.0-linux-x64.tar.xz\n"
            return Download(("c" * 64 + "  node-v30.1.0-linux-arm64.tar.xz\n" + sums).encode())
        elif url == "https://static.rust-lang.org/rustup/release-stable.toml":
            return Download(b"schema-version = '1'\nversion = '9.9.9'\n")
        elif url.endswith("/rustup-init.sha256"):
            checksum = "" if unverified == "rustup-init" else "d" * 64
            return Download(f"{checksum} *./rustup-init\n".encode())
        elif url.startswith("https://github.com/google-workspace-cli-") and url.endswith(".sha256"):
            # gws publishes its own .sha256 file, which wins over the GitHub digest.
            checksum = "" if unverified == "googleworkspace/cli" else "f" * 64
            return Download(f"{checksum}  google-workspace-cli.tar.gz\n".encode())
        elif url.startswith("https://github.com/pyrefly-") and url.endswith(".sha256"):
            checksum = "" if unverified == "facebook/pyrefly" else "f" * 64
            return Download(f"{checksum}  {url.rsplit('/', 1)[1].removesuffix('.sha256')}".encode())
        elif url.startswith("https://codeberg.org/"):
            return codeberg(url, unverified)
        elif url == "https://pypi.org/pypi/psutil/json":
            files = [] if unverified == "psutil" else [{"digests": {"sha256": "e" * 64}}]
            body = {"info": {"version": "9.9.9"}, "urls": files}
        else:
            body = {"version": "18.9.9"}
        return Download(json.dumps(body).encode())

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)


EVERYTHING = {
    *installer.GITHUB_LATEST,
    *installer.NPM_LATEST,
    "node",
    "rustup-init",
    "psutil",
}


def test_latest_releases_are_pinned_to_the_digests_their_publishers_list(monkeypatch):
    upstream(monkeypatch)
    latest = installer.resolve_latest("linux-x86_64", EVERYTHING)
    for tool in (
        "herdr",
        "bun",
        "gh",
        "no-mistakes",
        "treehouse",
        "uv",
        "btop",
        "sentrux",
        "sentrux-grammars",
        "fallow",
        "concord",
        "slk",
        "obscura",
        "koncreet",
        "jj",
    ):
        assert latest[tool]["assets"]["linux-x86_64"]["sha256"] == "a" * 64
    for tool in (
        "herdr",
        "bun",
        "gh",
        "treehouse",
        "uv",
        "btop",
        "sentrux",
        "fallow",
        "concord",
        "slk",
        "obscura",
        "koncreet",
        "jj",
    ):
        assert latest[tool]["version"] == "9.9.9"
    gws = latest["gws"]["assets"]["linux-x86_64"]
    assert (latest["gws"]["version"], gws["sha256"]) == ("9.9.9", "f" * 64)
    assert gws["url"].endswith("google-workspace-cli-x86_64-unknown-linux-musl.tar.gz")
    assert latest["gh"]["assets"]["linux-x86_64"]["format"] == "tar"
    assert latest["bun"]["assets"]["linux-x86_64"]["format"] == "zip"
    assert latest["sentrux"]["assets"]["linux-x86_64"]["format"] == "file"
    assert latest["fallow"]["assets"]["linux-x86_64"]["format"] == "file"
    assert latest["sentrux-grammars"]["assets"]["linux-x86_64"]["format"] == "tar"
    assert latest["concord"]["assets"]["linux-x86_64"]["format"] == "tar"
    assert latest["jj"]["assets"]["linux-x86_64"]["format"] == "tar"
    # The newest Node release, not the first index entry, verified by SHASUMS256.
    node = latest["node"]["assets"]["linux-x86_64"]
    assert latest["node"]["version"] == "30.1.0"
    assert node["url"] == "https://nodejs.org/dist/v30.1.0/node-v30.1.0-linux-x64.tar.xz"
    assert node["sha256"] == "b" * 64
    rustup = latest["rustup-init"]["assets"]["linux-x86_64"]
    assert rustup["url"].endswith("/9.9.9/x86_64-unknown-linux-gnu/rustup-init")
    assert (rustup["sha256"], rustup["format"]) == ("d" * 64, "file")
    assert latest["psutil"] == {"version": "9.9.9", "sha256": ["e" * 64]}
    for tool in installer.NPM_LATEST:
        assert latest[tool] == "18.9.9"


def test_forgejo_resolves_from_codeberg_with_its_checksum_file_and_signature(monkeypatch):
    upstream(monkeypatch)
    forgejo = installer.resolve_latest("linux-x86_64", {"forgejo"})["forgejo"]
    asset = forgejo["assets"]["linux-x86_64"]
    assert forgejo["version"] == "9.9.9"
    assert asset["url"] == "https://codeberg.org/forgejo-9.9.9-linux-amd64"
    assert (asset["sha256"], asset["format"]) == ("9" * 64, "file")
    # Ansible checks this signature against the Forgejo release key before installing.
    assert asset["signature"] == "https://codeberg.org/forgejo-9.9.9-linux-amd64.asc"


def test_forgejo_without_a_published_checksum_is_refused(monkeypatch):
    upstream(monkeypatch, unverified="forgejo")
    with pytest.raises(ValueError, match="refusing an unverified binary"):
        installer.resolve_latest("linux-x86_64", {"forgejo"})



@pytest.mark.parametrize(
    ("key", "arch"), [("linux-x86_64", "x86_64"), ("linux-aarch64", "arm64")]
)
def test_pyrefly_musl_release_installs_verified_tar_and_is_idempotent(
    monkeypatch, tmp_path, key, arch
):
    name = f"pyrefly-linux-{arch}-musl.tar.gz"
    monkeypatch.setitem(RELEASES, "facebook/pyrefly", ("9.9.9", name, name + ".sha256"))
    upstream(monkeypatch)
    payload = b"#!/bin/sh\nprintf 'pyrefly 9.9.9\\n'\n"
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as archive:
        member = tarfile.TarInfo("pyrefly")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    tar = packed.getvalue()
    checksum = hashlib.sha256(tar).hexdigest()
    original = installer.urllib.request.urlopen

    def urlopen(request, **kwargs):
        url = request if isinstance(request, str) else request.full_url
        if url == f"https://github.com/{name}.sha256":
            return Download(f"{checksum}  {name}".encode())
        if url == f"https://github.com/{name}":
            return Download(tar)
        return original(request, **kwargs)

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    spec = installer.resolve_latest(key, {"pyrefly"})["pyrefly"]
    assert spec["version"] == "9.9.9"
    assert installer.install_asset(tmp_path, "pyrefly", spec, key)
    command = tmp_path / ".local/bin/pyrefly"
    assert subprocess.check_output([command, "--version"], text=True).strip() == "pyrefly 9.9.9"
    assert not installer.install_asset(tmp_path, "pyrefly", spec, key)


def test_no_mistakes_follows_the_prerelease_channel_and_skips_drafts(monkeypatch):
    seen = []
    upstream(monkeypatch, seen=seen)
    latest = installer.resolve_latest("linux-x86_64", EVERYTHING)
    # Newer than the latest stable v9.9.9, older than the unpublished draft v9.9.11.
    no_mistakes = latest["no-mistakes"]
    assert no_mistakes["version"] == "9.9.10-beta.1"
    assert no_mistakes["assets"]["linux-x86_64"]["url"].endswith(
        "no-mistakes-v9.9.10-beta.1-linux-amd64.tar.gz"
    )
    requested = {url for url, _ in seen if url.startswith("https://api.github.com/repos/")}
    assert "https://api.github.com/repos/kunchenguid/no-mistakes/releases?per_page=10" in requested
    assert "https://api.github.com/repos/kunchenguid/no-mistakes/releases/latest" not in requested
    assert "https://api.github.com/repos/kunchenguid/treehouse/releases/latest" in requested


def test_a_release_list_with_only_drafts_is_refused(monkeypatch):
    def urlopen(request, **kwargs):
        return Download(json.dumps([{"tag_name": "v9.9.11", "draft": True, "assets": []}]).encode())

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    with pytest.raises(ValueError, match="no-mistakes has no published release"):
        installer.resolve_latest("linux-x86_64", {"no-mistakes"})


@pytest.mark.parametrize(
    "source",
    [*(repo for repo in RELEASES if repo != "jimididit/koncreet"), "node", "rustup-init", "psutil"],
)
def test_release_without_a_published_checksum_is_refused(monkeypatch, source):
    upstream(monkeypatch, unverified=source)
    with pytest.raises(ValueError, match="refusing an unverified binary"):
        installer.resolve_latest("linux-x86_64", EVERYTHING)


UNSAFE_TAGS = ["v1.0$(id)", "v1;id", 'v1"x', "v1`id`", "v1|id", "v1 2", "v/1"]


@pytest.mark.parametrize("tag", UNSAFE_TAGS)
def test_release_tag_that_is_not_a_plain_version_is_refused(monkeypatch, tag):
    monkeypatch.setitem(RELEASES, "herdrdev/herdr", (tag, "herdr-linux-x86_64"))
    upstream(monkeypatch)
    with pytest.raises(ValueError, match="not a safe version"):
        installer.resolve_latest("linux-x86_64", EVERYTHING)


def resolve_without_koncreet(capsys):
    latest = installer.resolve_latest("linux-x86_64", EVERYTHING)
    assert "koncreet" not in latest
    assert {"herdr", "uv", "obscura", "node", "psutil"} <= latest.keys()
    return capsys.readouterr().err


@pytest.mark.parametrize("tag", UNSAFE_TAGS)
def test_koncreet_release_with_an_unsafe_tag_is_skipped_with_a_warning(monkeypatch, capsys, tag):
    monkeypatch.setitem(RELEASES, "jimididit/koncreet", (tag, "koncreet.tar.gz"))
    upstream(monkeypatch)
    assert "not a safe version" in resolve_without_koncreet(capsys)


def test_koncreet_release_without_a_published_checksum_is_skipped_with_a_warning(
    monkeypatch, capsys
):
    upstream(monkeypatch, unverified="jimididit/koncreet")
    assert "refusing an unverified binary" in resolve_without_koncreet(capsys)


def test_koncreet_release_without_its_asset_is_skipped_with_a_warning(monkeypatch, capsys):
    monkeypatch.setitem(RELEASES, "jimididit/koncreet", ("v9.9.9", "renamed.tar.gz"))
    upstream(monkeypatch)
    assert "refusing an unverified binary" in resolve_without_koncreet(capsys)


@pytest.mark.parametrize(
    "failure",
    [
        installer.urllib.error.HTTPError("https://api.github.com/", 403, "rate limited", {}, None),
        installer.urllib.error.URLError("offline"),
    ],
)
def test_koncreet_lookup_failure_is_skipped_with_a_warning(monkeypatch, capsys, failure):
    upstream(monkeypatch)
    fake = installer.urllib.request.urlopen

    def urlopen(request, **kwargs):
        if "jimididit/koncreet" in request.full_url:
            raise failure
        return fake(request, **kwargs)

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    assert "skipping optional koncreet" in resolve_without_koncreet(capsys)


def test_resolve_cli_still_succeeds_when_koncreet_cannot_be_resolved(monkeypatch, capsys, tmp_path):
    upstream(monkeypatch, unverified="jimididit/koncreet")
    latest = run_cli(monkeypatch, capsys, tmp_path, "--tools", "uv", "--also", "koncreet")
    assert set(latest) == {"uv"}


@pytest.mark.parametrize(("env", "expected"), [("env-token", "Bearer env-token"), ("", None)])
def test_github_token_goes_only_to_the_github_api(monkeypatch, env, expected):
    seen = []
    monkeypatch.setenv("GITHUB_TOKEN", env)
    upstream(monkeypatch, seen=seen)
    installer.resolve_latest("linux-x86_64", EVERYTHING)
    github = {auth for url, auth in seen if url.startswith("https://api.github.com/")}
    assert github == {expected}
    assert {auth for url, auth in seen if not url.startswith("https://api.github.com/")} == {None}


def run_cli(monkeypatch, capsys, tmp_path, *argv):
    monkeypatch.setattr(installer, "platform_key", lambda: "linux-x86_64")
    monkeypatch.setattr(
        installer.sys, "argv", ["provisions.py", "--home", str(tmp_path), *argv, "--resolve"]
    )
    installer.main()
    return json.loads(capsys.readouterr().out)


def test_resolve_covers_only_the_requested_tools(monkeypatch, capsys, tmp_path):
    seen = []
    upstream(monkeypatch, unverified="psutil", seen=seen)
    latest = run_cli(monkeypatch, capsys, tmp_path, "--tools", "uv")
    assert set(latest) == {"uv"}
    assert [url for url, _ in seen] == ["https://api.github.com/repos/astral-sh/uv/releases/latest"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--tools", "herdr,node"], {"herdr", "node"}),
        (["--tools", "uv", "--development"], {"uv", "rustup-init"}),
        (
            ["--tools", "uv", "--npm"],
            {"uv", *installer.AGENT_TOOLS, *installer.NPM_LATEST},
        ),
        (["--tools", "uv", "--also", "psutil"], {"uv", "psutil"}),
        (["--tools", "uv", "--also", "forgejo"], {"uv", "forgejo"}),
        (["--tools", "sentrux"], {"sentrux", "sentrux-grammars"}),
        (["--tools", "pyrefly"], {"pyrefly"}),
        (["--tools", "jj"], {"jj"}),
    ],
)
def test_resolve_selection_matches_what_the_flags_install(
    monkeypatch, capsys, tmp_path, argv, expected
):
    upstream(monkeypatch)
    assert set(run_cli(monkeypatch, capsys, tmp_path, *argv)) == expected


def test_resolve_refuses_a_source_that_does_not_exist(monkeypatch, capsys, tmp_path):
    upstream(monkeypatch)
    with pytest.raises(ValueError, match="no latest release source for: nonesuch"):
        run_cli(monkeypatch, capsys, tmp_path, "--tools", "uv", "--also", "nonesuch")


def test_the_dropped_npm_set_loses_its_links_but_keeps_the_prefix_and_other_installs(tmp_path):
    bin_dir = tmp_path / ".local/bin"
    bin_dir.mkdir(parents=True)
    legacy = tmp_path / ".local/share/crewship/npm/node_modules"
    for name in ("codex", "pnpm"):
        script = legacy / name / "bin.js"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/sh\n")
        (bin_dir / name).symlink_to(script)
    elsewhere = tmp_path / ".bun/bin/pnpx"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("#!/bin/sh\n")
    (bin_dir / "pnpx").symlink_to(elsewhere)
    assert installer.retire_legacy_npm(tmp_path)
    assert not (bin_dir / "codex").is_symlink()
    assert not (bin_dir / "pnpm").is_symlink()
    assert (legacy / "codex/bin.js").is_file()
    assert (legacy / "pnpm/bin.js").is_file()
    assert (bin_dir / "pnpx").resolve() == elsewhere
    assert not installer.retire_legacy_npm(tmp_path)


def test_omp_plugins_are_managed_from_the_target_home_whatever_the_installer_cwd(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    omp = home / ".local/bin/omp"
    omp.parent.mkdir(parents=True)
    omp.write_text(
        "#!/bin/sh\n"
        f'pwd >> "{tmp_path}/cwds"\n'
        'case "$2" in list) echo \'{"marketplace": []}\' ;; upgrade) echo "up to date" ;; esac\n'
    )
    omp.chmod(0o755)
    elsewhere = tmp_path / "checkout-under-another-users-home"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    installer.omp_plugins(home, {})
    assert set((tmp_path / "cwds").read_text().split()) == {str(home)}


def test_current_follows_the_newest_release_and_a_repeat_changes_nothing(tmp_path):
    tool = tmp_path / "chrome-devtools-mcp"
    for version in ("1.0.0", "1.1.0"):
        (tool / version).mkdir(parents=True)
    assert installer.point_current(tool / "1.0.0")
    assert not installer.point_current(tool / "1.0.0")
    assert (tool / "current").resolve() == tool / "1.0.0"
    assert installer.point_current(tool / "1.1.0")
    assert (tool / "current").resolve() == tool / "1.1.0"
    assert (tool / "1.0.0").is_dir()


def test_sentrux_grammars_replace_its_own_download_with_the_verified_release(tmp_path):
    store = tmp_path / "store"
    (store / "c/grammars").mkdir(parents=True)
    (store / "c/grammars/linux-x86_64.so").write_bytes(b"verified")
    # What sentrux fetched itself, unverified, before the installer managed it.
    grammar = tmp_path / ".sentrux/plugins/c/grammars/linux-x86_64.so"
    grammar.parent.mkdir(parents=True)
    grammar.write_bytes(b"unverified")
    assert installer.link_grammars(tmp_path, store)
    assert grammar.read_bytes() == b"verified"
    assert not installer.link_grammars(tmp_path, store)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], {"herdr": {"version": "1"}, "uv": {"version": "1"}}),
        (
            ["--resolved", json.dumps({"uv": {"version": "2"}})],
            {"herdr": {"version": "1"}, "uv": {"version": "2"}},
        ),
    ],
)
def test_an_apply_merges_its_resolved_record_into_the_existing_one(
    monkeypatch, tmp_path, argv, expected
):
    record = tmp_path / ".local/share/crewship/resolved.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"herdr": {"version": "1"}, "uv": {"version": "1"}}) + "\n")
    upstream(monkeypatch)
    monkeypatch.setattr(installer, "platform_key", lambda: "linux-x86_64")
    monkeypatch.setattr(installer, "install_asset", lambda *args: False)
    monkeypatch.setattr(
        installer.sys, "argv", ["provisions.py", "--home", str(tmp_path), "--tools", "uv", *argv]
    )
    installer.main()
    assert json.loads(record.read_text()) == expected


def test_a_failed_command_reports_why_it_failed(monkeypatch, capsys, tmp_path):
    rustup = tmp_path / ".cargo/bin/rustup"
    rustup.parent.mkdir(parents=True)
    rustup.write_text("#!/bin/sh\necho 'error: network down' >&2\nexit 1\n")
    rustup.chmod(0o755)
    payload = b"#!/bin/sh\n"
    resolved = {}
    for name in ("uv", "rustup-init"):
        resolved[name] = asset(payload)
        resolved[name]["assets"]["linux-x86_64"]["binaries"] = {name: name}
    monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(installer.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(payload))
    monkeypatch.setattr(
        installer.sys,
        "argv",
        ["provisions.py", "--home", str(tmp_path), "--tools", "uv", "--development"]
        + ["--resolved", json.dumps(resolved)],
    )
    with pytest.raises(SystemExit) as exit_status:
        runpy.run_path(str(SPEC.origin), run_name="__main__")
    assert exit_status.value.code == 1
    assert "error: network down" in capsys.readouterr().err


def test_every_installed_tool_has_a_built_with_line():
    credits = (Path(__file__).parents[1] / "CREDITS.md").read_text()
    tools = {*EVERYTHING, *installer.OMP_PLUGINS}
    assert [tool for tool in sorted(tools) if f"`{tool}`" not in credits] == []


def rate_limited_github(monkeypatch):
    """GitHub whose API refuses every call (HTTP 403, the 60 an hour budget spent) but whose public pages answer."""
    api = installer.urllib.request.urlopen

    def urlopen(request, **kwargs):
        url = request.full_url
        if url.startswith("https://api.github.com/"):
            raise http_error(403)
        if url.endswith(".sha256"):
            return Download(b"f" * 64 + b"  asset")
        if not url.startswith("https://github.com/"):
            return api(request, **kwargs)
        repo = "/".join(url.split("/")[3:5])
        tag, *names = RELEASES[repo]
        if url.endswith("/releases/latest"):
            return Download(b"", url=f"https://github.com/{repo}/releases/tag/{tag}")
        if url.endswith("/releases.atom"):
            return Download(f'<link href="https://github.com/{repo}/releases/tag/{tag}"/>'.encode())
        assert url.endswith(f"/releases/expanded_assets/{tag}"), url
        page = "".join(
            f'<a href="/{repo}/releases/download/{tag}/{name}">{name}</a>'
            f'<span class="Truncate-text">sha256:{"a" * 64}</span>'
            for name in names
        )
        return Download(page.encode())

    upstream(monkeypatch)
    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(installer.time, "sleep", lambda seconds: None)


def test_a_rate_limited_api_falls_back_to_the_public_release_pages(monkeypatch, capsys):
    rate_limited_github(monkeypatch)
    latest = installer.resolve_latest("linux-x86_64", EVERYTHING)
    assert "reading github.com's release pages instead" in capsys.readouterr().err
    assert latest["uv"]["version"] == "9.9.9"
    assert latest["uv"]["assets"]["linux-x86_64"] == {
        "url": "https://github.com/astral-sh/uv/releases/download/9.9.9/uv-x86_64-unknown-linux-gnu.tar.gz",
        "sha256": "a" * 64,
        "format": "tar",
        "binaries": {"uv": "uv-*/uv", "uvx": "uv-*/uvx"},
    }
    # The prerelease channel reads the newest release from the Atom feed.
    assert latest["no-mistakes"]["version"] == "9.9.10-beta.1"
    # gws and Pyrefly keep their own .sha256 file as the checksum source.
    assert latest["pyrefly"]["assets"]["linux-x86_64"]["sha256"] == "f" * 64


def test_a_rate_limited_api_and_unreadable_pages_still_name_the_token(monkeypatch):
    rate_limited_github(monkeypatch)
    fake = installer.urllib.request.urlopen

    def urlopen(request, **kwargs):
        if request.full_url.startswith("https://github.com/"):
            raise http_error(500)
        return fake(request, **kwargs)

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    with pytest.raises(ValueError, match="set GITHUB_TOKEN"):
        installer.resolve_latest("linux-x86_64", {"uv"})
