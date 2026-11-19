"""The supervisor's duplicate guard: fm-claim, installed by the ansible task exactly as the host gets it."""

import shutil
import subprocess

import yaml
from test_imessage import ROOT


def installed(tmp_path):
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/imessage.yml").read_text())
    task = next(t for t in tasks if t.get("name") == "Install the iMessage commands")
    for name in task["loop"]:
        shutil.copy(ROOT / "apps/imessage" / name, tmp_path / name)
    return tmp_path / "fm-claim"


def claim(cmd, claims, actor, *args):
    env = {
        "PATH": "/usr/bin:/bin:" + shutil.which("bun").rsplit("/", 1)[0],
        "FM_IMESSAGE_CLAIMS": str(claims),
        "FM_CLAIM_ACTOR": actor,
    }
    return subprocess.run(
        [str(cmd), *args], env=env, capture_output=True, text=True, timeout=30
    ).returncode


def test_installed_fm_claim_lets_only_one_actor_take_an_owner_text(tmp_path):
    (tmp_path / "bin").mkdir()
    cmd = installed(tmp_path / "bin")
    claims = tmp_path / "claims"
    assert claim(cmd, claims, "desk", "msg", "t1") == 0
    assert claim(cmd, claims, "firstmate", "msg", "t1") == 3
    assert claim(cmd, claims, "firstmate", "msg", "t2") == 0
    assert claim(cmd, claims, "desk", "msg", "t2") == 3
    assert claim(cmd, claims, "firstmate", "bad") == 2
