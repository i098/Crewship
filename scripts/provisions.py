#!/usr/bin/env python3
"""Install public tools into a user-owned Crewship prefix.

Stdlib-only: also bootstraps uv before repository dependencies exist. stdout is
one JSON result; installer progress goes to stderr. Existing unmanaged commands
are never replaced. Archives cannot write outside their staging directory.
Nothing is pinned: every tool tracks its latest release (no-mistakes its newest
non-draft one, prereleases included). Native assets are
verified against the SHA-256 their publisher lists for that exact release (the
GitHub release-asset digest, or the release's own .sha256 file for gws and Pyrefly, Node's
SHASUMS256.txt, rustup's .sha256, Forgejo's .sha256 on Codeberg), npm-registry tools (installed by bun)
against the integrity the registry records for the resolved version, psutil against the
digests PyPI publishes. The Rust toolchain follows the stable channel. The omp
marketplace plugins and sgrep (built by cargo from its default branch, crates locked by
its Cargo.lock) are the exceptions: no publisher checksums them, so they
track each author's default branch.
"""

import argparse
import fcntl
import hashlib
import html
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from threading import Lock

GITHUB_API = "https://api.github.com/repos/{}/releases"
FORGEJO_RELEASES = (
    "https://codeberg.org/api/v1/repos/forgejo/forgejo/releases?draft=false&pre-release=false"
)
# How release asset names spell each platform.
ARCH = {
    "linux-x86_64": {
        "node": "x64",
        "go": "amd64",
        "bun": "x64-baseline",
        "gnu": "x86_64",
        "goreleaser": "x86_64",
        "nvim": "x86_64",
    },
    "linux-aarch64": {
        "node": "arm64",
        "go": "arm64",
        "bun": "aarch64",
        "gnu": "aarch64",
        "goreleaser": "arm64",
        "nvim": "arm64",
    },
}
# Native tools on their latest GitHub release: repository, tag prefix, asset
# name, and where each command sits inside the asset.
GITHUB_LATEST = {
    "herdr": ("herdrdev/herdr", "v", "herdr-{key}", {"herdr": "herdr"}),
    "bun": ("oven-sh/bun", "bun-v", "bun-linux-{bun}.zip", {"bun": "bun-linux-*/bun"}),
    "gh": ("cli/cli", "v", "gh_{v}_linux_{go}.tar.gz", {"gh": "gh_*/bin/gh"}),
    "nvim": (
        "neovim/neovim",
        "v",
        "nvim-linux-{nvim}.tar.gz",
        {"nvim": "nvim-linux-*/bin/nvim"},
    ),
    "no-mistakes": (
        "kunchenguid/no-mistakes",
        "v",
        "no-mistakes-v{v}-linux-{go}.tar.gz",
        {"no-mistakes": "no-mistakes"},
    ),
    "treehouse": (
        "kunchenguid/treehouse",
        "v",
        "treehouse-v{v}-linux-{go}.tar.gz",
        {"treehouse": "treehouse"},
    ),
    "uv": (
        "astral-sh/uv",
        "",
        "uv-{gnu}-unknown-linux-gnu.tar.gz",
        {"uv": "uv-*/uv", "uvx": "uv-*/uvx"},
    ),
    # Linked as btop-bin: ~/.local/bin/btop is the launcher that fits it to the
    # pane (blueprint/maintenance/btop.sh, installed by blueprint/ansible/tasks/herdr.yml).
    "btop": (
        "aristocratos/btop",
        "v",
        "btop-{gnu}-unknown-linux-musl.tar.gz",
        {"btop-bin": "btop/bin/btop"},
    ),
    "sentrux": ("sentrux/sentrux", "v", "sentrux-{key}", {"sentrux": "sentrux"}),
    # The grammars of the same sentrux release. sentrux downloads them itself,
    # unverified, when ~/.sentrux/plugins lacks them; link_grammars puts them there.
    "sentrux-grammars": ("sentrux/sentrux", "v", "grammars-{key}.tar.gz", {}),
    # JS/TS changed-code health for the omp quality gate (docs/omp.md#quality-gate).
    "fallow": ("fallow-rs/fallow", "v", "fallow-linux-{node}-musl", {"fallow": "fallow"}),
    # Quick Tunnel to the password gateway (docs/gateway.md); a single binary per release.
    "cloudflared": ("cloudflare/cloudflared", "", "cloudflared-linux-{go}", {"cloudflared": "cloudflared"}),
    # Python type checker and language server for every host.
    "pyrefly": (
        "facebook/pyrefly",
        "",
        "pyrefly-linux-{goreleaser}-musl.tar.gz",
        {"pyrefly": "pyrefly"},
    ),
    # Terminal chat clients for the chat profile (docs/chat.md).
    "concord": (
        "chojs23/concord",
        "v",
        "concord-{gnu}-unknown-linux-gnu.tar.xz",
        {"concord": "concord-*/concord"},
    ),
    "slk": ("gammons/slk", "v", "slk_{v}_linux_{goreleaser}.tar.gz", {"slk": "slk"}),
    # Resolved for the fleet browser ladder (blueprint/ansible/tasks/fleet-browsers.yml), not installed here.
    "obscura": (
        "h4ckf0r0day/obscura",
        "v",
        "obscura-{gnu}-linux.tar.gz",
        {"obscura": "obscura", "obscura-worker": "obscura-worker"},
    ),
    # Resolved for host hardening (blueprint/ansible/tasks/koncreet.yml), installed there as root.
    "koncreet": ("jimididit/koncreet", "v", "koncreet.tar.gz", {"koncreet": "koncreet/koncreet"}),
    # Jujutsu for the opt-in jj profile (docs/jj.md); one static musl binary per release.
    "jj": (
        "jj-vcs/jj",
        "v",
        "jj-v{v}-{gnu}-unknown-linux-musl.tar.gz",
        {"jj": "jj"},
    ),
    # Google Workspace CLI, verified against the .sha256 file the release publishes.
    "gws": (
        "googleworkspace/cli",
        "v",
        "google-workspace-cli-{gnu}-unknown-linux-musl.tar.gz",
        {"gws": "gws"},
    ),
}
# Resolved when they can be, skipped with a warning when they cannot: they never stop a run.
OPTIONAL = {"koncreet"}
# Verified against the `<asset>.sha256` file of the release instead of the GitHub digest.
SHA256_FILE = {"gws", "pyrefly"}
# npm-registry tools on the registry's latest version, each installed by bun into its own prefix.
NPM_LATEST = {
    "omp": "@oh-my-pi/pi-coding-agent",
    "chrome-devtools-axi": "chrome-devtools-axi",
    "gh-axi": "gh-axi",
    "lavish-axi": "lavish-axi",
    "quota-axi": "quota-axi",
    "tasks-axi": "tasks-axi",
    "acpx": "acpx",
    "chrome-devtools-mcp": "chrome-devtools-mcp",
    "forgejo-axi": "forgejo-axi",
    "ondine": "ondine",
}
# Tools that follow the prerelease channel: the newest non-draft release, betas
# included, instead of the latest stable one.
PRERELEASE_CHANNEL = {"no-mistakes"}
AGENT_TOOLS = ["bun", "gh", "no-mistakes", "treehouse", "gws"]
# Attempts per download; transient 5xx and connection errors back off 1 s, then 2 s.
DOWNLOAD_ATTEMPTS = 3
SGREP_REPOSITORY = "https://github.com/context-dot-dev/sgrep"
# One extension per language sgrep parses with Tree-sitter (its README).
SGREP_LANGUAGES = ("py", "c", "cpp", "cs", "go", "java", "rs", "js", "jsx", "ts", "tsx")
INSTALL_OUTPUT_LOCK = Lock()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def platform_key():
    machine = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(
        platform.machine().lower()
    )
    if platform.system() != "Linux" or machine is None:
        raise ValueError(
            "native provisioning supports Linux x86_64/aarch64; other devices can use SSH Herdr clients"
        )
    return "linux-" + machine


