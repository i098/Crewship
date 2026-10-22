import configparser
import getpass
import grp
import hashlib
import importlib.util
import io
import json
import os
import runpy
import shutil
import ssl
import subprocess
import sys
import tarfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Barrier, BrokenBarrierError, Event, Thread

import pytest
import yaml

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


@pytest.mark.parametrize(("version", "floor", "passes"), [
    ("22.23.3", "22.23.4", False), ("22.23.4", "22.23.4", True),
    ("24.22.0", "24.22.1", False), ("24.22.1", "24.22.1", True),
    ("26.12.0", "26.12.1", False), ("26.12.1", "26.12.1", True),
    ("26.13.0", "26.12.1", True), ("30.1.0", None, True),
])
def test_node_resolution_enforces_its_major_security_floor(monkeypatch, version, floor, passes):
    def fetch(url, source):
        if url.endswith("index.json"):
            return json.dumps([{"version": "v" + version}]).encode()
        return ("a" * 64 + f"  node-v{version}-linux-x64.tar.xz\n").encode()

    monkeypatch.setattr(installer, "fetch", fetch)
    if passes:
        assert installer.resolve_latest("linux-x86_64", {"node"})["node"]["version"] == version
    else:
        with pytest.raises(ValueError, match=rf"node v{version} is below security minimum {floor}"):
            installer.resolve_latest("linux-x86_64", {"node"})


@pytest.mark.parametrize("version", ["20.99.0", "23.99.0", "26.12.1-rc.1", "invalid"])
def test_node_security_floor_rejects_unsupported_or_unstable_versions(version):
    with pytest.raises(ValueError, match="node.*security minimum"):
        installer.require_secure_node(version)


@pytest.mark.parametrize(("version", "passes"), [
    ("22.23.3", False), ("22.23.4", True),
    ("24.22.0", False), ("24.22.1", True),
    ("26.12.0", False), ("26.12.1", True),
])
def test_node_install_checks_the_executable_version(tmp_path, monkeypatch, version, passes):
    payload = f"#!/bin/sh\nprintf 'v{version}\\n'\n".encode()
    spec = asset(payload)
    spec["version"] = "26.12.1"
    spec["assets"]["linux-x86_64"]["binaries"] = {"node": "node"}
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Download(payload))
    if passes:
        assert installer.install_asset(tmp_path, "node", spec, "linux-x86_64")
    else:
        with pytest.raises(ValueError, match="node.*below security minimum"):
            installer.install_asset(tmp_path, "node", spec, "linux-x86_64")
        assert not (tmp_path / ".local/bin/node").exists()


def security_wheel(directory, name, version, dependencies=(), console=False):
    dist_info = f"{name}-{version}.dist-info"
    files = {
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {dependency}\n" for dependency in dependencies)
        ),
        f"{dist_info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{name}/__init__.py": (
            f"def main():\n    print('{name} {version}')\n" if console else ""
        ),
    }
    if console:
        files[f"{dist_info}/entry_points.txt"] = f"[console_scripts]\n{name} = {name}:main\n"
    files[f"{dist_info}/RECORD"] = "".join(f"{path},,\n" for path in files)
    wheel = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return wheel


