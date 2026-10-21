"""install.sh and the npm launcher print the usage before any install step."""

import base64
import errno
import getpass
import hashlib
import importlib.util
import io
import lzma
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import tarfile
import termios
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
BASH = shutil.which("bash")
SHIP = importlib.util.spec_from_file_location("ship", ROOT / "scripts/ship.py")
ship = importlib.util.module_from_spec(SHIP)
SHIP.loader.exec_module(ship)


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


def install_log(result):
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("Full install log: "):
            return Path(line.removeprefix("Full install log: "))
    pytest.fail("The installer did not print its log path")


@pytest.mark.parametrize("args", [["--help"], ["-h"], ["--container", "--help"], ["--user", "--help"]])
def test_help_prints_usage_and_changes_nothing(tmp_path, args):
    result = install(sandbox(tmp_path), *args)
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.startswith("Usage: crewship ")
    assert not any((tmp_path / "home").iterdir())


def test_usage_names_every_opt_in_feature(tmp_path):
    usage = install(sandbox(tmp_path), "--help").stdout
    assert all(name in usage.split() for name in ship.OPT_IN)


@pytest.mark.parametrize("args", [["--bogus"], ["--user"], ["--with"], ["--container", "extra"]])
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
        [shutil.which("node"), "--require", str(stub), str(ROOT / "tools/npm/crewship.js"), "--help"],
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
[ -z "${CURL_REQUESTS:-}" ] || printf '%s\\n' "$url" >>"$CURL_REQUESTS"
code=200; redirect=
case $url in
  https://github.com/*/releases/latest) code=302; redirect=https://github.com/i098/Crewship/releases/tag/$(cat "$MIRROR/latest") ;;
  https://github.com/*/releases/download/*/*)
    if [ -f "$MIRROR/${url##*/}" ]; then cp "$MIRROR/${url##*/}" "$out"; else : >"$out"; code=404; fi ;;
  https://github.com/*/archive/refs/tags/*.tar.gz)
    if [ -f "$MIRROR/src-${url##*/}" ]; then cp "$MIRROR/src-${url##*/}" "$out"; else : >"$out"; code=404; fi ;;
  *) code=403; echo '{}' >"$out" ;;