class RateLimited(ValueError):
    """The GitHub API refused a lookup for the request budget (HTTP 403 or 429)."""


def fetch_page(url, what):
    """The final URL after redirects, and the body."""
    # The GitHub token only ever goes to the GitHub API. Unauthenticated calls
    # there share a 60/hour budget per IP.
    token = os.environ.get("GITHUB_TOKEN")
    github = url.startswith("https://api.github.com/")
    headers = {"Authorization": f"Bearer {token}"} if token and github else {}
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=60
            ) as response:
                return response.geturl(), response.read()
        except OSError as error:
            # Connection resets, TLS EOFs, timeouts and 5xx are transient; a 4xx is final.
            status = getattr(error, "code", 500)
            if status < 500 or attempt == DOWNLOAD_ATTEMPTS:
                if isinstance(error, urllib.error.HTTPError):
                    failure = RateLimited if github and status in (403, 429) else ValueError
                    raise failure(
                        f"cannot resolve the latest {what} (HTTP {error.code}); "
                        "if rate limited, set GITHUB_TOKEN and re-run"
                    ) from None
                raise
            time.sleep(attempt)


def fetch(url, what):
    return fetch_page(url, what)[1]


def release_from_pages(repo, tool, prerelease):
    """The release as the API shows it, read from github.com's public pages.

    The pages have no request budget: the latest tag is where /releases/latest
    redirects (the newest one in the Atom feed for the prerelease channel) and
    the release's asset list shows each asset's SHA-256.
    """
    site = f"https://github.com/{repo}"
    if prerelease:
        feed = fetch(f"{site}/releases.atom", f"{tool} release").decode()
        found = re.search(rf'href="{re.escape(site)}/releases/tag/([^"]+)"', feed)
    else:
        url = fetch_page(f"{site}/releases/latest", f"{tool} release")[0]
        found = re.search(r"/releases/tag/([^/?#]+)$", url)
    if not found:
        raise ValueError(f"cannot read the latest {tool} release from {site}/releases")
    tag = urllib.parse.unquote(found[1])
    page = fetch(f"{site}/releases/expanded_assets/{found[1]}", f"{tool} assets").decode()
    assets = []
    for chunk in page.split(f'href="/{repo}/releases/download/')[1:]:
        link = chunk.split('"', 1)[0]
        digest = re.search(r"sha256:[0-9a-f]{64}", chunk)
        assets.append(
            {
                "name": html.unescape(urllib.parse.unquote(link.split("/", 1)[1])),
                "browser_download_url": f"{site}/releases/download/{html.unescape(link)}",
                "digest": digest[0] if digest else None,
            }
        )
    return {"tag_name": tag, "assets": assets}


