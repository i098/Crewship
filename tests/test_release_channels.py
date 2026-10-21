import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("version", "prerelease", "tag", "expected"),
    [
        ("0.4.8-rc.1", "true", "v0.4.8-rc.1", "next"),
        ("0.4.8", "false", "v0.4.8", "latest"),
        ("0.4.8-rc.1", "false", "v0.4.8-rc.1", None),
        ("0.4.8", "true", "v0.4.8", None),
        ("0.4.8", "false", "v0.4.9", None),
    ],
)
def test_npm_release_channel(tmp_path, version, prerelease, tag, expected):
    workflow = yaml.safe_load((ROOT / ".github/workflows/npm-publish.yml").read_text())
    check = next(
        step for step in workflow["jobs"]["publish"]["steps"]
        if step.get("name") == "Check the package version matches the tag"
    )
    (tmp_path / "package.json").write_text(json.dumps({"version": version}))
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", check["run"]],
        cwd=tmp_path,
        env={**os.environ, "TAG": tag, "PRERELEASE": prerelease, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
    )
    if expected is None:
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert output.read_text().strip() == f"npm_tag={expected}"


@pytest.mark.parametrize(
    ("tag", "legacy", "failure"),
    [
        ("v0.4.7", True, ""),
        ("v0.4.8", False, ""),
        ("v0.4.8-rc.1", False, ""),
        ("v0.4.8", False, "checksum"),
        ("v0.4.8", False, "missing-checksum"),
        ("v0.4.8", False, "server"),
        ("v0.4.8", False, "api-digest"),
        ("v0.4.8", False, "api-unavailable"),
        ("v0.4.8", False, "lock"),
    ],
)
def test_bootstrap_runs_only_the_selected_checked_installer(tmp_path, tag, legacy, failure):
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    installer = b'#!/bin/bash\nprintf "selected=%s args=%s\\n" "$CREWSHIP_REF" "$*"\n'
    name = f"crewship-{tag}.tar.gz" if legacy else "install.sh"
    if legacy:
        with tarfile.open(mirror / name, "w:gz") as archive:
            member = tarfile.TarInfo(f"crewship-{tag}/install.sh")
            member.size = len(installer)
            archive.addfile(member, io.BytesIO(installer))
    else:
        (mirror / name).write_bytes(installer)
    digest = hashlib.sha256((mirror / name).read_bytes()).hexdigest()
    if failure == "checksum":
        digest = "0" * 64
    if failure != "missing-checksum":
        (mirror / f"{name}.sha256").write_text(f"{digest}  {name}\n")
    if failure != "api-unavailable":
        api_digest = "0" * 64 if failure == "api-digest" else digest
        (mirror / tag).write_text(json.dumps({"assets": [{"name": name, "digest": f"sha256:{api_digest}"}]}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if failure == "lock":
        commands = {
            "dpkg-query": "#!/bin/sh\nexit 1\n",
            "sudo": '#!/bin/sh\nexec "$@"\n',
            "sleep": "#!/bin/sh\nexit 0\n",
            "apt-get": (
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$APT_CALLS"\n'
                'if [ ! -f "$LOCK_SEEN" ]; then touch "$LOCK_SEEN"; '
                'echo "E: Could not get lock /var/lib/apt/lists/lock" >&2; exit 100; fi\n'
            ),
        }
        for name, body in commands.items():
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "url = next(arg for arg in args if arg.startswith('https://'))\n"
        "with open(os.environ['REQUESTS'], 'a') as log: log.write(url + '\\n')\n"
        "if url.endswith('/releases/latest'):\n"
        "    print('https://github.com/i098/Crewship/releases/tag/' + os.environ['STABLE_TAG'], end='')\n"
        "    sys.exit(0)\n"
        "source = pathlib.Path(os.environ['MIRROR']) / url.rsplit('/', 1)[-1]\n"
        "code = 200 if source.exists() else 404\n"
        "if os.environ['FAILURE'] == 'server' and url.endswith('/install.sh'): code = 500\n"
        "output = pathlib.Path(args[args.index('-o') + 1])\n"
        "output.write_bytes(source.read_bytes() if code == 200 else b'')\n"
        "if '-w' in args: print(code, end='')\n"
        "if code != 200 and any(arg.startswith('-') and 'f' in arg for arg in args): sys.exit(22)\n"
    )
    curl.chmod(0o755)
    requests = tmp_path / "requests"
    opt_in = "-" in tag
    result = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--container"],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "CREWSHIP_REPO": "i098/Crewship",
            "CREWSHIP_REF": tag if opt_in else "",
            "STABLE_TAG": tag if not opt_in else "v0.4.7",
            "MIRROR": str(mirror),
            "REQUESTS": str(requests),
            "FAILURE": failure,
            "APT_CALLS": str(tmp_path / "apt-calls"),
            "LOCK_SEEN": str(tmp_path / "lock-seen"),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    urls = requests.read_text().splitlines()
    if failure in {"checksum", "missing-checksum", "server", "api-digest"}:
        assert result.returncode != 0
        assert "selected=" not in result.stdout
        assert not any(".tar.gz" in url for url in urls)
    else:
        assert result.returncode == 0, result.stderr
        assert f"selected={tag} args=--container" in result.stdout
    if failure == "lock":
        calls = (tmp_path / "apt-calls").read_text().splitlines()
        assert len(calls) == 3
        assert all("DPkg::Lock::Timeout=" in call for call in calls)
        assert "update -q" in calls[0] and "update -q" in calls[1]
        assert "install -y -q curl ca-certificates jq" in calls[2]
    if opt_in:
        assert not any(url.endswith("/releases/latest") for url in urls)
    else:
        assert urls[0] == "https://github.com/i098/Crewship/releases/latest"
        assert all("-rc." not in url for url in urls)
