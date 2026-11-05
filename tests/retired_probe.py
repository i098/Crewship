"""Playbook pieces for tests that run one task file in isolation.

The removal tasks gate on tasks/retired.yml, which site.yml runs once from account.yml;
an isolated playbook runs the probe first and loads the group vars that name the paths.
"""

from pathlib import Path

ROOT = Path(__file__).parents[1]
GROUP_VARS = sorted(str(path) for path in (ROOT / "blueprint/ansible/group_vars/all").glob("*.yml"))
RETIRED = [str(ROOT / "blueprint/ansible/group_vars/all/retired.yml")]
PROBE = {"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/retired.yml")}
