import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
ANSIBLE = ROOT / "blueprint/ansible"


def apply(tmp_path, tasks, variables, *options, injected_facts="True"):
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": True,
        "vars_files": [str(path) for path in sorted((ANSIBLE / "group_vars/all").glob("*.yml"))],
        "tasks": tasks,
    }]))
    result = subprocess.run(
        [Path(sys.executable).parent / "ansible-playbook", "-i", "localhost,", str(playbook),
         *options,
         "-e", json.dumps({"crewship_repo": str(ROOT),
                           "ansible_python_interpreter": sys.executable, **variables})],
        cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "ANSIBLE_INJECT_FACT_VARS": injected_facts},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[WARNING]" not in result.stderr, result.stderr
    assert "[DEPRECATION WARNING]" not in result.stderr, result.stderr
    return result.stdout


@pytest.mark.parametrize("injected_facts", ["True", "False"])
def test_platform_and_account_use_namespaced_facts(tmp_path, injected_facts):
    preflight = yaml.safe_load((ANSIBLE / "tasks/preflight.yml").read_text())
    tasks = preflight[1:3] + [preflight[-1]]
    tasks.append({"ansible.builtin.assert": {"that": [
        "crewship_platform in ['linux-x86_64', 'linux-aarch64']",
        "crewship_deb_arch in ['amd64', 'arm64']",
        "crewship_tailscale_suite == ansible_facts['distribution_release']",
        "not (crewship_become_target | bool)",
    ]}})
    apply(tmp_path, tasks, {
        "crewship": {"user": getpass.getuser(), "browser_prune": {"enabled": False}},
        "crewship_latest": {"herdr": {"version": "test"}, "omp": "test"},
    }, injected_facts=injected_facts)


@pytest.mark.parametrize("existing", [False, True])
def test_legacy_scans_skip_missing_directories_and_preserve_migration(tmp_path, existing):
    home = tmp_path / "home"
    home.mkdir()
    units = home / ".config/systemd/user"
    ssh = home / ".ssh"
    profile = home / ".profile"
    profile.write_text("# BEGIN code-factory PATH\nkeep this\n# END code-factory PATH\n")
    if existing:
        units.mkdir(parents=True)
        ssh.mkdir()
        (units / "custom.service").write_text("ExecStart=/opt/code-factory/tool\n")
        (ssh / "config").write_text("# BEGIN code-factory SSH\nHost example\n# END code-factory SSH\n")
    migration = yaml.safe_load((ANSIBLE / "tasks/rename.yml").read_text())[0]
    names = {
        "Check for the user unit directory",
        "Find user unit files that name the pre-rename paths",
        "Rewrite the pre-rename paths in user unit files",
        "Check for the SSH directory",
        "Find the pre-rename managed block markers",
        "Rename the managed block markers",
    }
    tasks = [task for task in migration["block"] if task["name"] in names]
    variables = {
        "crewship_cfg": {"home": str(home), "user": getpass.getuser()},
        "crewship_user_units": str(units), "crewship_renamed_word": "code-factory",
    }
    apply(tmp_path, tasks, variables, "--check")
    assert "code-factory" in profile.read_text()
    apply(tmp_path, tasks, variables)
    assert profile.read_text() == "# BEGIN crewship PATH\nkeep this\n# END crewship PATH\n"
    if existing:
        assert (units / "custom.service").read_text() == "ExecStart=/opt/crewship/tool\n"
        assert (ssh / "config").read_text() == "# BEGIN crewship SSH\nHost example\n# END crewship SSH\n"
    else:
        assert not units.exists()
        assert not ssh.exists()
    assert "changed=0" in apply(tmp_path, tasks, variables)