esac
case $fmt in *redirect_url*) printf %s "$redirect" ;; *http_code*) printf %s "$code" ;; esac
"""
SHIP = """#!/usr/bin/env bash
echo "$1" >>"$HOME/calls"
echo "$*" >>"$HOME/args"
if [ "$1" = dock ]; then mkdir -p .local && echo "dock-v$(cat VERSION)" >.local/host.yml; fi
"""

INSTALLER_V047 = lzma.decompress(base64.b64decode(
    b"/Td6WFoAAATm1rRGAgAhARYAAAB0L+Wj4Ds2FsddABGIQkeKIzPDdw8z/VWX7afG1TtMjxXpQsg+dBWsTnInIaaojqnerPjybjd4"
    b"Ll6L8kURqEVyRvVJtKI7VSZcE5Q0wTTRNA7JB7EdnqtYfv1A09vKl5DnEzbeP8y+Qbwk4svDXXmtD2+eTNSyI3jWHtEngzLSLzYI"
    b"koVi1PQfCrSl506GoYMJgF6p0VT92S4xGCHkMzhxokUhewemt/JKKdcW5UT7WOlwK67ZtohVDBnRHBfafxEKwGGMFVjgpzent6QM"
    b"ouBCI/bGjs6NCBJhJsh5S2vX47LHqBfL/ZJP07zY1HbKaTzMjS9EqLVDPuI4VqWliNNsh3FwQXvwUGodqtI3Uslk4iWwSdYb9k/I"
    b"vR66nPKcDmA+vSGZV762YyZbviARquFFXo+ibq2v8x+/yDxaoNXf7CrBQrFOQMm2iEgPYDMemoy2EqutvN6OVtGNhiLy6kCgEkP6"
    b"5LdwKF2DlNu48uqSSUMS4jCBKsnVIH2E0mP+ZNZ0xd0ws8WdxFIw7x2PFUTcDyehFnadoal3ozybxWD4nuD9RhI3p3J2M0wLUDTO"
    b"VG128q+Ehy9jj/7qLX/HBtRPRTfXgQJhU6y39n//ugwOGdwpv24Ja1dTMIiI0gHghVTkMA6TVcF61Cgs7YrIgrGNxg2sw+M1J7Eb"
    b"1vpyo1oHzJ+lY+5NUxHZCv8tFQvNuSkN51PW4AkEkv/4h5HbmM6v4wu0KtOgAgJ9Y6Ai/2IunZpXya26yfq3RGXrhlRV+ZgX/lPX"
    b"/RXhgV5ztzLnV8BqGvjjeKEcnIPobX4sbVLUN5lNQMyPDHDb1Taxq4BaqvU7vMJqp4R8JrGNvJEDoHahJHB0Vs2AObYC3YKhaf3R"
    b"uSVc+/bMdsBfzZpuFFY2tAtNOho+8SRjZlZYkaQgVrhTNP1qgSVdO0ygxaASYNSPdUCOBsUMnrSzgCUIEmvGxyAQ1Nox9JIVq0LJ"
    b"9vhb7RGXD4C8PUUc9lxTm4402hi5TjR1J94anBbFP0gVSjomre0LPPEv43ThBIPTzbMyRRF/iimdTZr2NmsPO1xPOyClBGOCvdXu"
    b"lau8G+cRq5OWl/PdSQJ4itwffeScjOTBIHuwQzCXicR/lclrgWyefUpxi12eNCIsqXzqjMceW6rsI64Y3jPdxA/0TPktbx5RSW4B"
    b"vMD9DfiA3+oaS/rhCGa0XRXyDdi5KoDaji1BRJ5a337xNQ86Ix79nQe8SqtQHQOwHuhX6X7OjO9TQa50L9JvCw7gCsNG8wkw78Dc"
    b"CntOTNfgFJGP0ALX1catKq/q/rBf1O1bX7E8oKLDvuE3pZmgqZ89ETHD0X8rO1U0Tqybt9X7wi295ubnPorTu8UChzqCs+eeF79Z"
    b"FnuTvJedu1Z2UIY7Gdsq6v8tOS1g9l65Z2SPPsECje8IeWDMP84a5sql9UhxfyuP0yIhVwgz3X0Nk3r93CFOh0is4J97P1iwit+a"
    b"LwnF2e3DPeUJIaRH78siAIBttGF7OYcX1w7eVvpSGyHpKHFxa1M824uPjFW6YRwJZv/jf5e8VN2jzA6r/Nl63K51QUaMojdt8onX"
    b"LtAUxbXPRC/mSoxuqvEO7jQGG5SvwzanXnh8DgkEIaSi75yZxWY1jddLE/o/L6FJHSSj7T7m60RG1aHvOsn581nc5F0p6eBA8mfb"
    b"OHJoFPY0IpvkfdZiPvupOGarpwUeYk8Roa+EM64QaLeUgSX8ERLLBwA4t9pu/On8MzikveNIppY5zDHnPHiNaNL+azF8B7bJTL9n"
    b"XYUJ+5Ei6VeoGj6KWQdl0v1Xbh6qbylhRxC/GBAFPXHkxtmVRQ+1ocHOgnd+wnuGvNFamhjDcj+I+4aNrmV0ePY11/fIBo1SsiIc"
    b"nrWwzZktEbl2fiEEuK2FHHS9Vn/t/cwv6E3B9OI0M23xb8B7HaqHU9lSn1XTO4qCFKNM9b2T5uAqXtu4IiHG8enXloK5KYkZT/Ti"
    b"3IaZT66dTJkTSleK6w6rRw4SbuDYfTfv0BCnbVsXO4PLV0ZcbACd2CA+Y+xMSHy509q5MbMKM/Vid3wXlXciefVSaGNTNMyv9G+8"
    b"gvjTy1KZ+YKozkhoteUVbgPKcpFr2ARNAWjZ++Ey9rp/pFdkz5xeDdO6VgQFeYDHcpsw66cC1mkvPpYUqAJc3hg2B7vAq4nvZ4PW"
    b"EgtyYbiHnUBOu8NT2eRU4HZVbqKlpa9BeBuccKh0iAxzeEanNIb2A4jIpiTeSMf3jdpwOcdmA7eYh/9SOY6qsjh20CIgPoHJ9dXD"
    b"i1Ur6p2iWxxap/n7KJRAgGX1gERqdKgZaLpFuWKAKGq651v42jk3d8+OLOHkLIpVb3rHg6j4v3qOUqRsYKKjyylEZTTAEbMlpTC1"
    b"5sErvoNmFDU+3/FtcSux8m/S89GszJVv3Nbf87ryOzGhWSeq329KoOCz7X7uv+r6TRFhQzXEGfqmWJBlLfwlr+eTmRG9zTAfFtAU"
    b"p9i2tnsxkwrbdRQeXeJcJjtaNHM3M/MaQUCyHWtzukxlSOTFE9u+PI98KyyL2FXsWljYqu+lYPEYkacc6WPicNxN6XuuboKWa+2Q"
    b"4PV2/IlHcccz7/72WIEh89k0D1XCgZA+y8PyrBazi1IYwHK16UKbDtRuGdMMoCuPRhE+eHbQA7LfV2opxGWHTmuRBCh7/TpfnKp5"
    b"CaGThAPS/gr+vvbPemCO+U2aZz2IWjWlKAq50CY14xo+1gaJ9412H8efNTQNXtcso9EKmN7tzOLhREb8yxBYLSv5gEJnryybQ8yB"
    b"YakT8YnV0rfXhXHrJGPAf71INs1ynMMReQ3X/k0ioUg6wuy766wPCrVzQijj9BQE7URaIztKwLn1ty49AmGQQJrYrixTxDEDroPq"
    b"xsDGjDMiRjpkq4p2MLrJqeZNBWNOhI6AnFJPeWy9hLrpbobhW4PIp0GoxGFLwSPOwqWPRmFQV4WDww/ESaPg8j3BCZa6ufY0UfT5"
    b"jM9jjjXFvxqP2DUEH3BxZCA7QPA1dRDetSRVJOkbMeGmiKNsYT3viKSgohelQBxF7JXw1CxyrFqLWAFAs0e6BIXs8wVYvyWF8i18"
    b"6+ZcvVBKF/qr2Lr1FSDwUrZJ8y5yg961r5C15FPwdAXle4LKq7eXxuGN10M39WNGIniiC4w25GJDx5U4xAkYFRw1au9hC47wIrL+"
    b"2RnAeo7nt753cgC5UdnU5jprB764/pBZrlqcWU+cbZuKrxJ+2SSevqhv3uVeZpQilflXVbAmNV0B88zoH+Y5Zk0/OOY80dKm44wt"
    b"SzR8S2RsB/VQ1fHaMR+j4Hqhs9+S2vyK1o2YSUjs/HYMDt3WiB0uewasWa4jQkGdZXtywe7fkrdtgT6u1zumIESEovL9t+0aPU7s"
    b"MmiNWoSis9S4X0iev+EaEqpMJgfk15u5P40PPe9D62NW6T8oT9tZkXJdVk+A/W8dzY5+4+bMHyhCrMQYwXfv5JuFAWp0owBVqXev"
    b"yqglv+9DLeHO3gVi9R+eRXI/ONKjtiiwnBqv0mSTvWtd9Ciao+iJ6Ahkj7KyLZD3pQ1hSvNMqYXoZqL5vPMWcsx2Wves1nTQzzEw"
    b"3ecsEnEpoAzHUNKmnwSeXqC9d0PWJSe+2HNmUEZsgjV7h70Tfcpu+hik+CY5Xe2UnYR63FHK0hbxtP2Tlcl49JC81JnUMMYvzVf8"
    b"X8o0OF6xtyPGQR/HdM21lH1WvOh+VQ49LVdIBxt3llAuPfFOer3ZW1NXULXzBdgtZ4YhDJLBo1cbk3xNEhlAA4qjaxfuLAS3ft3i"
    b"ZjtAPdYAOVN7XPUNyiCF0zO5tq2tTzTh/LbtoAKt/AhtYWcjvU6pNFCUZtcwT2bl9YROPQsQmbfhSu+lMH/YILfuc9gKpD/c3YTu"
    b"uXqjX7ddr5Et4Yc3sDdfQedSGDPtKvd9uyMSgd2PiiC2FD6Cxvlse41AgLjgRRJRUsFZ+SS97gCWFrONdl2BODeUr1crNaaLpQ/D"
    b"P7ij0AIcRmT0Cb2aDKSmRtlsgi85E2CI962lyJLSWRG6Ey0RotUNuLfcU9oExC0GEOrhH2bwgAqin2s5oEAcN0fBmVG2neAiagia"
    b"uAmGRYTdc19QzRmL3Xrqd7IMN4nw1MMZ5V6KkgILeFD6Wo14m33fR8Fk61VGCWKqZRpusLZVZzwucphCl56PTeOERyKMM6I1IQ3x"
    b"mjo327UKiCAr7lRE7S9v6wSB44b7KP6aGS9x3FSQl5p9Qn+xJFGQ55VGoap/keayenIITQH71wxZGu5LmvJPaQ7vj5xc2LMmW64Y"
    b"5cjm7aevg4dHqKREAAOaoQkKEX4OGOfF6w2M+T/ASTEilQZkmobpq+YaD4aPgaN7VPXwW43pO/AUjXcjCoowoWRswAIFyuRWZzc0"
    b"qmzVqWWoPfTlsnYGSYAUbGr/FkHPaX2aF79uJjs7HOUQnY34iLfpoDrTJun2Ny+KkZcDVxwiX16YYKTkKyL2qlq98MEVTsTvxKkC"
    b"LRli8RwNx+0D4Ra6a+nGaVL2s8UqxmrENZG6EUwm521aBS+acP0vhTZ5wJ6HgJEcafjkIWaBlIHsXOqC6aw6w495VF40me2FNbAm"
    b"Frsb9TjwJxAljI+xVeDYB/kYhjqSeboZEdNyouUOhcVh1G+a9srS/b9x0ko0GD92YY4K6TVvx0vnK3ko9kplD6dklBfpaiT8cUMQ"
    b"87w8RwaDZd+rzJTa7fLVA/T01JwNt4t1UKoN4HMJTqQsQYZlMP3+FdqwQMCgeeEk7Akgi83bpJOjW3J8GyCq50FLH4zYiTsvP6dm"
    b"+d478xS6WM4LwXt4DnCM0uf+dwUBD1MIWe5BcL/tuaMSgyBmL+jgrgfhT8TJNCr0rZBUmQMMPQS1qCdapKZ2xW+NWPvMtQuUDTZ7"
    b"ZI/UGXn4A+gBYI2VLaMXb8UOLmmRAYcZFdqrIqS02a0KLpTYapg9BlExUtmnHgGRFO/x6hV7YZhbpcbYHmpDjmFqQSRE6g4x+rq1"
    b"8e1yw1eCxXHqRm4C10SNEZU9JKYp/BdroJo3fdNAuS1Y4pA2DYRupE3+FkKmOZd4WcU7jJMtZh39nqmt5ly/gRsxoqbnmnpJOdAc"
    b"UznRWkcX8Tyamt+5UNDRY2d1BFr5QxiLVT5u/Rs6soDNKVdL6j0cKlAdc4/noktBoeoztKyLWNQUWm3vS+JuZqcuUgC05YTqvDRd"
    b"e4QZJTyupUpyO1cMPSlmArJg3Xrrr5w3GmOZTqorGu+c3/8i78KzgFFdt8rSrZFSnaOmSb0s35XnZt/7dOoBqOLK3y1GUypKcws2"
    b"x4J4mEIMinYNK3sjqUgAHl7eebahwPwaILQbvqd2UpeANglO3woIaWDaPOSy1hOjHjE7SZJ8PDwe/FpRRtB/bfTpq77OWa5Hm7p/"
    b"Ult/9qSjK0PEohyn/pSZtL7afCc2vu+DTNFS3R/msl/4+KNlLGsxwvYO3IeHkrHwGWJtPM7FCpsWc8ebL5oxnAYl/Oy09yYIa/Ml"
    b"zpPWMynYc4vYmMbBX0EkQAbTghgJdz8l34Q7lP4MvaOdVK+86LC0u5eAgcYFvHdQ7B0TrJgbJK5HBeQB1w090CZXsw9kaePK0Z9+"
    b"5zEnAaz4zfXWSNbBpRlpPZ3iLig0caSax0Lg+AjaNjaur9NLExx6jnDwQD3Bvu6OVcFr8IRjOofrM5kfnljDLCKyitbCKEb0zSlh"
    b"oqu2uCinXRiBakK3p4hpNMgtEQPY/QE9jG4uOM72M8KLEKihrbHqcbfmS8YfFaaRbStTLfVuSUcbfawbeGlNymYFdYlwxyNqIL9z"
    b"Esi6joCh7WM9HJUItNSV9iSReFqWrIOPqDjQS39wr2f2JTLet6E3GucnFEUekiOMOi3ZQm95l3uIeG/fi8NICt5XUdU03I0PyyDO"
    b"UwhmGK1WC5f3uGiHu/AHjeivIW5rSObicsOC51sdaJinEdUriqQEqF957z8ZcpmpF2znADX5gHRzlIBdJ4cDkarE0esWzTJBLYBo"
    b"7zmt9nAK+DxZ1hR6u4UYqm1o2GTc22k6G1tcMeNnCuur+s1UQ7zbU0SthXX5K13vkz0xieIYDdBhvB6M+t1JHgFqT3fPm8HkBQro"
    b"JWVa1SdqS7YT/pSCVGew5Yqyu4ATtAZYPs/CL1UlmCuP9GcG+9oD5fddd95fJO0cC8LYnlDgiquVz61CqftUbsLAY4gny1yo7Kzh"
    b"Ijk4m7Q1i80aSG93Ef3ZfcHtmBmpiDZDkian9JhB1kDTQiZUctTyDEEoKy37M/HhARm7iiNgPKWtefEHaUHPMInANPVCzpEYzzb7"
    b"4TmQRk3xzAl0vAbNVXABIr8b08ng5qsR1KzyRxYMdBqAhgf77Uqvi9TdjBE+VNYRBRfXsZKP5/gaFC8CDENVwBKW4d6i51yH6y/5"
    b"Ma0oCgmeSSnmtxVt2cVu0KKq2E9QyHRgFSglbiEA5YdrPvAGnbnLxE7MJzZ6ST869ajs7yXjj6UEiswTCQkRr4MPFLKpy0aCc0Ib"
    b"bav8gI5Lr3XFuJtRJuKUqvVZU+kdFGaoSAeRyQc1oRdQwzI0sC273cFeSmyqu2+s1vMlerl1XPbkIuT32iCWYz25DMZfUTvsDthX"
    b"ciZZ+ih/N16UTlQViY0k+AZdLb64J93T+LTFRQX79WiTI3P5h+valNDG1aBR3OdhohIjxg//lcajLuTI9CxeZBhkMa/2dNCsoh+i"
    b"nm7/A/iHiGxdBqHpK2yA29OeE2X4Id4WvBvDuPHQsW9l7vHJfaHFQnziQHjIb84/RSBIH9NSWsnlENiITNe18NRUZvxpRTjGU6iH"
    b"UIUYxfhkYeYdP06nWxk6B3SBQMcIGP2JTztJbgnk+E1YYi6RXga4BrDVBd+4HgIrSAHLB8NVOVxkPSzULd+o2I4VEiEk1CphslZb"
    b"DxbUDtF1Ei6G44nXfWt9qRhbZgLnBXPZ5bHU59UHozTHzHArPysxiyuai31yDIUgUpRNM1mYnw3F9JlkJtMjgr4GpVcHcnM1FzvN"
    b"WdZXA77+o35d3/ZDfgyLhp7M/ggYVydOwL5ZCx3H0mOA7qcbqNgp26ndTGvgs0TCtls3tfxhladDrkhsBYMKYnTTdkJbYdVmWCs+"
    b"eAtzlm83zA9DTxSuRTJC4lCGAg4/0v+uPeYaSquEKwuoi+hlVyb6gQ9Pparr/ioZ0m1xQP0Dgvo4CrIFL9BW+XkrWxWRcX3TVprX"
    b"O5BFNimlXDI20R548YbcHhpoE1sedBQztL8pMHzQKiFQHuYHPNZLCcj/q9oMTZcmlvclkXP4FV2CxC6a0gdGJ3OhuIAH1fybvius"
    b"BHGzkpYztNpHyuvLa6QJw3YYxGeMaPNe0gY/rSlKApgLYZKyU+/Llf+yTaD8Rz0K5u8kYssYFWuwG7YEs+ApchU7xBSuUsywJZQE"
    b"Wkjyju40SeZiUnAxkGyIsyhT9jOuGwzMQlemiLj244dSAp0p/2ux8AtUEonjU2geBejz+MIs7SZ8Hp6K8xXELOdgSFeUvzuOOVrK"
    b"Z4GslgoAPt+ENJ4NsJKchnrYtfTEMJmdVBIL//QK5nyxpKC0XfdyKtOSlr0VC5LgmRCjOBQILDmBLz9JNtdEKPcpO3JMtGVv5/9e"
    b"MDbnNKbYQ1DfVmcrsxHdYDtLbOBddP55bTKTnaokRREW1oGhldRh6AJMz7xTZwOr4yyuA4MA8iCLRy8qJCdTsOetR6OXutXsVHqY"
    b"sbdfEhA3fsRm8a4QJEQAbkIygvkgsY/VyMCuna7BuTCFP3nv6V2xCQ+wHzToupJTyPtmucFBRViNV1C/L2nI92VHbL0hG37tozqR"
    b"STtTvqdBY9bdt6qoAADPp1E6wdpf3AAB4y23dgAAhTQNurHEZ/sCAAAAAARZWg=="
))

INSTALLER_V040 = lzma.decompress(base64.b64decode(
    b"/Td6WFoAAATm1rRGAgAhARYAAAB0L+Wj4A1UBq1dABGIQkeKIzPDdw8z/VWX7afG1TtMjxXpQsg+dBWsTnInIaaojqnerPjybjd4"
    b"Ll6L8kURqEVyRvVJtKI7VSZcE5Q0wTTRNA7JB7EdnqtYfv1A09vKl5DnEzbeP8y+Qbwk4svDXXmtD2+eTNSyI3jWHtEngzLSLzYI"
    b"koVi1PQfCrSl506GoYMJgF6p0VT92S4xGCHkMzhxokUhewemt/JKKdcW5UT7WOlwK67ZtohVDBnRHBfafxEKwGGMFVjgpzent6QM"
    b"ouBCI/bGjs6NCBJhJsh5S2vX47LHqBfL/ZJP07zY1HbKaTzMjS9EqLVDPuI4VqWliNNsh3FwQXvwUGodqtI3Usf32zLRd349YvCK"
    b"Ml9NNOm9oIdrJau8wyrHr+HncmXiqI4xXv7OYEzWp2wAZ1+tdzcbcMwov72J2Si/rx9oQJdVL+xvU4htYZjpOeNE+Ma8dxSxtbYj"
    b"ZnrXoSKowCM8Oo9K8qNIflBYCuZjF2v1JOwp49KRsiEP4tUonMyKWWzDBugzQ2zW6SutUf1Wmq9GcWSEYiSRKwGcBlhi7maoQIvF"
    b"ZzyC9HazrSjqEuAxk12iK9Q97RTRjP0+ntyNGBUpjKX8e1L3/ExPMrn/iufBRYdAUpMhvn9LRgpvHNTxvWUA7QtTMfZGcEmtAmJn"
    b"dRzexVLlykdC36UOjZVF0Nj6TRO8vvwyRLrXm5iFeit10I7v9rK3u6/6HSzh3VG77QySYtICpwPDRnlTmmnRBfv5tGus+bJq51t7"
    b"PZAQq7EE95B5RwgYaVtnSHOXZjQHP+PxiL9wlCg/mjC6U7l9s+WhYH6l9kwOZxQzcxAyFLgjvxwWOl5T6eionAWgKxwXgODa8Zq/"
    b"uPGqXJs5E/0pXBbecVg/3e+phwCOoCd+yPI/tdQt3e1OB4ZX4cOF3QXNNEmgjV5vlzjgN200U/Al0THlJ35uBpqiRyVCbw5aVLZE"
    b"tQaSMAIhBksyGU9iRcI6Uv9jxc21jgtKSYRJu59juL9Lk0dK+ariAOR0ZZSz8Ev4rbgzMkvkkb0k3Md7BrSKOyAOnry4AYeX12Ot"
    b"TbwhK0TQipFxriPrtbFbUpTWr+KZLMmr+UIVPthG+CMSHw0HIuMD1WQlvTevQ1yYNJiGdViK/mVNiDFyjI4EGLQcRcJz6mxuarl8"
    b"KIXixjG4mveCcm97tGHbDVXZU838MskW+9qYUzRT0mtASNFhF0c1wwwPw1brRMvwdBL9XHFORQsSqZyo38R/WsXOOCnM4EQcb4y4"
    b"Ahwi4ofJ3s1NPLTZkE1htqu6uQQcYqP4Snzdap+ZtQwszUnPct9b3G2hQe3LvIHo2kFzOtGmw+X57u8+AemRRwUxYQTWynQp33yo"
    b"i5UZyunk1p/udnHUJhQY+mATxiIdFN4Jgz+C9TJ4Af3ztLJEjBkOVg6lK8KGP8D+eJIZ262Y87w6SsfpLkY4LBYyStQI3RbkgIH/"
    b"XAUOlLi19JQqoHxeyMXHmQy1vlKguIU7WIs5FImiNKnnbUqJ3tx5Gz7kiAKGUdXUaWnFJ2MukysXnb92RelnwQwrrHvhP5BKlZv1"
    b"4ePECS9i3QSX4ikzSGdSX9EIPC9/+qDrFDpWEElMl4JDJSlhDYZ56IZKEb2IyZfRNw4ZHXLsce8rSp4nImHhOcuTw4TRfcmRi3q0"
    b"dYKo2QrU8XLJnaPPVfJdcYiJc0Y42SXko01rnJor7mJfu1dLp4caL5VAaywW3/hXZLahI8/QOa8V/y3TT3d0XksXJwbxR6fBwVnU"
    b"a08feSAlT2tuTug+2G0BY3JzxOHvUHJpPLkRS7oBv5SA67cSU8OxKbtJJys/McKiK5Irrixd+rP6IRkvi+lBx91BtvzcHobUqJol"
    b"b1JIKW6bedkqtzH3dtNWv2dLy0ImrYYKEZ4/KxQz9V7OE56IaR+eJAB7ByBeUZpQISuBNnIpsWg2vCRLpR5Omy9zEtPsd+uU1qA0"
    b"zYvHT5kpcE7CCYLQ5X2YxFLx7twPfFDIHxlyMi+JSkA5kSd14XCmOpohTLEknVT5P3a8Z6btndW+FUd+JH5YkhbsG5VrarOBVFQn"
    b"AAYBJLX/tDi16O2WKWZnRuAS33dayYYm2G06CWBGR2pqlFMbtWD6CCRunGyUPJnYL28YuQhj8QOhRJYpBicg60eBtRdmkU0nset3"
    b"VXuyx4bJrSgQyyRYA5/4EKGSgFwqsEH57CmMM8r7FKx4fxZWMgAk5Lvcald9GhkOzXs65WoeIuAOgLT2Ybk84Yrez7NxC68j9xqG"
    b"3XFdYUyQzyk2+qgS9OWSAAAAALDe4aC6XkBWAAHJDdUaAAAdMBkNscRn+wIAAAAABFla"
))


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
            # GitHub's source archive of the tag: a git archive whose header names the commit.
            subprocess.run(
                ["git", "archive", "--format=tar.gz", f"--prefix=Crewship-{tag[1:]}/", "-o", str(self.mirror / f"src-{tag}.tar.gz"), tag],
                cwd=self.repo,
                check=True,
            )
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in {"curl": CURL_SHIM, "apt-get": "#!/bin/sh\n", "dpkg-query": "#!/bin/sh\nprintf installed\n"}.items():
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(self.home),
            "MIRROR": str(self.mirror),
            # git ls-remote of the GitHub URL reads the local repo, whose tags stand in for the release tags.
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{self.repo}.insteadOf",
            "GIT_CONFIG_VALUE_0": "https://github.com/i098/Crewship",
        }

    def install(self, latest, *args):
        (self.mirror / "latest").write_text(latest)
        return subprocess.run(
            [BASH, "-s", "--", *args],
            input=(ROOT / "scripts/install.sh").read_text(),
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


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize("latest, warns", [("1.1.0", True), ("1.0.0", False), ("0.9.0", False), (None, False), ("offline", False)])
def test_pnpm_release_policy_preserves_the_selected_release(release, tmp_path, latest, warns):
    import json

    launcher = tmp_path / "launcher"
    launcher.mkdir()
    shutil.copyfile(ROOT / "tools/npm/crewship.js", launcher / "crewship.js")
    (launcher / "package.json").write_text('{"version":"1.0.0"}')
    stub = tmp_path / "fetch.js"
    stub.write_text(
        "const fs = require('node:fs');\n"
        "globalThis.fetch = async (url) => {\n"
        "  if (url === 'https://registry.npmjs.org/crewship/latest') {\n"
        + ("    throw new Error('registry unavailable');\n" if latest == "offline" else "")
        + f"    return new Response(JSON.stringify({{version: {json.dumps(latest)}}}));\n"
        "  }\n"
        "  if (!url.endsWith('/v1.0.0/install.sh')) throw new Error(`unexpected URL: ${url}`);\n"
        f"  return new Response(fs.readFileSync({json.dumps(str(ROOT / 'scripts/install.sh'))}, 'utf8'));\n"
        "};\n"
    )
    result = subprocess.run(
        [shutil.which("node"), "--require", str(stub), str(launcher / "crewship.js"), "--with", "none"],
        capture_output=True, text=True, timeout=60,
        env={**release.env, "npm_config_user_agent": "pnpm/12.14.0 npm/? node/v24.0.0 linux x64"},
    )
    assert result.returncode == 0, result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
    assert ("minimumReleaseAge" in result.stdout) is warns
    assert result.stdout.index("Installing Crewship v1.0.0") < result.stdout.index("Crewship v1.0.0 in")



@pytest.mark.parametrize(
    "ref, missing",
    [("v1.0.0", None), (None, None), (None, "curl"), (None, "ca-certificates")],
    ids=["pinned", "resolved", "missing-curl", "missing-ca-certificates"],
)
def test_release_is_announced_before_main_package_setup(release, tmp_path, ref, missing):
    if ref:
        release.env["CREWSHIP_REF"] = ref
    if missing is None:
        (release.home / "https-installed").touch()
    bin_dir = tmp_path / "bin"
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "sudo").chmod(0o755)
    (bin_dir / "apt-get").write_text(
        '#!/bin/sh\n'
        'if [ -f "$HOME/https-installed" ]; then echo MAIN_PACKAGE_SETUP; else echo HTTPS_BOOTSTRAP; fi\n'
        'case "$*" in *install*) touch "$HOME/https-installed" ;; esac\n'
    )
    (bin_dir / "dpkg-query").write_text(
        '#!/bin/sh\n[ "$3" != git ] && [ -f "$HOME/https-installed" ] || exit 1\nprintf installed\n'
    )
    (bin_dir / "curl").write_text(
        '#!/usr/bin/env bash\n[ -f "$HOME/https-installed" ] || exit 127\n' + CURL_SHIM.split("\n", 1)[1]
    )
    if missing == "curl":
        env = tmp_path / "bash-env"
        env.write_text(
            'command() {\n'
            '  if [[ $* == "-v curl" && ! -f "$HOME/https-installed" ]]; then return 1; fi\n'
            '  builtin command "$@"\n'
            '}\n'
        )
        release.env["BASH_ENV"] = str(env)
    result = release.install("v1.1.0" if ref else "v1.0.0")
    assert result.returncode == 0, result.stderr
    assert (release.home / "https-installed").exists()
    assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
    assert result.stdout.index("Installing Crewship v1.0.0") < result.stdout.index("Updating OS packages...")
    assert "MAIN_PACKAGE_SETUP" not in result.stdout
    assert "MAIN_PACKAGE_SETUP" in install_log(result).read_text()
    assert ("HTTPS_BOOTSTRAP" in result.stderr) is (missing is not None)


@pytest.mark.parametrize("status", [0, 23])
def test_install_logs_keep_details_private_on_success_and_failure(release, status):
    assert release.install("v1.0.0").returncode == 0
    (release.crewship / "onboard.sh").write_text(
        f"#!/bin/sh\necho package-details\necho diagnostic-details >&2\nexit {status}\n"
    )
    result = release.install("v1.0.0")
    assert result.returncode == status
    assert "package-details" not in result.stdout + result.stderr
    assert "diagnostic-details" not in result.stdout + result.stderr
    log = install_log(result)
    assert log.stat().st_mode & 0o777 == 0o600
    assert log.parent == release.home / ".local/state/crewship-install"
    assert "package-details\n" in log.read_text()
    assert "diagnostic-details\n" in log.read_text()


def terminal_install(release, responses):
    pid, terminal = pty.fork()
    if pid == 0:
        termios.tcsetwinsize(0, (40, 120))
        os.execve(BASH, [BASH, str(ROOT / "scripts/install.sh")], release.env)
    output = b""
    deadline = time.monotonic() + 20
    status = None
    responses = dict(responses)
    try:
        while True:
            ready, _, _ = select.select([terminal], [], [], max(0, deadline - time.monotonic()))
            assert ready, f"The installer did not exit:\n{output.decode(errors='replace')}"
            try:
                chunk = os.read(terminal, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
            if not chunk:
                break
            output += chunk
            for prompt, answer in list(responses.items()):
                if prompt in output:
                    os.write(terminal, answer)
                    del responses[prompt]
        _, status = os.waitpid(pid, 0)
    finally:
        os.close(terminal)
        if status is None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
    assert not responses, output.decode(errors="replace")
    return subprocess.CompletedProcess(
        [], os.waitstatus_to_exitcode(status), output.decode(errors="replace"), ""
    )


@pytest.mark.parametrize("status", [0, 23])
def test_terminal_install_drains_output_before_exit(release, tmp_path, status):
    assert release.install("v1.0.0").returncode == 0
    (release.crewship / "ship.sh").write_text(
        SHIP + f'\nif [ "$1" = launch ]; then\n'
        '  echo terminal-output\n'
        '  echo terminal-error >&2\n'
        f'  exit {status}\nfi\n'
    )
    tee = tmp_path / "bin/tee"
    tee.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys, time\n"
        "data = sys.stdin.buffer.read()\n"
        "time.sleep(0.1)\n"
        f"sys.exit(subprocess.run([{shutil.which('tee')!r}, *sys.argv[1:]], input=data).returncode)\n"
    )
    tee.chmod(0o755)
    result = terminal_install(release, {})
    assert result.returncode == status, result.stdout
    log = install_log(result)
    footer = f"Full install log: {log}"
    assert result.stdout.count(footer) == 1
    assert log.read_text().count(footer) == 1
    assert result.stdout.index("Installing repository tools...") < result.stdout.index(footer)
    assert result.stdout.index("terminal-output") < result.stdout.index(footer)
    assert result.stdout.count("terminal-error") == 1
    assert log.read_text().count("terminal-output") == 1
    assert log.read_text().count("terminal-error") == 1
    assert ("Crewship installation failed" in result.stdout) == bool(status)


def test_interrupt_during_package_lock_wait_does_not_hang(release, tmp_path):
    assert release.install("v1.0.0").returncode == 0
    (release.home / "calls").unlink()
    bin_dir = tmp_path / "bin"
    for name, body in {
        "dpkg-query": "#!/bin/sh\nexit 1\n",
        "sudo": '#!/bin/sh\nexec "$@"\n',
        "apt-get": "#!/bin/sh\necho 'E: Could not get lock /var/lib/apt/lists/lock'\nexit 100\n",
        "sleep": "#!/bin/sh\necho ready-to-interrupt >/dev/tty\nexec /bin/sleep 60\n",
    }.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    result = terminal_install(release, {b"ready-to-interrupt": b"\x03"})
    assert result.returncode == -signal.SIGINT, result.stdout
    assert not (release.home / "calls").exists()


@pytest.mark.parametrize("question_status", [0, 17])
def test_install_questions_keep_terminal_and_capture_output(release, question_status):
    assert release.install("v1.0.0").returncode == 0
    config = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    config["crewship"].update(
        home=str(release.home), user=ship.pwd.getpwuid(os.getuid()).pw_name,
        workspace=str(release.home / "Dev"),
    )
    config["crewship"]["profiles"]["firstmate"] = True
    config["crewship"]["firstmate"].pop("checklist", None)
    (release.crewship / ".local/host.yml").write_text(yaml.safe_dump(config))
    (release.home / "Dev/firstmate").mkdir(parents=True)
    omp = release.home / ".local/bin/omp"
    omp.parent.mkdir(parents=True)
    omp.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "if sys.argv[1:] == ['models', '--json']:\n"
        "    print('{\"models\": [{\"id\": \"test\"}]}')\n"
        "    sys.exit(0)\n"
        "assert all(os.isatty(fd) for fd in (0, 1, 2)), 'missing terminal'\n"
        "assert all(os.get_terminal_size(1)), 'missing terminal size'\n"
        "home = pathlib.Path(os.environ['HOME'])\n"
        "assert pathlib.Path.cwd() == home / 'Dev/firstmate'\n"
        "answer = input('Choose a host name: ')\n"
        "(home / 'answer').write_text(answer)\n"
        "print('Configured host: ' + answer, flush=True)\n"
        "print('Question diagnostic', file=sys.stderr, flush=True)\n"
        f"sys.exit({question_status})\n"
    )
    omp.chmod(0o755)
    (release.crewship / "ship.sh").write_text(
        f"#!{sys.executable}\n"
        "import importlib.util, pathlib, sys\n"
        "if sys.argv[1] != 'launch':\n"
        "    sys.exit(0)\n"
        f"spec = importlib.util.spec_from_file_location('ship', {str(ROOT / 'scripts/ship.py')!r})\n"
        "ship = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(ship)\n"
        "ship.provision = lambda document, check: 0\n"
        "ship.load_config = lambda path: ship.yaml.safe_load(path.read_text())\n"
        "config = pathlib.Path(__file__).parent / '.local/host.yml'\n"
        "sys.argv = [sys.argv[0], 'launch', '--config', str(config)]\n"
        "sys.exit(ship.main())\n"
    )
    result = terminal_install(release, {b"Choose a host name: ": b"test-host\n"})
    assert result.returncode == 0, result.stdout
    assert (release.home / "answer").read_text() == "test-host"
    log = install_log(result)
    assert log.stat().st_mode & 0o777 == 0o600
    for message in ("Configured host: test-host", "Question diagnostic"):
        assert message in result.stdout
        assert log.read_text().count(message) == 1
    marker = release.home / ".local/share/crewship/new-host-questions-done"
    assert marker.exists() == (question_status == 0)
    assert (f"omp exited {question_status}" in result.stdout) == bool(question_status)


@pytest.mark.parametrize("cache_state", ["present", "recreated", "home-conflict", "system-conflict"])
def test_install_preserves_legacy_state_and_cache_during_migration(release, tmp_path, cache_state):
    assert release.install("v1.0.0").returncode == 0
    for directory in ((".local/state", ".cache") if cache_state == "present" else (".local/state",)):
        old = release.home / directory / "code-factory"
        old.mkdir(parents=True)
        (old / "data").write_text(directory)
    system_old = tmp_path / "system/code-factory"
    system_new = tmp_path / "system/crewship"
    system_old.parent.mkdir()
    if cache_state == "present":
        system_old.mkdir()
        (system_old / "data").write_text("system")
    conflict = {
        "home-conflict": release.home / ".cache/crewship",
        "system-conflict": system_new,
    }.get(cache_state)
    if conflict:
        conflict.mkdir(parents=True)
        (conflict / "data").write_text("keep")
    units = release.home / ".config/systemd/user"
    units.mkdir(parents=True)
    for unit in ("herdr-spaces.timer", "herdr-spaces.service"):
        (units / unit).touch()
    shutdown = tmp_path / "shutdown.py"
    shutdown.write_text(
        "import pathlib, sys\n"
        f"state = pathlib.Path({str(release.home / '.local/state/code-factory')!r})\n"
        "if sys.argv[1] != 'herdr-spaces.service' or not state.exists():\n"
        "    sys.exit(0)\n"
        f"for name, data in {[(str(release.home / '.cache/code-factory'), '.cache'), (str(system_old), 'system')]!r}:\n"
        "    path = pathlib.Path(name)\n"
        "    if not path.exists():\n"
        "        path.mkdir(parents=True)\n"
        "        (path / 'data').write_text(data)\n"
    )
    migration = yaml.safe_load((ROOT / "blueprint/ansible/tasks/rename.yml").read_text())[0]
    migration["vars"]["crewship_renamed_paths"] = [
        pair for pair in migration["vars"]["crewship_renamed_paths"]
        if pair[0].endswith(("/.local/state/code-factory", "/.cache/code-factory"))
    ] + [[str(system_old), str(system_new)]]
    tasks = migration["block"]
    stop = next(task for task in tasks if task["name"] == "Stop the units that use the pre-rename paths")
    del stop["ansible.builtin.systemd_service"]
    stop["ansible.builtin.command"] = {
        "argv": [sys.executable, str(shutdown), "{{ item.item }}"],
    }
    stop["changed_when"] = False
    last_move = next(
        index for index, task in enumerate(tasks)
        if task["name"] == "Move the pre-rename system paths to their new names"
    )
    migration["block"] = tasks[:last_move + 1]
    playbook = tmp_path / "migration.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {
            "ansible_become": False, "ansible_python_interpreter": sys.executable,
            "crewship_become_target": False,
            "crewship_cfg": {"home": str(release.home), "user": getpass.getuser()},
            "crewship_share_dir": str(release.home / ".local/share/crewship"),
            "crewship_path_checker": str(ROOT / "scripts/check_paths.py"),
            "crewship_user_units": str(units),
            "crewship_manage_services": True, "crewship_user_systemd_env": {},
        },
        "tasks": [migration],
    }]))
    (release.crewship / "ship.sh").write_text(
        SHIP + '\ncase $1 in\n'
        '  launch) set -- ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
        f'exec "{Path(sys.executable).parent / "ansible-playbook"}"'
        f' -i localhost, "{playbook}" "$@"\n'
    )
    release.env["ANSIBLE_PIPELINING"] = "1"
    result = release.install("v1.0.0")
    if conflict:
        assert result.returncode != 0
        assert f"{conflict.parent / 'code-factory'} and {conflict}" in install_log(result).read_text()
        assert (conflict / "data").read_text() == "keep"
        assert (release.home / ".local/state/code-factory/data").read_text() == ".local/state"
        assert (release.home / ".cache/code-factory/data").read_text() == ".cache"
        assert (system_old / "data").read_text() == "system"
        return
    assert result.returncode == 0, install_log(result).read_text()
    for directory in (".local/state", ".cache"):
        assert not (release.home / directory / "code-factory").exists()
        assert (release.home / directory / "crewship/data").read_text() == directory
    assert not system_old.exists()
    assert (system_new / "data").read_text() == "system"
    assert install_log(result).stat().st_mode & 0o777 == 0o600
    repeated = release.install("v1.0.0")
    assert repeated.returncode == 0, install_log(repeated).read_text()
    assert "changed=0" in install_log(repeated).read_text()


@pytest.mark.parametrize("password_required", [False, True])
def test_install_routes_apply_output(release, tmp_path, password_required):
    assert release.install("v1.0.0").returncode == 0
    (release.crewship / "ship.sh").write_text(
        f"#!{sys.executable}\n"
        "import importlib.util, os, sys\n"
        "if sys.argv[1] != 'launch':\n"
        "    sys.exit(0)\n"
        f"spec = importlib.util.spec_from_file_location('ship', {str(ROOT / 'scripts/ship.py')!r})\n"
        "ship = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(ship)\n"
        "ship.os.geteuid = lambda: 1000\n"
        "ship.sys.stdin.isatty = lambda: True\n"
        "sys.exit(ship.provision({'crewship': {'home': os.environ['HOME']}}, False))\n"
    )
    bin_dir = tmp_path / "bin"
    (bin_dir / "sudo").write_text(f"#!/bin/sh\nexit {int(password_required)}\n")
    (bin_dir / "sudo").chmod(0o755)
    ansible = bin_dir / "ansible-playbook"
    ansible.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "assert ('--ask-become-pass' in sys.argv) == (os.environ['PASSWORD_REQUIRED'] == '1')\n"
        "print('apply-details')\n"
        "print('apply-diagnostic', file=sys.stderr)\n"
    )
    ansible.chmod(0o755)
    release.env["PASSWORD_REQUIRED"] = str(int(password_required))
    result = release.install("v1.0.0")
    log = install_log(result).read_text()
    assert result.returncode == 0, log
    for stream in ("details", "diagnostic"):
        message = f"apply-{stream}"
        assert log.count(message) == 1
        assert (message in result.stdout + result.stderr) == password_required



@pytest.mark.parametrize("failure", ["lock", "timeout", "frontend-timeout", "package"])
def test_package_failures_wait_only_for_locks(release, tmp_path, failure):
    release.env["CREWSHIP_REF"] = "v1.0.0"
    bin_dir = tmp_path / "bin"
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "sudo").chmod(0o755)
    (bin_dir / "dpkg-query").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "apt-get").write_text(
        "#!/usr/bin/python3\n"
        "import os, pathlib, sys\n"
        "failure = os.environ['FAILURE']\n"
        "if failure == 'frontend-timeout' and 'install' not in sys.argv:\n"
        "    sys.exit(0)\n"
        "calls = pathlib.Path(os.environ['HOME']) / 'apt-calls'\n"
        "previous = calls.read_text() if calls.exists() else ''\n"
        "with calls.open('a') as log:\n"
        "    log.write(' '.join(sys.argv[1:]) + '\\n')\n"
        "if not previous or failure in ('timeout', 'frontend-timeout'):\n"
        "    message = 'Could not get lock /var/lib/apt/lists/lock'\n"
        "    if os.environ['FAILURE'] == 'package':\n"
        "        message = 'Unable to locate package missing'\n"
        "    if failure == 'frontend-timeout':\n"
        "        message = 'Unable to acquire the dpkg frontend lock (/var/lib/dpkg/lock-frontend), is another process using it?'\n"
        "    print('E: ' + message, file=sys.stderr)\n"
        "    sys.exit(100)\n"
    )
    release.env["FAILURE"] = failure
    if failure.endswith("timeout"):
        bash_env = tmp_path / "bash-env"
        bash_env.write_text("sleep() { SECONDS=1000000; }\n")
        release.env["BASH_ENV"] = str(bash_env)

    result = release.install("v1.0.0")

    calls = (release.home / "apt-calls").read_text().splitlines()
    if failure == "lock":
        assert result.returncode == 0, result.stderr
        assert len(calls) == 3
        assert (release.home / "calls").read_text().split()[-1] == "launch"
    else:
        assert result.returncode == 100
        assert not release.crewship.exists()
        if failure.endswith("timeout"):
            assert "package locks did not clear within 600 seconds" in install_log(result).read_text()
        else:
            assert "Unable to locate package missing" in install_log(result).read_text()
            assert len(calls) == 1


def test_update_keeps_host_files_and_removes_the_replaced_release(release):
    assert release.install("v1.0.0").returncode == 0
    (release.crewship / ".local/host.yml").write_text("mine\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.1.0").resolve()
    assert (release.crewship / "VERSION").read_text() == "1.1.0"
    assert (release.crewship / ".local/host.yml").read_text() == "mine\n"
    assert [p.name for p in release.releases.iterdir()] == ["v1.1.0"]


def test_bad_checksum_leaves_the_install_untouched(release):
    assert release.install("v1.0.0").returncode == 0
    (release.mirror / "crewship-v1.1.0.tar.gz.sha256").write_text(f"{'0' * 64}  crewship-v1.1.0.tar.gz\n")
    result = release.install("v1.1.0")
    assert result.returncode != 0
    assert "does not match its .sha256" in result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
    assert [p.name for p in release.releases.iterdir()] == ["v1.0.0"]


def test_release_without_artifact_installs_the_verified_source_archive(release):
    for name in ("crewship-v1.1.0.tar.gz", "crewship-v1.1.0.tar.gz.sha256"):
        (release.mirror / name).unlink()
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert "has no install artifact; using GitHub's source archive" in result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.1.0").resolve()
    assert (release.crewship / "VERSION").read_text() == "1.1.0"
    assert not (release.crewship / ".git").exists()


def test_source_archive_of_another_commit_is_refused(release):
    (release.mirror / "crewship-v1.1.0.tar.gz").unlink()
    # The v1.0.0 archive under the v1.1.0 name: a different commit than the tag's.
    (release.mirror / "src-v1.1.0.tar.gz").write_bytes((release.mirror / "src-v1.0.0.tar.gz").read_bytes())
    result = release.install("v1.1.0")
    assert result.returncode != 0
    assert "refusing to install" in result.stderr
    assert not release.crewship.exists()


@pytest.fixture
def legacy_release(release, tmp_path):
    approved = release.mirror / "crewship-v0.4.7.tar.gz"
    with tarfile.open(approved, "w:gz") as archive:
        member = tarfile.TarInfo("crewship-v0.4.7/install.sh")
        member.size = len(INSTALLER_V047)
        archive.addfile(member, io.BytesIO(INSTALLER_V047))
    digest = hashlib.sha256(approved.read_bytes()).hexdigest()
    approved.with_name(approved.name + ".sha256").write_text(f"{digest}  {approved.name}\n")
    (release.repo / "install.sh").write_bytes(INSTALLER_V040)
    (release.repo / "VERSION").write_text("0.4.0")
    git(release.repo, "add", "-A")
    git(release.repo, "commit", "-qm", "Legacy release with its cloning installer")
    git(release.repo, "tag", "v0.4.0")
    subprocess.run(
        ["git", "archive", "--format=tar.gz", "--prefix=Crewship-0.4.0/",
         "-o", str(release.mirror / "src-v0.4.0.tar.gz"), "v0.4.0"],
        cwd=release.repo, check=True,
    )
    wrapper = tmp_path / "bin/git"
    wrapper.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >>"$HOME/git-calls"\n'
        'if [ "$1" = clone ]; then echo "legacy clone called" >&2; exit 99; fi\n'
        f'exec {shutil.which("git")} "$@"\n'
    )
    wrapper.chmod(0o755)
    release.env.update(TMPDIR=str(tmp_path), CURL_REQUESTS=str(tmp_path / "requests"))
    return release


@pytest.mark.parametrize(
    ("archive_kind", "existing", "repo", "failure"),
    [
        ("source", False, "i098/Crewship", ""),
        ("artifact", False, "i098/Crewship", ""),
        ("source", True, "i098/Crewship", ""),
        ("artifact", True, "example/fork", ""),
        ("source", False, "example/fork", ""),
        ("source", True, "i098/Crewship", "other-commit"),
        ("source", True, "i098/Crewship", "tree"),
        ("source", False, "i098/Crewship", "missing-git"),
        ("artifact", True, "i098/Crewship", "checksum"),
        ("artifact", True, "i098/Crewship", "missing-checksum"),
    ],
)
def test_public_bootstrap_installs_legacy_archive(
    legacy_release, tmp_path, archive_kind, existing, repo, failure,
):
    release = legacy_release
    private = {
        ".local/host.yml": "crewship: {}\n",
        ".local/token": "private-token",
        "blueprint/skills/private/local.md": "private-skill",
        "blueprint/rules/private/local.md": "private-rule",
    }
    if existing:
        assert release.install("v1.0.0").returncode == 0
        for name, content in private.items():
            path = release.crewship / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (release.home / "args").unlink()
    release.env.update(CREWSHIP_REF="v0.4.0", CREWSHIP_REPO=repo,
                       GIT_CONFIG_VALUE_0=f"https://github.com/{repo}")
    source = release.mirror / "src-v0.4.0.tar.gz"
    if failure in {"other-commit", "tree"}:
        ref = "v1.1.0" if failure == "other-commit" else "v0.4.0^{tree}"
        subprocess.run(
            ["git", "archive", "--format=tar.gz", "--prefix=Crewship-0.4.0/",
             "-o", str(source), ref], cwd=release.repo, check=True,
        )
    if archive_kind == "artifact":
        artifact = release.mirror / "crewship-v0.4.0.tar.gz"
        artifact.write_bytes(source.read_bytes())
        if failure != "missing-checksum":
            digest = "0" * 64 if failure == "checksum" else hashlib.sha256(artifact.read_bytes()).hexdigest()
            artifact.with_name(artifact.name + ".sha256").write_text(f"{digest}  {artifact.name}\n")
    if failure == "missing-git":
        (tmp_path / "bin/dpkg-query").write_text(
            '#!/bin/sh\n'
            '[ "$3" != git ] || [ -f "$HOME/git-installed" ] || exit 1\nprintf installed\n'
        )
        (tmp_path / "bin/apt-get").write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >>"$HOME/packages"\ntouch "$HOME/git-installed"\n'
        )
        sudo = tmp_path / "bin/sudo"
        sudo.write_text('#!/bin/sh\nexec "$@"\n')
        sudo.chmod(0o755)
    result = install(release.env, "--container")
    if failure in {"other-commit", "tree", "checksum", "missing-checksum"}:
        assert result.returncode != 0
        assert "refusing to install" in result.stderr
        assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
        assert not (release.home / "args").exists()
    else:
        assert result.returncode == 0, result.stderr
        assert release.crewship.resolve() == (release.releases / "v0.4.0").resolve()
        assert (release.crewship / "VERSION").read_text() == "0.4.0"
        assert (release.crewship / "install.sh").read_bytes() == INSTALLER_V040
        assert not (release.crewship / ".git").exists()
        expected = ["inspect", "launch"] if existing else ["dock --container", "inspect", "launch"]
        assert (release.home / "args").read_text().splitlines() == expected
        repeated = install(release.env, "--container")
        assert repeated.returncode == 0, repeated.stderr
        assert (release.crewship / "install.sh").read_bytes() == INSTALLER_V040
        if failure == "missing-git":
            packages = (release.home / "packages").read_text().splitlines()
            assert len(packages) == 2
            assert packages[0].endswith("update -q")
            assert packages[1].endswith("install -y -q git")
    if existing:
        assert all((release.crewship / name).read_text() == content for name, content in private.items())
    assert "legacy clone called" not in result.stderr
    calls = release.home / "git-calls"
    assert not calls.exists() or not any(line.startswith("clone ") for line in calls.read_text().splitlines())
    urls = (tmp_path / "requests").read_text().splitlines()
    assert f"https://github.com/{repo}/releases/download/v0.4.0/crewship-v0.4.0.tar.gz" in urls
    assert "https://github.com/i098/Crewship/releases/download/v0.4.7/crewship-v0.4.7.tar.gz" in urls
    assert not any("raw.githubusercontent.com" in url or "/main/" in url for url in urls)


def test_public_bootstrap_updates_a_legacy_release(legacy_release):
    release = legacy_release
    release.env["CREWSHIP_REF"] = "v0.4.0"
    assert install(release.env).returncode == 0
    (release.crewship / ".local/token").write_text("keep-token")
    release.env["CREWSHIP_REF"] = ""
    (release.mirror / "latest").write_text("v1.1.0")
    result = install(release.env, "update")
    assert result.returncode == 0, result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.1.0").resolve()
    assert (release.crewship / "VERSION").read_text() == "1.1.0"
    assert (release.crewship / ".local/token").read_text() == "keep-token"
    assert not (release.releases / "v0.4.0").exists()


def test_unknown_release_is_an_error_and_never_clones(release):
    result = release.install("v9.9.9")
    assert result.returncode != 0
    assert "no release v9.9.9" in result.stderr
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


@pytest.mark.parametrize("old_layout", ["", "blueprint/"], ids=["before-blueprint", "blueprint"])
@pytest.mark.parametrize("from_git", [False, True], ids=["release", "git-clone"])
def test_update_carries_private_skills_and_rules_into_the_blueprint(release, old_layout, from_git):
    if from_git:
        subprocess.run(["git", "clone", "-q", str(release.repo), str(release.crewship)], check=True)
    else:
        assert release.install("v1.0.0").returncode == 0
    for kind, name in (("skills", "mine/SKILL.md"), ("rules", "mine.md")):
        path = release.crewship / f"{old_layout}{kind}/private/{name}"
        path.parent.mkdir(parents=True)
        path.write_text(f"{kind}\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert (release.crewship / "blueprint/skills/private/mine/SKILL.md").read_text() == "skills\n"
    assert (release.crewship / "blueprint/rules/private/mine.md").read_text() == "rules\n"
    assert not (release.crewship / "skills").exists() and not (release.crewship / "rules").exists()


def test_v040_host_is_migrated_before_the_reapply(release):
    assert release.install("v1.0.0").returncode == 0
    # What v0.4.0 left: tools under share/code-factory linked from ~/.local/bin, and removed fleet keys.
    old = release.home / ".local/share/code-factory/tools/uv/1/linux"
    old.mkdir(parents=True)
    (old / "uv").write_text("x")
    bin_dir = release.home / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "uv").symlink_to(old / "uv")
    (bin_dir / "mine").write_text("not ours")
    host = release.crewship / ".local/host.yml"
    host.write_text("factory:\n  home: /h\n  fleet:\n    supabase_project_id: a\n    fixture_archive: b\n    worktree_pools: [c]\n    keep: 1\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert not (bin_dir / "uv").exists() and not (bin_dir / "uv").is_symlink()
    assert (bin_dir / "mine").read_text() == "not ours"
    assert (old / "uv").read_text() == "x"
    assert "factory:\n  home: /h\n  fleet:\n    keep: 1\n" == host.read_text()
    assert "supabase_project_id" in (host.parent / "host.yml.v0.4.0").read_text()


def test_failed_link_migration_stops_before_reapplying(release, tmp_path):
    assert release.install("v1.0.0").returncode == 0
    old = release.home / ".local/share/code-factory/tools/uv/1/linux"
    old.mkdir(parents=True)
    (old / "uv").write_text("x")
    links = release.home / ".local/bin"
    links.mkdir(parents=True)
    link = links / "uv"
    link.symlink_to(old / "uv")
    env = tmp_path / "bash-env"
    env.write_text(
        'rm() {\n'
        '  if [[ $# == 2 && $1 == -f && $2 == "$FAILED_LINK" ]]; then return 73; fi\n'
        '  command rm "$@"\n'
        '}\n'
    )
    release.env.update(BASH_ENV=str(env), FAILED_LINK=str(link))
    result = release.install("v1.1.0")
    assert result.returncode == 73
    assert link.is_symlink()
    assert (release.home / "calls").read_text().split().count("launch") == 1


def test_update_installs_the_newest_release_and_passes_options_to_dock(release):
    assert release.install("v1.0.0", "update", "--container").returncode == 0
    assert (release.home / "args").read_text().splitlines()[0] == "dock --container"
    (release.crewship / ".local/host.yml").write_text("mine\n")
    result = release.install("v1.1.0", "update", "--container")
    assert result.returncode == 0, result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.1.0").resolve()
    assert (release.crewship / ".local/host.yml").read_text() == "mine\n"


def test_with_goes_to_dock_for_a_new_host_and_is_refused_for_an_existing_one(release):
    assert release.install("v1.0.0", "--with=docker,chat").returncode == 0
    assert (release.home / "args").read_text().splitlines()[0] == "dock --with=docker,chat"
    (release.crewship / ".local").mkdir(exist_ok=True)
    (release.crewship / ".local/host.yml").write_text("mine\n")
    result = release.install("v1.1.0", "update", "--with", "docker")
    assert result.returncode == 1
    assert "--with applies to a new host config" in result.stderr
    assert (release.crewship / ".local/host.yml").read_text() == "mine\n"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize(
    "location, status, output",
    [
        ("https://github.com/i098/Crewship/releases/tag/v1.1.0", 0, "ref=v1.1.0 args=--container"),
        ("https://github.com/i098/Crewship/releases", 1, "no release found"),
        ("", 1, "no release found"),
    ],
)
def test_launcher_update_runs_the_install_of_the_latest_tag(tmp_path, location, status, output):
    stub = tmp_path / "fetch.js"
    stub.write_text(
        "const location = process.env.LATEST_LOCATION;\n"
        "globalThis.fetch = async (url, options) => {\n"
        "  if (url.endsWith('/releases/latest')) {\n"
        "    if (options?.redirect !== 'manual') throw new Error('redirect not manual');\n"
        "    return new Response(null, { status: 302, headers: location ? { location } : {} });\n"
        "  }\n"
        "  const ref = url.split('/')[5];\n"
        "  return new Response(`echo \"ref=$CREWSHIP_REF args=$*\"; echo \"url-ref=${ref}\"`);\n"
        "};\n"
    )
    result = subprocess.run(
        [shutil.which("node"), "--require", str(stub), str(ROOT / "tools/npm/crewship.js"), "update", "--container"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LATEST_LOCATION": location},
        timeout=10,
    )
    assert result.returncode == status
    assert output in result.stdout + result.stderr
    if status == 0:
        assert "url-ref=v1.1.0" in result.stdout


def test_v040_links_are_relinked_when_home_is_a_symlink(release, tmp_path):
    assert release.install("v1.0.0").returncode == 0
    old = release.home / ".local/share/code-factory/tools/uv/1/linux"
    old.mkdir(parents=True)
    (old / "uv").write_text("x")
    (release.home / ".local/bin").mkdir(parents=True, exist_ok=True)
    (release.home / ".local/bin/uv").symlink_to(old / "uv")
    alias = tmp_path / "home-alias"
    alias.symlink_to(release.home)
    release.env["HOME"] = str(alias)
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert not (alias / ".local/bin/uv").is_symlink()


def test_migration_is_a_noop_on_a_current_host(release):
    assert release.install("v1.0.0").returncode == 0
    host = release.crewship / ".local/host.yml"
    host.write_text("crewship:\n  fleet:\n    keep: 1\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert host.read_text() == "crewship:\n  fleet:\n    keep: 1\n"
    assert not (host.parent / "host.yml.v0.4.0").exists()
