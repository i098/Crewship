import getpass
import grp
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    home = tmp_path_factory.mktemp("gluttony-install")
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/agents.yml").read_text())
    names = {
        "Inspect the omp extensions directory", "Ensure the omp extensions directory",
        "Install the opt-in gluttony omp extension",
    }
    playbook = home / "install.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars_files": [str(ROOT / "blueprint/ansible/group_vars/all/herdr.yml")],
        "vars": {
            "crewship_cfg": {"home": str(home), "user": getpass.getuser()},
            "crewship_group": grp.getgrgid(os.getgid()).gr_name,
            "crewship_blueprint": str(ROOT / "blueprint"), "ansible_become": False,
        },
        "tasks": [task for task in tasks if task["name"] in names],
    }]))
    for _ in range(2):
        result = subprocess.run(
            [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert "changed=0" in result.stdout
    return home / ".omp/agent/extensions/fm-gluttony.ts"


def run(installed, home, code, *, enabled=True, env=None, context=None):
    if not shutil.which("bun"):
        pytest.skip("needs bun")
    (home / "config").mkdir()
    if enabled:
        (home / "config/gluttony").touch()
    script = f"""
import ext from {json.dumps(str(installed))};
import * as fs from 'node:fs';
const handlers = {{}};
const roles = {{smol: 'original-fast', task: 'original-good', subagent: 'original-sub'}};
const seen = [];
class Spawn {{
  async execute(id, params) {{
    await new Promise(resolve => setTimeout(resolve, 1));
    seen.push([id, roles[params.cli === 'good' ? 'task' : 'smol'], params.prompt]);
    if (id === 'fail') throw new Error('spawn failed');
    return id;
  }}
}}
const host = {{
  Settings: {{instance: {{getModelRole: r => roles[r], overrideModelRoles: r => Object.assign(roles, r)}}}},
  VibeSpawnTool: Spawn,
}};
const api = {{on: (e, f) => handlers[e] = f, pi: host}};
let mode = 'normal';
const ctx = {{
  agent: {{kind: 'main'}}, hasUI: true, model: {{provider: 'anthropic'}},
  sessionManager: {{buildSessionContext: () => ({{mode}}), appendModeChange: m => mode = m}},
  ...{json.dumps(context or {})},
}};
const start = () => handlers.session_start?.({{}}, ctx);
const pick = (id, cli, prompt) => handlers.tool_call?.({{
  toolName: 'vibe_spawn', toolCallId: id, input: {{cli, prompt}},
}});
const spawn = async (id, cli, prompt) => {{
  const result = pick(id, cli, prompt);
  if (result?.block) return result;
  return new Spawn().execute(id, result?.input ?? {{cli, prompt}});
}};
{code}
"""
    result = subprocess.run(
        ["bun", "-e", script], capture_output=True, text=True,
        env={"PATH": os.environ["PATH"], "HOME": str(home), "FM_OMP_HARNESS": "omp",
             "OMP_SKIP_SETUP": "1", "FM_TASK_ID": "sample",
             "FM_TASK_INBOX": str(home / "state/sample.inbox"), **(env or {})},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_installs_without_enabling(installed):
    assert installed.is_file()
    assert installed.stat().st_mode & 0o777 == 0o644
    assert not (installed.parents[3] / "config/gluttony").exists()


@pytest.mark.parametrize("env,context,enabled", [
    ({}, {}, False),
    ({"FM_OMP_HARNESS": "claude"}, {}, True),
    ({"OMP_SKIP_SETUP": "0"}, {}, True),
    ({"FM_TASK_ID": ""}, {}, True),
    ({"FM_TASK_INBOX": ""}, {}, True),
    ({}, {"agent": {"kind": "sub"}}, True),
    ({}, {"hasUI": False}, True),
])
def test_only_opted_in_interactive_crews_enter_vibe(installed, tmp_path, env, context, enabled):
    assert run(installed, tmp_path, """
ext(api); start();
console.log(JSON.stringify([mode, pick('one', 'good', '@model invalid high')]));
""", env=env, context=context, enabled=enabled) == ["normal", None]


def test_switch_is_read_at_start_not_each_turn(installed, tmp_path):
    assert run(installed, tmp_path, """
ext(api); start();
fs.unlinkSync(process.env.FM_TASK_INBOX.replace('state/sample.inbox', 'config/gluttony'));
console.log(JSON.stringify([mode, pick('one', 'good', '@model invalid high').block]));
""") == ["vibe", True]


@pytest.mark.parametrize("provider,cli,prompt,expected", [
    ("anthropic", "fast", "Work", "inception/mercury-3:high"),
    ("anthropic", "fast", "@model anthropic/claude-haiku-5-5 medium\nWork", "anthropic/claude-haiku-5-5:medium"),
    ("anthropic", "good", "@model anthropic/claude-sonnet-5-5 max\r\nWork", "anthropic/claude-sonnet-5-5:max"),
    ("openai-codex", "fast", "@model openai-codex/gpt-6-luna xhigh\nWork", "openai-codex/gpt-6-luna:xhigh"),
    ("openai", "good", "@model openai/gpt-6.1-sol low\nWork", "openai/gpt-6.1-sol:low"),
])
def test_applies_valid_choice_and_strips_directive(installed, tmp_path, provider, cli, prompt, expected):
    result = run(installed, tmp_path, f"""
ext(api); start();
await spawn('one', {json.dumps(cli)}, {json.dumps(prompt)});
console.log(JSON.stringify(seen));
""", context={"model": {"provider": provider}})
    assert result == [["one", expected, "Work"]]


@pytest.mark.parametrize("provider,cli,choice", [
    ("anthropic", "fast", "anthropic/claude-haiku-5-5 low"),
    ("anthropic", "good", "inception/mercury-3 high"),
    ("openai-codex", "fast", "openai-codex/gpt-6-luna max"),
    ("openai-codex", "good", "openai-codex/gpt-6.1-sol high"),
    ("openai-codex", "good", "openai/gpt-6.1-sol medium"),
])
def test_rejects_out_of_set_choices(installed, tmp_path, provider, cli, choice):
    result = run(installed, tmp_path, f"""
ext(api); start();
console.log(JSON.stringify(pick('one', {json.dumps(cli)}, {json.dumps('@model ' + choice + chr(10) + 'Work')})));
""", context={"model": {"provider": provider}})
    assert result["block"] is True
    assert "Allowed:" in result["reason"]


def test_concurrent_spawns_restore_roles_after_failure(installed, tmp_path):
    result = run(installed, tmp_path, """
ext(api); start();
const outcomes = await Promise.allSettled([
  spawn('fail', 'fast', '@model anthropic/claude-haiku-5-5 medium\\nFirst'),
  spawn('two', 'fast', '@model inception/mercury-3 high\\nSecond'),
]);
console.log(JSON.stringify({seen, roles, outcomes: outcomes.map(o => o.status)}));
""")
    assert result == {
        "seen": [["fail", "anthropic/claude-haiku-5-5:medium", "First"],
                 ["two", "inception/mercury-3:high", "Second"]],
        "roles": {"smol": "original-fast", "task": "original-good", "subagent": "original-sub"},
        "outcomes": ["rejected", "fulfilled"],
    }


@pytest.mark.parametrize("provider", ["openai-codex", "openai"])
def test_codex_subagent_roles_use_the_same_provider(installed, tmp_path, provider):
    assert run(installed, tmp_path, """
ext(api); start(); console.log(JSON.stringify(roles));
""", context={"model": {"provider": provider}}) == {
        "smol": f"{provider}/gpt-6-luna:high",
        "task": f"{provider}/gpt-6.1-sol:medium",
        "subagent": f"{provider}/gpt-6.1-sol:medium",
    }


def test_missing_private_api_still_enters_vibe(installed, tmp_path):
    assert run(installed, tmp_path, """
delete api.pi;
ext(api); start();
console.log(JSON.stringify([mode, roles]));
""") == ["vibe", {"smol": "original-fast", "task": "original-good", "subagent": "original-sub"}]