@pytest.fixture
def python_security_index(tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    for name, versions in {
        "pip": ("26.2.1", "26.2.2", "26.3.0"),
        "certifi": ("2026.10.18", "2026.10.19", "2026.11.1"),
    }.items():
        for version in versions:
            security_wheel(wheels, name, version)
    environment = {
        **os.environ, "UV_NO_CONFIG": "1", "UV_NO_INDEX": "1", "UV_OFFLINE": "1",
        "UV_FIND_LINKS": str(wheels), "UV_CACHE_DIR": str(tmp_path / "cache"),
        "UV_TOOL_DIR": str(tmp_path / "tools"), "UV_PYTHON_DOWNLOADS": "never",
        "UV_PYTHON": str(Path(sys.executable).resolve()), "UV_NO_PROJECT": "1",
    }
    environment.pop("VIRTUAL_ENV", None)
    environment.pop("PYTHONPATH", None)
    return Path(shutil.which("uv")), environment, wheels


@pytest.mark.parametrize("installed", [
    {}, {"pip": "26.2.1"}, {"certifi": "2026.10.18"},
    {"pip": "26.2.1", "certifi": "2026.10.18"},
    {"pip": "26.2.2", "certifi": "2026.11.1"},
])
def test_python_security_updates_only_present_packages(tmp_path, python_security_index, installed):
    uv, environment, _ = python_security_index
    managed = tmp_path / ".local/bin"
    managed.mkdir(parents=True)
    (managed / "uv").symlink_to(uv)
    other = tmp_path / "other-bin"
    other.mkdir()
    (other / "uv").write_text("#!/bin/sh\nexit 99\n")
    (other / "uv").chmod(0o755)
    environment["PATH"] = f"{other}{os.pathsep}{environment['PATH']}"
    python = tmp_path / "venv/bin/python"
    subprocess.run([uv, "venv", "--python", sys.executable, python.parent.parent],
                   env=environment, check=True, capture_output=True)
    if installed:
        subprocess.run(
            [uv, "pip", "install", "--python", python,
             *(f"{name}=={version}" for name, version in installed.items())],
            env=environment, check=True, capture_output=True,
        )
    result = subprocess.run(
        [sys.executable, SPEC.origin, "--home", tmp_path, "--python-env", python],
        env=environment, check=True, capture_output=True, text=True,
    )
    expected = {
        name: {"pip": "26.3.0", "certifi": "2026.11.1"}[name]
        if version in ("26.2.1", "2026.10.18") else version
        for name, version in installed.items()
    }
    actual = json.loads(subprocess.check_output(
        [python, "-c", "import importlib.metadata as m, json; "
         "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}))"],
        env=environment,
    ))
    assert actual == expected
    assert json.loads(result.stdout)["changed"] == (installed != expected)
    assert not installer.secure_python(python, uv, environment)


def test_python_security_reports_upgrade_with_inherited_metadata(tmp_path, python_security_index):
    uv, environment, wheels = python_security_index
    inherited = tmp_path / "inherited"
    subprocess.run(
        [uv, "pip", "install", "--target", inherited, wheels / "certifi-2026.10.18-py3-none-any.whl"],
        env=environment, check=True, capture_output=True,
    )
    python = tmp_path / "venv/bin/python"
    subprocess.run(
        [uv, "venv", "--system-site-packages", "--python", sys.executable, python.parent.parent],
        env=environment, check=True, capture_output=True,
    )
    site = subprocess.check_output(
        [python, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        env=environment, text=True,
    ).strip()
    (Path(site) / "inherited.pth").write_text(str(inherited) + "\n")
    assert installer.secure_python(python, uv, environment)
    assert subprocess.check_output(
        [python, "-I", "-c", "import importlib.metadata as m; print(m.version('certifi'))"],
        env=environment, text=True,
    ).strip() == "2026.11.1"
    assert not installer.secure_python(python, uv, environment)


@pytest.mark.parametrize("corrupt", [False, True])
def test_native_installs_overlap_and_keep_checksum_failures_fatal(tmp_path, monkeypatch, capsys, corrupt):
    key = "linux-x86_64"
    payloads = {
        name: f"#!/bin/sh\nprintf '{name} 1.0.0\\n'\n".encode()
        for name in ("first", "second")
    }
    latest = {name: asset(payload) for name, payload in payloads.items()}
    for name, spec in latest.items():
        spec["assets"][key]["url"] = f"https://downloads.example.test/{name}"
        spec["assets"][key]["binaries"] = {name: name}
    barrier = Barrier(2, timeout=5)

    def source(url, **kwargs):
        name = url.rsplit("/", 1)[1]
        barrier.wait()
        payload = b"corrupt" if corrupt and name == "second" else payloads[name]
        return Download(payload, url)

    monkeypatch.setattr(installer.urllib.request, "urlopen", source)
    monkeypatch.setattr(installer, "platform_key", lambda: key)
    monkeypatch.setattr(
        sys, "argv",
        ["provisions.py", "--home", str(tmp_path), "--tools", "first,second,first",
         "--resolved", json.dumps(latest)],
    )
    if corrupt:
        with pytest.raises(ValueError, match="checksum mismatch"):
            installer.main()
        assert not os.path.lexists(tmp_path / ".local/bin/second")
    else:
        installer.main()
        assert json.loads(capsys.readouterr().out)["changed"]
        assert subprocess.check_output([tmp_path / ".local/bin/second"], text=True).strip() == "second 1.0.0"
        installer.main()
        assert not json.loads(capsys.readouterr().out)["changed"]
    assert subprocess.check_output([tmp_path / ".local/bin/first"], text=True).strip() == "first 1.0.0"


def test_parallel_download_progress_keeps_separate_lines(tmp_path, monkeypatch):
    barrier = Barrier(2, timeout=1)

    class SlowStderr(io.StringIO):
        def write(self, text):
            written = super().write(text)
            if text.startswith("Downloading "):
                try:
                    barrier.wait()
                except BrokenBarrierError:
                    pass
            return written

    progress = SlowStderr()
    payload = b"verified download"
    checksum = hashlib.sha256(payload).hexdigest()
    urls = [f"https://downloads.example.test/{name}" for name in ("first", "second")]
    monkeypatch.setattr(sys, "stderr", progress)
    monkeypatch.setattr(
        installer.urllib.request, "urlopen",
        lambda url, **kwargs: Download(payload, url),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            pool.submit(installer.download, url, checksum, tmp_path / str(index))
            for index, url in enumerate(urls)
        ]
        for result in results:
            result.result()

    assert sorted(progress.getvalue().splitlines()) == sorted(
        f"Downloading {url}" for url in urls
    )


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

    replies[:] = [installer.urllib.error.URLError("reset") for _ in range(3)]
    url = "https://nodejs.org/dist/index.json"
    with pytest.raises(ValueError) as failure:
        installer.fetch(url, "node release")
    assert url in str(failure.value)
    assert "after 3 attempt(s)" in str(failure.value)
    assert replies == []


@pytest.mark.parametrize(
    ("tool", "package"),
    [("acpx", "acpx"), ("omp", "@oh-my-pi/pi-coding-agent"), ("spectrum-ts", "spectrum-ts")],
)
@pytest.mark.parametrize(
    ("latest_status", "fallback_stalls"),
    [(None, False), (None, True), (504, False), (404, False), (200, False)],
)
def test_npm_lookup_bounds_stalls_and_uses_the_latest_tag(
    monkeypatch, tool, package, latest_status, fallback_stalls
):
    stopped = Event()
    seen = []
    timeouts = []
    base = f"https://registry.npmjs.org/{package}"

    class Registry(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            latest = self.path.endswith("/latest")
            status = latest_status if latest else None if fallback_stalls else 200
            if status is None:
                stopped.wait(5)
                return
            self.send_response(status)
            self.end_headers()
            body = {"version": "1.0.0"} if latest else {
                "dist-tags": {"latest": "2.0.0"},
                "versions": {"2.0.0": {"version": "2.0.0"}, "3.0.0": {"version": "3.0.0"}},
            }
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    real_urlopen = installer.urllib.request.urlopen
    with ThreadingHTTPServer(("127.0.0.1", 0), Registry) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def local_urlopen(request, *, timeout):
            assert request.full_url in (base, base + "/latest")
            timeouts.append(timeout)
            return real_urlopen(
                f"http://127.0.0.1:{server.server_port}" + request.full_url.removeprefix(
                    "https://registry.npmjs.org"
                ),
                timeout=min(timeout, 0.1),
            )

        monkeypatch.setattr(installer.urllib.request, "urlopen", local_urlopen)
        monkeypatch.setattr(installer.time, "sleep", lambda seconds: None)
        started = installer.time.monotonic()
        try:
            if fallback_stalls or latest_status == 404:
                with pytest.raises(ValueError) as failure:
                    installer.resolve_latest("linux-x86_64", {tool})
                final_url = base if fallback_stalls else base + "/latest"
                assert final_url in str(failure.value)
                assert f"after {2 if fallback_stalls else 1} attempt" in str(failure.value)
            else:
                version = "1.0.0" if latest_status == 200 else "2.0.0"
                assert installer.resolve_latest("linux-x86_64", {tool}) == {tool: version}
            assert installer.time.monotonic() - started < 2
            assert all(timeout <= 10 for timeout in timeouts)
            paths = [f"/{package}/latest"]
            if latest_status not in (200, 404):
                paths.append(f"/{package}")
            assert seen == paths
        finally:
            stopped.set()
            server.shutdown()
            thread.join()


@pytest.mark.parametrize(
    ("source", "fallback"),
    [("fetch_page", False), ("fetch", False), ("npm", False), ("npm", True)],
)
def test_incomplete_metadata_read_reports_context_without_retry(monkeypatch, source, fallback):
    base = "https://registry.npmjs.org/acpx"
    seen = []

    class Registry(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            if fallback and self.path.endswith("/latest"):
                self.send_response(504)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b'{"version": "1.0.0"}')

        def log_message(self, *args):
            pass

    real_urlopen = installer.urllib.request.urlopen
    with ThreadingHTTPServer(("127.0.0.1", 0), Registry) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def local_urlopen(request, *, timeout):
            path = installer.urllib.parse.urlsplit(request.full_url).path
            return real_urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=timeout)

        monkeypatch.setattr(installer.urllib.request, "urlopen", local_urlopen)
        try:
            with pytest.raises(ValueError) as failure:
                if source == "npm":
                    installer.resolve_latest("linux-x86_64", {"acpx"})
                else:
                    getattr(installer, source)(base + "/latest", "test release")
            final_url = base if fallback else base + "/latest"
            assert final_url in str(failure.value)
            assert f"after {2 if fallback else 1} attempt(s)" in str(failure.value)
            assert isinstance(failure.value.__cause__, IncompleteRead)
            assert seen == (["/acpx/latest", "/acpx"] if fallback else ["/acpx/latest"])
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize(
    ("fallback", "body", "cause"),
    [
        (False, b'{"version":', json.JSONDecodeError),
        (True, b'{"dist-tags":', json.JSONDecodeError),
        (False, b"{}", KeyError),
        (True, b"{}", KeyError),
        (True, b'{"versions": {}}', KeyError),
        (True, b'{"versions": {}, "dist-tags": {}}', KeyError),
        (True, b'{"versions": {}, "dist-tags": {"latest": "2.0.0"}}', KeyError),
        (True, b'{"versions": {"2.0.0": {}}, "dist-tags": {"latest": "2.0.0"}}', KeyError),
    ],
)
def test_invalid_npm_metadata_reports_context_without_retry(monkeypatch, fallback, body, cause):
    base = "https://registry.npmjs.org/acpx"
    seen = []

    def urlopen(request, *, timeout):
        seen.append(request.full_url)
        if fallback and request.full_url.endswith("/latest"):
            raise http_error(504)
        return Download(body)

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    with pytest.raises(ValueError) as failure:
        installer.resolve_latest("linux-x86_64", {"acpx"})
    final_url = base if fallback else base + "/latest"
    assert final_url in str(failure.value)
    assert f"after {2 if fallback else 1} attempt(s)" in str(failure.value)
    assert isinstance(failure.value.__cause__, cause)
    assert seen == ([base + "/latest", base] if fallback else [base + "/latest"])


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

def test_release_lookups_overlap_and_share_one_result_per_repository_per_apply(monkeypatch):
    seen = []
    upstream(monkeypatch, seen=seen)
    source = installer.urllib.request.urlopen
    barrier = Barrier(2, timeout=5)

    def urlopen(request, **kwargs):
        barrier.wait()
        return source(request, **kwargs)

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    for _ in range(2):
        latest = installer.resolve_latest("linux-x86_64", {"sentrux", "sentrux-grammars", "uv"})
        assert latest["sentrux"]["version"] == latest["sentrux-grammars"]["version"] == "9.9.9"
        assert latest["uv"]["assets"]["linux-x86_64"]["sha256"] == "a" * 64
    assert [url for url, _ in seen].count(
        "https://api.github.com/repos/sentrux/sentrux/releases/latest"
    ) == 2
    assert [url for url, _ in seen].count(
        "https://api.github.com/repos/astral-sh/uv/releases/latest"
    ) == 2



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


def forgejo_host(tmp_path):
    """A home with the Forgejo secrets, units directories and a stopped Tailscale."""
    home, stubs = tmp_path / "home", tmp_path / "bin"
    conf, units = home / ".config/crewship/forgejo", home / ".config/systemd/user"
    for directory in (conf, units, stubs):
        directory.mkdir(parents=True)
    for name in ("secret-key", "internal-token", "jwt-secret"):
        (conf / name).write_text("s3cret-value\n")
    (stubs / "tailscale").write_text("#!/bin/sh\nexit 1\n")
    (stubs / "tailscale").chmod(0o755)
    return home, conf, units, stubs


def apply_forgejo(tmp_path, crewship, **extra):
    """Run tasks/forgejo.yml with Forgejo 2.0.0 and tmp_path/bin first on PATH."""
    (tmp_path / "templates").symlink_to(Path(__file__).parents[1] / "blueprint/ansible/templates")
    ansible = Path(__file__).parents[1] / "blueprint/ansible"
    playbook = tmp_path / "forgejo.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars_files": [str(f) for f in sorted((ansible / "group_vars/all").glob("*.yml"))],
        "tasks": [{"ansible.builtin.import_tasks": str(ansible / "tasks/forgejo.yml")}],
        "handlers": [{"name": name, "ansible.builtin.debug": {"msg": name}}
                     for name in ("reload user systemd", "no-mistakes daemon restart required")],
    }]))
    variables = {
        "crewship_repo": str(ansible.parents[1]), "crewship_blueprint": str(ansible.parent),
        "ansible_become": False,
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_platform": "linux-x86_64",
        "crewship_local_bin": str(tmp_path / "bin"),
        "crewship_user_uid": os.getuid(),
        "crewship_latest": {"forgejo": {"version": "2.0.0", "assets": {}}},
        "crewship": {"user": getpass.getuser(), "home": str(tmp_path / "home"), **crewship},
        **extra,
    }
    return subprocess.run(
        [Path(sys.executable).parent / "ansible-playbook", "-i", "localhost,", str(playbook),
         "--extra-vars", json.dumps(variables)],
        cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}"},
    )