def latest_release(repo, tool, prerelease):
    """The newest release of a repo from the API; the public pages once the API is rate limited."""
    api = GITHUB_API.format(repo)
    try:
        if prerelease:
            releases = json.loads(fetch(api + "?per_page=10", f"{tool} release"))
            return next((r for r in releases if not r["draft"]), None)
        return json.loads(fetch(api + "/latest", f"{tool} release"))
    except RateLimited as error:
        print(f"provisions: {error}; reading github.com's release pages instead", file=sys.stderr)
        return release_from_pages(repo, tool, prerelease)


def verified(tool, version, key, name, url, checksum, binaries):
    """A lock-shaped spec, only when the publisher lists a SHA-256 for the asset."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", version):
        raise ValueError(f"{tool} release tag {version!r} is not a safe version; refusing it")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError(
            f"{tool} {version} publishes no SHA-256 for {name}; refusing an unverified binary"
        )
    kind = "zip" if name.endswith(".zip") else "tar" if ".tar." in name else "file"
    asset = {"url": url, "sha256": checksum, "format": kind, "binaries": binaries}
    return {"version": version, "assets": {key: asset}}


def resolve_latest(key, names):
    """Specs for the newest releases of exactly these tools, and nothing else."""
    latest = {}
    stable = {}  # repository -> its latest release, so tools from one release share it
    skipped = set()
    for tool, (repo, prefix, pattern, binaries) in GITHUB_LATEST.items():
        if tool not in names:
            continue
        try:
            if tool in PRERELEASE_CHANNEL:
                release = latest_release(repo, tool, True)
                if release is None:
                    raise ValueError(f"{tool} has no published release")
            else:
                if repo not in stable:
                    stable[repo] = latest_release(repo, tool, False)
                release = stable[repo]
            version = release["tag_name"].removeprefix(prefix)
            name = pattern.format(v=version, key=key, **ARCH[key])
            asset = next((a for a in release["assets"] if a["name"] == name), {})
            checksum = (asset.get("digest") or "").removeprefix("sha256:")
            url = asset.get("browser_download_url", "")
            if tool in SHA256_FILE:
                sums = next((a for a in release["assets"] if a["name"] == name + ".sha256"), {})
                text = fetch(sums["browser_download_url"], f"{tool} checksum") if sums else b""
                checksum = text.decode().split(" ")[0]
            latest[tool] = verified(tool, version, key, name, url, checksum, binaries)
        except (OSError, ValueError, KeyError) as error:
            if tool not in OPTIONAL:
                raise
            skipped.add(tool)
            print(f"provisions: skipping optional {tool}: {error}", file=sys.stderr)
    if "node" in names:
        releases = json.loads(fetch("https://nodejs.org/dist/index.json", "node release"))
        tag = max((r["version"] for r in releases), key=lambda v: tuple(map(int, v[1:].split("."))))
        name = f"node-{tag}-linux-{ARCH[key]['node']}.tar.xz"
        sums = fetch(f"https://nodejs.org/dist/{tag}/SHASUMS256.txt", "node checksums").decode()
        match = re.search(rf"^([0-9a-f]{{64}})  {re.escape(name)}$", sums, re.M)
        binaries = {command: f"node-v*/bin/{command}" for command in ("node", "npm", "npx")}
        latest["node"] = verified(
            "node",
            tag.removeprefix("v"),
            key,
            name,
            f"https://nodejs.org/dist/{tag}/{name}",
            match[1] if match else "",
            binaries,
        )
    if "forgejo" in names:
        # Installed by Ansible itself (blueprint/ansible/tasks/forgejo.yml), which also
        # checks the release signature against the Forgejo release key.
        releases = json.loads(fetch(FORGEJO_RELEASES, "forgejo release"))
        release = max(
            releases, key=lambda r: tuple(int(n) for n in re.findall(r"\d+", r["tag_name"]))
        )
        version = release["tag_name"].removeprefix("v")
        name = f"forgejo-{version}-linux-{ARCH[key]['go']}"
        urls = {asset["name"]: asset["browser_download_url"] for asset in release["assets"]}
        checksum = fetch(urls[name + ".sha256"], "forgejo checksum").decode().split(" ")[0]
        latest["forgejo"] = verified(
            "forgejo", version, key, name, urls[name], checksum, {"forgejo": name}
        )
        latest["forgejo"]["assets"][key]["signature"] = urls[name + ".asc"]
    if "rustup-init" in names:
        toml = fetch("https://static.rust-lang.org/rustup/release-stable.toml", "rustup").decode()
        match = re.search(r"^version = '([0-9.]+)'$", toml, re.M)
        if not match:
            raise ValueError("cannot read the latest rustup version")
        version = match[1]
        url = f"https://static.rust-lang.org/rustup/archive/{version}/{ARCH[key]['gnu']}-unknown-linux-gnu/rustup-init"
        checksum = fetch(url + ".sha256", "rustup-init checksum").decode().split(" ")[0]
        binaries = {"rustup-init": "rustup-init"}
        latest["rustup-init"] = verified(
            "rustup-init", version, key, "rustup-init", url, checksum, binaries
        )
    for tool, package in NPM_LATEST.items():
        if tool in names:
            registry = fetch(f"https://registry.npmjs.org/{package}/latest", f"{tool} version")
            latest[tool] = json.loads(registry)["version"]
    # Installed by Ansible itself for the iMessage bridge.
    for package in ("spectrum-ts",):
        if package in names:
            registry = fetch(f"https://registry.npmjs.org/{package}/latest", f"{package} version")
            latest[package] = json.loads(registry)["version"]
    if "psutil" in names:
        # The Chrome pruner's runtime, installed by Ansible with uv --require-hashes.
        pypi = json.loads(fetch("https://pypi.org/pypi/psutil/json", "psutil release"))
        hashes = [file["digests"]["sha256"] for file in pypi["urls"]]
        if not hashes or not all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes):
            raise ValueError("psutil publishes no SHA-256 digests; refusing an unverified binary")
        latest["psutil"] = {"version": pypi["info"]["version"], "sha256": hashes}
    if unknown := sorted(set(names) - latest.keys() - skipped):
        raise ValueError(f"no latest release source for: {', '.join(unknown)}")
    return latest


def download(url, checksum, destination):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[0-9a-f]{64}", checksum)
    ):
        raise ValueError("downloads require HTTPS and an explicit SHA-256")
    with INSTALL_OUTPUT_LOCK:
        print(f"Downloading {url}", file=sys.stderr)
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with (
                urllib.request.urlopen(url, timeout=120) as response,
                destination.open("wb") as stream,
            ):
                if urllib.parse.urlsplit(response.geturl()).scheme != "https":
                    raise ValueError("refusing an insecure download redirect")
                shutil.copyfileobj(response, stream)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            # GitHub release assets intermittently answer 5xx; a 4xx is final.
            status = getattr(error, "code", 500)
            if status < 500 or attempt == DOWNLOAD_ATTEMPTS:
                raise
            time.sleep(attempt)
    if digest(destination) != checksum:
        raise ValueError(f"checksum mismatch for {url}")


def extract(archive, destination, kind, name):
    if kind == "file":
        shutil.copyfile(archive, destination / name)
    elif kind == "tar":
        with tarfile.open(archive) as source:
            source.extractall(destination, filter="data")
    elif kind == "zip":
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                path = PurePosixPath(item.filename)
                mode = item.external_attr >> 16
                if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
                    raise ValueError("unsafe ZIP member")
            source.extractall(destination)
    else:
        raise ValueError(f"unsupported archive format: {kind}")


def binaries_in(root, patterns):
    result = {}
    for name, pattern in patterns.items():
        if name in (".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("unsafe binary name")
        matches = [p for p in root.glob(pattern) if p.is_file()]
        if len(matches) != 1 or not matches[0].resolve().is_relative_to(root.resolve()):
            raise ValueError(f"expected one safe binary for {name}, found {len(matches)}")
        result[name] = matches[0]
    return result


def link_binary(home, name, target):
    link = home / ".local/bin" / name
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() and link.resolve() == target.resolve():
        return False
    if os.path.lexists(link):
        old = link.resolve()
        if not link.is_symlink() or not (
            old.is_relative_to(home / ".local/share/crewship")
            or old.is_relative_to(home / ".cargo")
        ):
            raise ValueError(
                f"unmanaged command exists: {link}; choose a clean account or relocate it explicitly"
            )
        link.unlink()
    link.symlink_to(target)
    return True


def install_asset(home, name, spec, key):
    version = spec["version"]
    if (
        name in (".", "..")
        or version in (".", "..")
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", version)
    ):
        raise ValueError("unsafe tool name/version")
    asset = spec["assets"][key]
    final = home / ".local/share/crewship/tools" / name / version / key
    stamp = final / ".asset.json"
    expected = hashlib.sha256(json.dumps(asset, sort_keys=True).encode()).hexdigest()
    valid = False
    if stamp.is_file():
        saved = json.loads(stamp.read_text())
        paths = binaries_in(final, asset["binaries"])
        valid = saved.get("spec") == expected and saved.get("files") == {
            n: digest(p) for n, p in paths.items()
        }
    changed = False
    if not valid:
        if final.exists():
            raise ValueError(
                f"installed artifact drifted or is incomplete: {final}; inspect it before replacing"
            )
        final.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=final.parent) as temporary:
            temporary = Path(temporary)
            archive = temporary / "download"
            unpacked = temporary / "contents"
            unpacked.mkdir()
            download(asset["url"], asset["sha256"], archive)
            extract(archive, unpacked, asset["format"], name)
            paths = binaries_in(unpacked, asset["binaries"])
            for path in paths.values():
                path.chmod(0o755)
            (unpacked / ".asset.json").write_text(
                json.dumps({"spec": expected, "files": {n: digest(p) for n, p in paths.items()}})
                + "\n"
            )
            unpacked.rename(final)
        changed = True
    for binary, path in binaries_in(final, asset["binaries"]).items():
        changed = link_binary(home, binary, path) or changed
    return changed


def link_grammars(home, store):
    """Link sentrux's grammar paths to a verified release, so sentrux never fetches them."""
    changed = False
    for grammar in store.glob("*/grammars/*.so"):
        link = home / ".sentrux/plugins" / grammar.relative_to(store)
        if link.is_symlink() and link.resolve() == grammar.resolve():
            continue
        link.parent.mkdir(parents=True, exist_ok=True)
        staged = link.with_name(".new-" + link.name)
        staged.unlink(missing_ok=True)
        staged.symlink_to(grammar)
        os.replace(staged, link)
        changed = True
    return changed


