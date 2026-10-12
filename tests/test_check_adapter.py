"""blueprint/config/omp-as-pi/check-adapter.sh run against a stub curl: exit codes and messages."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "blueprint/config/omp-as-pi/check-adapter.sh"

# Answers like curl -sSL -o FILE -w '%{http_code}' for one pinned file, as picked
# by STUB_PLAN ("pi.go=404 fallback.go=503") or else STUB_DEFAULT.
STUB_CURL = """#!/usr/bin/env bash
out=
url=
while [ $# -gt 0 ]; do
	case "$1" in
	-o) out=$2; shift ;;
	https://*) url=$1 ;;
	esac
	shift
done
spec=$STUB_DEFAULT
for entry in $STUB_PLAN; do
	[ "${url##*/}" = "${entry%%=*}" ] && spec=${entry#*=}
done
case "$spec" in
200) echo "not the pinned source" >"$out"; printf 200 ;;
404 | 429 | 503) : >"$out"; printf %s "$spec" ;;
neterr) echo "curl: (6) Could not resolve host" >&2; printf 000; exit 6 ;;
cut) echo partial >"$out"; printf 200; exit 28 ;;
esac
"""


def check_adapter(tmp_path, default, plan=None, *args):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    curl = bin_dir / "curl"
    curl.write_text(STUB_CURL)
    curl.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "STUB_DEFAULT": default,
        "STUB_PLAN": " ".join(f"{name}={spec}" for name, spec in (plan or {}).items()),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *(args or ("v9.9.9",))],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_a_source_that_differs_from_its_pin_is_a_mismatch(tmp_path):
    result = check_adapter(tmp_path, "200")
    assert result.returncode == 1
    assert "changed in v9.9.9" in result.stdout


def test_a_pinned_source_that_is_gone_from_the_tag_is_a_mismatch(tmp_path):
    result = check_adapter(tmp_path, "503", {"ompgate.go": "404"})
    assert result.returncode == 1
    assert "ompgate.go is gone from v9.9.9 (HTTP 404)" in result.stdout


@pytest.mark.parametrize(
    ("default", "status"),
    [("503", "503"), ("429", "429"), ("neterr", "000"), ("cut", "000")],
)
def test_server_errors_and_network_failures_are_inconclusive(tmp_path, default, status):
    result = check_adapter(tmp_path, default)
    assert result.returncode == 2
    assert f"(HTTP {status})" in result.stdout
    assert "changed in" not in result.stdout
    assert "is gone" not in result.stdout


@pytest.mark.parametrize(
    ("default", "plan"),
    [
        ("503", {"pi.go": "200"}),
        ("neterr", {"fallback.go": "404"}),
        ("cut", {"pi_profile.go": "200"}),
    ],
)
def test_a_proven_mismatch_wins_over_an_inconclusive_fetch(tmp_path, default, plan):
    assert check_adapter(tmp_path, default, plan).returncode == 1


def test_the_tag_is_required(tmp_path):
    result = check_adapter(tmp_path, "200", None, *["a", "b"])
    assert result.returncode == 64