def test_a_failed_dump_with_the_installed_forgejo_stops_the_upgrade_before_its_units_change(tmp_path):
    home, conf, units, stubs = forgejo_host(tmp_path)
    log = tmp_path / "calls"
    old = home / ".local/share/crewship/forgejo/1.0.0/forgejo"
    new = home / ".local/share/crewship/forgejo/2.0.0/forgejo"
    for directory in (old.parent, new.parent):
        directory.mkdir(parents=True)
    installed = {"forgejo.service": f"[Service]\nExecStart={old} web\n",
                 "forgejo-dump.service": f"[Service]\nExecStart={old} dump\n"}
    for name, text in installed.items():
        (units / name).write_text(text)
    # The service is stopped; systemctl start runs the installed dump unit's command.
    for path, body in (
        (old, f'echo "old $*" >> {log}; exit 1'),
        (new, f'echo "new $*" >> {log}'),
        (stubs / "systemctl", f'echo "systemctl $*" >> {log}\n'
         f'[ "$*" = "--user start forgejo-dump.service" ] || exit 0\n'
         f'exec $(sed -n "s/^ExecStart=//p" {units}/forgejo-dump.service)'),
    ):
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
    result = apply_forgejo(tmp_path, {"start_services": True, "profiles": {"forgejo": True}})
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "rescued=1" in result.stdout, output
    assert "s3cret-value" not in output
    # The old release dumped; Forgejo keeps it: no new units, configuration or restart.
    assert {name: (units / name).read_text() for name in installed} == installed
    assert not (conf / "app.ini").exists()
    calls = log.read_text()
    assert "old dump" in calls, calls
    assert "restart" not in calls and "new" not in calls, calls
    # `forgejo dump` fails until this directory exists, and Forgejo makes it only with a repository.
    assert (home / ".local/share/forgejo/data/forgejo-repositories").is_dir()