def command(argv, environment):
    subprocess.run([str(arg) for arg in argv], env=environment, check=True, stdout=sys.stderr)


def link_package_bins(home, destination, package_names):
    # Only expose explicitly requested packages, not incidental dependency bins.
    changed = False
    for package_name in package_names:
        root = destination / "node_modules" / package_name
        package = json.loads((root / "package.json").read_text())
        bins = package.get("bin", {})
        if isinstance(bins, str):
            bins = {package_name.rsplit("/", 1)[-1]: bins}
        for name, relative in bins.items():
            target = root / relative
            if not target.is_file() or not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"invalid installed package command: {name}")
            changed = link_binary(home, name, target) or changed
    return changed


def bun_latest_install(home, tool, version, environment):
    """Install exactly this version into its own prefix; a new version relinks the tool."""
    package_name = NPM_LATEST[tool]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+[A-Za-z0-9.+-]*", version):
        raise ValueError(f"unsafe {tool} version")
    # ponytail: superseded versions stay on disk so running agents keep their files;
    # prune them by hand or add a sweep if disk use matters.
    final = home / ".local/share/crewship" / tool / version
    package = final / "node_modules" / package_name / "package.json"
    changed = False
    if not package.is_file() or json.loads(package.read_text()).get("version") != version:
        if final.exists():
            raise ValueError(f"incomplete {tool} install: {final}; inspect it before replacing")
        final.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=final.parent) as temporary:
            staging = Path(temporary) / "prefix"
            staging.mkdir()
            # `bun add -g` with bun's global directory and bin directory pointed at the
            # staging prefix: the package lands in <prefix>/node_modules, one version per
            # prefix, and ~/.bun is untouched.
            result = subprocess.run(
                [
                    home / ".local/bin/bun",
                    "add",
                    "--global",
                    "--exact",
                    "--no-progress",
                    f"{package_name}@{version}",
                ],
                env={
                    **environment,
                    "BUN_INSTALL_GLOBAL_DIR": str(staging),
                    "BUN_INSTALL_BIN": str(staging / ".bin"),
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            with INSTALL_OUTPUT_LOCK:
                print(f"provisions: {tool} {version}", file=sys.stderr)
                print(result.stdout, end="", file=sys.stderr, flush=True)
            result.check_returncode()
            staging.rename(final)
        changed = True
    changed = link_package_bins(home, final, [package_name]) or changed
    if tool == "chrome-devtools-mcp":
        changed = point_current(final) or changed
    return changed


def point_current(target):
    """Re-point `current` beside a version directory at it, so unit and profile text never change."""
    link = target.parent / "current"
    if link.is_symlink() and link.resolve() == target.resolve():
        return False
    staged = target.parent / ".current.new"
    staged.unlink(missing_ok=True)
    staged.symlink_to(target.name)
    os.replace(staged, link)
    return True


def retire_legacy_npm(home):
    """Remove the codex, pnpm and pnpx links into the dropped npm prefix; the prefix stays for live shells."""
    legacy = home / ".local/share/crewship/npm"
    changed = False
    for name in ("codex", "pnpm", "pnpx"):
        link = home / ".local/bin" / name
        if link.is_symlink() and Path(os.readlink(link)).is_relative_to(legacy):
            link.unlink()
            changed = True
    return changed


def rust_environment(home, environment):
    return {
        **environment,
        "CARGO_HOME": str(home / ".cargo"),
        "RUSTUP_HOME": str(home / ".rustup"),
        "PATH": f"{home / '.cargo/bin'}:{environment['PATH']}",
    }


def rust_install(home, environment):
    """The stable toolchain with rustfmt and clippy; an apply moves it to the newest stable."""
    version = "stable"
    rustup = home / ".cargo/bin/rustup"
    environment = rust_environment(home, environment)
    profile = ["--profile", "minimal", "--component", "rustfmt", "--component", "clippy"]
    changed = False
    if not rustup.exists():
        init = [home / ".local/bin/rustup-init", "-y", "--no-modify-path", "--default-toolchain"]
        command([*init, version, *profile], environment)
        changed = True
    else:
        # ponytail: the rustup binary itself only changes on a fresh account;
        # add `rustup self update` here if an old rustup ever matters.
        result = subprocess.run(
            [rustup, "toolchain", "install", version, *profile, "--no-self-update"],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        changed = " unchanged - " not in result.stdout
        components = subprocess.run(
            [rustup, "component", "list", "--installed", "--toolchain", version],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        missing = [
            name
            for name in ("rustfmt", "clippy")
            if not any(line.startswith(name + "-") for line in components.splitlines())
        ]
        if missing:
            command([rustup, "component", "add", "--toolchain", version, *missing], environment)
            changed = True
        current = subprocess.run(
            [rustup, "default"], env=environment, capture_output=True, text=True, check=True
        ).stdout
        if not current.startswith(version + "-"):
            command([rustup, "default", version], environment)
            changed = True
    for name in (
        "rustup",
        "cargo",
        "rustc",
        "rustfmt",
        "cargo-fmt",
        "cargo-clippy",
        "clippy-driver",
    ):
        changed = link_binary(home, name, home / ".cargo/bin" / name) or changed
    return changed


def sgrep_install(home, environment):
    """The latest sgrep from its default branch, built by cargo; an apply moves it to the newest."""
    environment = rust_environment(home, environment)
    binary = home / ".cargo/bin/sgrep"
    before = digest(binary) if binary.exists() else ""
    command(
        [home / ".cargo/bin/cargo", "install", "--git", SGREP_REPOSITORY, "--locked"], environment
    )
    changed = digest(binary) != before
    changed = link_binary(home, "sgrep", binary) or changed
    warm_sgrep(binary, environment)
    return changed


def warm_sgrep(binary, environment):
    """One tiny search per model, so the first real search downloads nothing.

    sgrep loads a code parser only for a file longer than one passage, so the
    scratch directory holds one long file per language it parses. A failed
    download only warns: sgrep fetches what it lacks on its first search.
    """
    with tempfile.TemporaryDirectory(prefix="sgrep-warm-") as scratch:
        for extension in SGREP_LANGUAGES:
            Path(scratch, "warm." + extension).write_text("value = 1;\n" * 400)
        for model in ("code", "text"):
            result = subprocess.run(
                [binary, "value", scratch, "-n", "1", "--model", model, "--no-cache"],
                env=environment,
                stdout=subprocess.DEVNULL,
            )
            if result.returncode not in (0, 1):
                print(f"provisions: sgrep {model} model not warmed (exit {result.returncode})", file=sys.stderr)


def fdu_install(home, environment):
    """The latest fdu from its PyPI wheel (no Rust toolchain), installed by uv; an apply moves it to the newest."""
    fdu = home / ".local/bin/fdu"

    def version():
        if not fdu.exists():
            return ""
        return subprocess.run(
            [fdu, "--version"], env=environment, capture_output=True, text=True, check=True
        ).stdout

    before = version()
    command(
        [home / ".local/bin/uv", "tool", "install", "--upgrade", "--no-build", "fdu"],
        {**environment, "UV_TOOL_BIN_DIR": str(home / ".local/bin")},
    )
    return version() != before


# omp marketplace plugins, upgraded on every apply to the default branch: name -> repository.
OMP_PLUGINS = {
    "ponytail": "DietrichGebert/ponytail",
    "i-have-adhd": "ayghri/i-have-adhd",
    "caveman": "JuliusBrussee/caveman",
}


def omp_plugins(home, environment):
    """Install each plugin from its marketplace, then upgrade all to its default branch."""

    def omp(*argv):
        result = subprocess.run(
            [home / ".local/bin/omp", "plugin", *argv],
            env=environment,
            cwd=home,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    changed = False
    marketplaces = home / ".omp/marketplaces.json"
    known = marketplaces.read_text() if marketplaces.is_file() else ""
    installed = {plugin["id"] for plugin in json.loads(omp("list", "--json"))["marketplace"]}
    if known:
        omp("marketplace", "update")
    for name, repository in OMP_PLUGINS.items():
        if repository not in known:
            omp("marketplace", "add", repository)
            changed = True
        if f"{name}@{name}" not in installed:
            omp("install", f"{name}@{name}")
            changed = True
    return "up to date" not in omp("upgrade") or changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--tools", default="herdr,node,bun,uv,btop,sentrux,fallow,pyrefly,nvim")
    parser.add_argument("--npm", action="store_true")
    parser.add_argument("--development", action="store_true")
    parser.add_argument(
        "--sgrep", action="store_true", help="also build sgrep with cargo (installs the Rust toolchain too)"
    )
    parser.add_argument("--fdu", action="store_true", help="also install fdu with uv (needs uv in --tools)")
    parser.add_argument(
        "--also",
        default="",
        help="comma-separated extra sources to resolve that Ansible installs itself: "
        "obscura, psutil, koncreet, forgejo",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="print the latest release of every selected source as JSON and exit",
    )
    parser.add_argument(
        "--resolved", type=json.loads, help="--resolve output to install instead of resolving"
    )
    args = parser.parse_args()
    key = platform_key()
    names = args.tools.split(",") + (AGENT_TOOLS if args.npm else [])
    if "sentrux" in names:
        names.append("sentrux-grammars")
    rust = args.development or args.sgrep
    if rust:
        names.append("rustup-init")
    names = list(dict.fromkeys(names))
    sources = {*names, *(NPM_LATEST if args.npm else ()), *filter(None, args.also.split(","))}
    if args.resolve:
        print(json.dumps(resolve_latest(key, sources)))
        return
    home = args.home.resolve(strict=True)
    if home.stat().st_uid != os.geteuid():
        parser.error("run as the user who owns --home")
    latest = args.resolved or resolve_latest(key, sources)
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": str(home / ".local/bin") + ":/usr/local/bin:/usr/bin:/bin",
    }
    prefix = home / ".local/share/crewship"
    prefix.mkdir(parents=True, exist_ok=True)
    with (prefix / ".install.lock").open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        changed = False
        with ThreadPoolExecutor(max_workers=4) as pool:
            installs = [
                pool.submit(install_asset, home, name, latest[name], key)
                for name in names
            ]
            for install in installs:
                changed = install.result() or changed
        if "bun" in names:
            # The release zip ships only `bun`; bun runs as `bunx` when invoked under that name.
            changed = link_binary(home, "bunx", (home / ".local/bin/bun").resolve()) or changed
        if "sentrux" in names:
            version = latest["sentrux-grammars"]["version"]
            store = prefix / "tools/sentrux-grammars" / version / key
            changed = link_grammars(home, store) or changed
        if args.npm:
            with ThreadPoolExecutor(max_workers=4) as pool:
                installs = [
                    pool.submit(bun_latest_install, home, tool, latest[tool], environment)
                    for tool in NPM_LATEST
                ]
                for install in installs:
                    changed = install.result() or changed
            changed = retire_legacy_npm(home) or changed
            changed = omp_plugins(home, environment) or changed
        if rust:
            changed = rust_install(home, environment) or changed
        if args.sgrep:
            changed = sgrep_install(home, environment) or changed
        if args.fdu:
            changed = fdu_install(home, environment) or changed
        if args.resolved:
            # The record checks compare against, so a later upstream release cannot
            # make an unchanged install look wrong.
            record = prefix / "resolved.json"
            known = json.loads(record.read_text()) if record.is_file() else {}
            record.write_text(json.dumps({**known, **latest}, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "changed": changed,
                "installed": names,
                "npm": args.npm,
                "development": args.development,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"provisions: {error}", file=sys.stderr)
        print(getattr(error, "stderr", None) or "", end="", file=sys.stderr)
        sys.exit(1)
