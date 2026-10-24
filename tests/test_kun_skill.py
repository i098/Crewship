import subprocess
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).parents[1]
SHA = "a" * 40


def kun_script(skill_dir):
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/agents.yml").read_text())
    [task] = [t for t in tasks if t["name"].startswith("Install the kun skill")]
    return jinja2.Template(task["ansible.builtin.shell"]).render(kun_skill_dir=skill_dir)


def run(script, tmp_path):
    bin_dir = tmp_path / "bin"
    if not bin_dir.exists():  # stubs: git prints `<sha>\tHEAD` like ls-remote, npx creates the skill dir like `skills add -g`; no gh, as on a fresh host
        bin_dir.mkdir()
        (bin_dir / "git").write_text(f"#!/bin/sh\nprintf '{SHA}\\tHEAD\\n'\n")
        (bin_dir / "npx").write_text(f"#!/bin/sh\nmkdir -p '{tmp_path}/kun' && echo \"$*\" >> '{tmp_path}/npx.log'\n")
        for stub in bin_dir.iterdir():
            stub.chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=True).stdout


def test_kun_installs_once_per_commit_and_skips_a_matching_marker(tmp_path):
    script = kun_script(tmp_path / "kun")
    assert f"kun installed at {SHA}" in run(script, tmp_path)
    assert (tmp_path / "kun/.crewship-sha").read_text() == SHA + "\n"
    assert f"kun already at {SHA}" in run(script, tmp_path)
    [install] = (tmp_path / "npx.log").read_text().splitlines()
    assert f"kunchenguid/kun#{SHA}" in install.split()
    assert "-g" in install.split()
    (tmp_path / "kun/.crewship-sha").write_text("old\n")  # a newer upstream commit reinstalls
    assert "kun installed at" in run(script, tmp_path)