@pytest.mark.parametrize(
    ("installed", "port", "expected"),
    [
        # Tailscale is down: the installed tailnet URL stays.
        ("https://host.tail.ts.net:20250/", 20250, "https://host.tail.ts.net:20250/"),
        # A first install without Tailscale uses the loopback URL.
        (None, 20250, "http://127.0.0.1:20250/"),
        # A loopback URL follows a new port.
        ("http://127.0.0.1:20250/", 20251, "http://127.0.0.1:20251/"),
    ],
)
def test_forgejo_root_url_without_tailscale(tmp_path, installed, port, expected):
    home, conf, units, stubs = forgejo_host(tmp_path)
    binary = home / ".local/share/crewship/forgejo/2.0.0/forgejo"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    (units / "no-mistakes-daemon-.service.d").mkdir()
    if installed:
        (conf / "app.ini").write_text(f"[server]\nROOT_URL = {installed}\n")
    result = apply_forgejo(
        tmp_path,
        {"start_services": False, "profiles": {"forgejo": True, "agents": True}},
        crewship_forgejo_port=port,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    app = configparser.ConfigParser(interpolation=None)
    app.read_string("[root]\n" + (conf / "app.ini").read_text())
    assert app["server"]["ROOT_URL"] == expected
    dropin = configparser.ConfigParser(interpolation=None)
    dropin.read_string((units / "no-mistakes-daemon-.service.d/forgejo.conf").read_text())
    assert dropin["Service"]["Environment"] == f'"FORGEJO_BASE_URL={expected.rstrip("/")}"'


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


@pytest.mark.parametrize("releases", [[], [{"tag_name": "v9.9.11", "draft": True, "assets": []}]])
def test_a_release_list_without_published_releases_uses_public_pages(monkeypatch, releases):
    rate_limited_github(monkeypatch)
    pages = installer.urllib.request.urlopen

    def urlopen(request, **kwargs):
        if request.full_url.startswith("https://api.github.com/"):
            return Download(json.dumps(releases).encode())
        return pages(request, **kwargs)

    monkeypatch.setattr(installer.urllib.request, "urlopen", urlopen)
    latest = installer.resolve_latest("linux-x86_64", {"no-mistakes"})
    assert latest["no-mistakes"]["version"] == "9.9.10-beta.1"
    assert latest["no-mistakes"]["assets"]["linux-x86_64"]["sha256"] == "a" * 64


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
        (["--tools", "uv", "--sgrep"], {"uv", "rustup-init"}),
        (["--tools", "uv", "--npm"], {"uv", *installer.AGENT_TOOLS, *installer.NPM_LATEST}),
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


@pytest.mark.parametrize("registry_mode", (
    "current", "malformed", "future", "relocated",
    ".env", ".env.local", ".env.development", ".env.development.local",
    ".env.production", ".env.production.local", ".omp/.env", ".omp/agent/.env",
))
def test_plugin_catalogs_are_fetched_once_per_apply_and_existing_plugins_upgrade(
    tmp_path, registry_mode
):
    omp = tmp_path / ".local/bin/omp"
    omp.parent.mkdir(parents=True)
    state_file = tmp_path / "marketplace-state.json"
    state_file.write_text(json.dumps({"remote": 1, "catalogs": {}, "plugins": {}, "downloads": {}}))
    omp.write_text(
        f"#!{sys.executable}\n"
        """import json
import sys
from pathlib import Path

home = Path.home()
state_file = home / "marketplace-state.json"
state = json.loads(state_file.read_text())
args = sys.argv[2:]

def fetch(name):
    state["catalogs"][name] = state["remote"]
    state["downloads"][name] = state["downloads"].get(name, 0) + 1

if args == ["list", "--json"]:
    print(json.dumps({"marketplace": [{"id": name} for name in state["plugins"]]}))
elif args[:2] == ["marketplace", "add"]:
    name = args[2].split("/")[-1]
    fetch(name)
    registry = home / ".omp/marketplaces.json"
    registry.parent.mkdir(exist_ok=True)
    known = json.loads(registry.read_text()) if registry.exists() else []
    registry.write_text(json.dumps([*known, args[2]]))
elif args == ["marketplace", "update"]:
    for name in state["catalogs"]:
        fetch(name)
elif args[0] == "install":
    state["plugins"][args[1]] = state["catalogs"][args[1].split("@")[1]]
elif args == ["upgrade"]:
    updated = {name: state["catalogs"][name.split("@")[1]] for name in state["plugins"]}
    print("up to date" if updated == state["plugins"] else "upgraded")
    state["plugins"] = updated
else:
    raise SystemExit(1)
state_file.write_text(json.dumps(state))
registry = home / ".omp/plugins/installed_plugins.json"
registry.parent.mkdir(parents=True, exist_ok=True)
registry.write_text(json.dumps({
    "version": 2,
    "plugins": {name: [{"version": str(version)}] for name, version in state["plugins"].items()},
}))
"""
    )
    omp.chmod(0o755)
    environment = {"HOME": str(tmp_path)}
    assert installer.omp_plugins(tmp_path, environment)
    state = json.loads(state_file.read_text())
    assert state["plugins"] == {f"{name}@{name}": 1 for name in installer.OMP_PLUGINS}
    assert state["downloads"] == {name: 1 for name in installer.OMP_PLUGINS}

    state["remote"] = 2
    del state["plugins"]["ponytail@ponytail"]
    registry = tmp_path / ".omp/plugins/installed_plugins.json"
    saved = json.loads(registry.read_text())
    if registry_mode == "current":
        del saved["plugins"]["ponytail@ponytail"]
    elif registry_mode == "future":
        saved["version"] = 3
    elif registry_mode == "relocated":
        environment["XDG_DATA_HOME"] = str(tmp_path / "data")
    elif registry_mode != "malformed":
        dotenv = tmp_path / registry_mode
        dotenv.parent.mkdir(parents=True, exist_ok=True)
        dotenv.write_text(f"XDG_DATA_HOME={tmp_path / 'data'}\n")
        if "production" in registry_mode:
            environment["NODE_ENV"] = "production"
        state["plugins"] = {}
    registry.write_text("invalid JSON" if registry_mode == "malformed" else json.dumps(saved))
    state_file.write_text(json.dumps(state))
    assert installer.omp_plugins(tmp_path, environment)
    state = json.loads(state_file.read_text())
    assert state["plugins"] == {f"{name}@{name}": 2 for name in installer.OMP_PLUGINS}
    assert state["downloads"] == {name: 2 for name in installer.OMP_PLUGINS}


@pytest.mark.parametrize("failed", [False, True])
def test_concurrent_bun_logs_stay_together_and_failed_output_is_kept(
    monkeypatch, tmp_path, capfd, failed
):
    bun = tmp_path / ".local/bin/bun"
    bun.parent.mkdir(parents=True)
    bun.write_text(
        f"#!{sys.executable}\n"
        """import json
import os
from pathlib import Path
import sys
import time

name, version = sys.argv[-1].rsplit("@", 1)
home = Path.home()
print(f"{name}:start", flush=True)
(home / name).touch()
deadline = time.monotonic() + 5
while not all((home / tool).exists() for tool in ("first", "second")):
    if time.monotonic() > deadline:
        raise SystemExit("the other install did not start")
    time.sleep(0.01)
print(f"{name}:end", flush=True)
if name == "second" and os.environ.get("FAIL"):
    raise SystemExit(3)
package = Path(os.environ["BUN_INSTALL_GLOBAL_DIR"]) / "node_modules" / name
package.mkdir(parents=True)
(package / "package.json").write_text(json.dumps({"version": version}))
"""
    )
    bun.chmod(0o755)
    monkeypatch.setattr(installer, "NPM_LATEST", {"first": "first", "second": "second"})
    environment = {"HOME": str(tmp_path), "FAIL": "yes" if failed else ""}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(installer.bun_latest_install, tmp_path, "first", "1.0.0", environment)
        second = pool.submit(installer.bun_latest_install, tmp_path, "second", "1.0.0", environment)
        assert first.result()
        if failed:
            with pytest.raises(subprocess.CalledProcessError) as error:
                second.result()
            assert "second:end" in error.value.output
            assert not (tmp_path / ".local/share/crewship/second/1.0.0").exists()
        else:
            assert second.result()
    lines = capfd.readouterr().err.splitlines()
    for tool in ("first", "second"):
        assert lines.index(f"{tool}:end") == lines.index(f"{tool}:start") + 1


@pytest.mark.parametrize("failed", [False, True])
def test_package_installs_overlap_and_failures_prevent_success(
    monkeypatch, tmp_path, capsys, failed
):
    packages = {"first": "first", "second": "second"}
    ready = Barrier(2, timeout=5)

    def install(home, tool, version, environment):
        ready.wait()
        if failed and tool == "second":
            raise ValueError("package download failed")
        (home / tool).write_text(version)
        return True

    monkeypatch.setattr(installer, "NPM_LATEST", packages)
    monkeypatch.setattr(installer, "AGENT_TOOLS", [])
    monkeypatch.setattr(installer, "install_asset", lambda *args: False)
    monkeypatch.setattr(installer, "bun_latest_install", install)
    monkeypatch.setattr(installer, "omp_plugins", lambda *args: False)
    resolved = {"uv": {}, "first": "1.0.0", "second": "1.0.0"}
    monkeypatch.setattr(
        installer.sys, "argv",
        ["provisions.py", "--home", str(tmp_path), "--tools", "uv", "--npm",
         "--resolved", json.dumps(resolved)],
    )
    if failed:
        with pytest.raises(ValueError, match="package download failed"):
            installer.main()
        assert not (tmp_path / ".local/share/crewship/resolved.json").exists()
        assert capsys.readouterr().out == ""
    else:
        installer.main()
        assert json.loads(capsys.readouterr().out)["changed"]
        assert {tool: (tmp_path / tool).read_text() for tool in packages} == {
            "first": "1.0.0", "second": "1.0.0"
        }



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


@pytest.mark.parametrize("resolution", ["highest", "lowest"])
def test_fdu_installs_with_uv_into_the_account_bin_and_reports_change_only_on_a_new_version(
    tmp_path, python_security_index, resolution,
):
    uv, environment, wheels = python_security_index
    environment["UV_RESOLUTION"] = resolution
    bin_dir = tmp_path / ".local/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "uv").symlink_to(uv)
    security_wheel(wheels, "fdu", "0.5.0", ("certifi>=2026.10.18",), console=True)
    assert installer.fdu_install(tmp_path, environment) is True
    assert subprocess.check_output([bin_dir / "fdu"], text=True) == "fdu 0.5.0\n"
    assert installer.fdu_install(tmp_path, environment) is False
    security_wheel(wheels, "fdu", "0.6.0", ("certifi>=2026.10.18",), console=True)
    assert installer.fdu_install(tmp_path, environment) is True
    assert subprocess.check_output([bin_dir / "fdu"], text=True) == "fdu 0.6.0\n"
    python = tmp_path / "tools/fdu/bin/python"
    assert json.loads(subprocess.check_output(
        [python, "-c", "import importlib.metadata as m, json; "
         "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions()}))"],
        env=environment,
    )) == {"fdu": "0.6.0", "certifi": "2026.11.1"}


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


def test_sgrep_builds_from_git_links_warms_both_models_and_reports_change_only_on_a_new_build(tmp_path):
    cargo_bin = tmp_path / ".cargo/bin"
    cargo_bin.mkdir(parents=True)
    log, release = tmp_path / "log", tmp_path / "release"
    release.write_text("1")
    for build in ("1", "2"):
        (tmp_path / f"build{build}").write_text(f'#!/bin/sh\necho "sgrep $*" >> {log}\n# {build}\n')
    cargo = cargo_bin / "cargo"
    cargo.write_text(
        f'#!/bin/sh\necho "cargo $*" >> {log}\n'
        f'cp {tmp_path}/build"$(cat {release})" {cargo_bin}/sgrep\nchmod +x {cargo_bin}/sgrep\n'
    )
    cargo.chmod(0o755)
    environment = {"PATH": "/usr/bin:/bin"}
    assert installer.sgrep_install(tmp_path, environment) is True
    assert (tmp_path / ".local/bin/sgrep").resolve() == cargo_bin / "sgrep"
    lines = log.read_text().splitlines()
    assert lines[0] == f"cargo install --git {installer.SGREP_REPOSITORY} --locked"
    assert [line.split()[line.split().index("--model") + 1] for line in lines[1:]] == ["code", "text"]
    assert installer.sgrep_install(tmp_path, environment) is False
    release.write_text("2")
    assert installer.sgrep_install(tmp_path, environment) is True
