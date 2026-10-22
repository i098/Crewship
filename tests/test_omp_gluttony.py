import getpass
import grp
import json
import os
import resource
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
    package = home / "node_modules/@oh-my-pi/pi-coding-agent"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({
        "type": "module",
        "exports": {"./config/settings": "./config.js", "./session/settings": "./session.js"},
    }))
    (package / "config.js").write_text(
        "export const findScopedSettings = () => globalThis.gluttonSettings;\n"
    )
    (package / "session.js").write_text(
        "export const cfgRetryFallbackChains = {"
        "get: scope => scope.chains, override: (scope, value) => scope.chains = value};\n"
        "export const cfgTierOpenai = {"
        "get: scope => scope.openaiTier, override: (scope, value) => scope.openaiTier = value};\n"
    )
    return home / ".omp/agent/extensions/fm-gluttony.ts"


def limit_bun_files():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))


def run(installed, home, code, *, enabled=True, env=None, context=None):
    if not shutil.which("bun"):
        pytest.skip("needs bun")
    (home / "config").mkdir()
    (home / "tmp").mkdir()
    if enabled:
        (home / "config/gluttony").touch()
    script = f"""
import * as fs from 'node:fs';
const handlers = {{}};
const roles = {{smol: 'original-fast', task: 'original-good', subagent: 'original-sub'}};
const seen = [];
const seenTiers = [];
class Settings {{
  constructor(roles, overrides = {{}}, chains = {{}}, openaiTier = 'priority') {{
    this.roles = roles;
    this.overrides = overrides;
    this.chains = chains;
    this.openaiTier = openaiTier;
  }}
  overlay(values) {{
    return new Settings({{...this.roles, ...values.modelRoles}},
      {{...this.overrides, ...values['task.agentModelOverrides']}}, {{...this.chains}},
      values['tier.openai'] ?? this.openaiTier);
  }}
}}
const settings = new Settings(roles);
class SessionManager {{
  constructor(entries = []) {{ this.entries = entries; }}
  getSessionId() {{ return 'session-one'; }}
  getEntries() {{ return this.entries; }}
  buildSessionContext() {{ return {{mode}}; }}
  appendModeChange(value) {{ mode = value; }}
}}
const sessionManager = new SessionManager();
class Spawn {{
  constructor(session = {{settings, sessionManager}}) {{ this.session = session; }}
  async execute(id, params) {{
    await new Promise(resolve => setTimeout(resolve, 1));
    const agent = params.cli === 'good' ? 'task' : 'sonic';
    const role = params.cli === 'good' ? 'task' : 'smol';
    seen.push([id, this.session.settings.overrides[agent] ??
      this.session.settings.roles[role], params.prompt]);
    seenTiers.push(this.session.settings.openaiTier);
    if (id === 'fail') throw new Error('spawn failed');
    return id;
  }}
}}
const host = {{Settings, VibeSpawnTool: Spawn, SessionManager}};
let thinkingLevel = 'medium';
let defaultCredential = 'test-token';
const credentials = new Map();
const modelRegistry = {{
  find: (provider, id) => ({{provider, id}}),
  getApiKey: async model => {{
    const key = `${{model.provider}}/${{model.id}}`;
    return credentials.has(key) ? credentials.get(key) : defaultCredential;
  }},
}};
const api = {{on: (e, f) => handlers[e] = f, pi: host,
  getThinkingLevel: () => thinkingLevel, setThinkingLevel: value => thinkingLevel = value}};
let mode = 'normal';
const ctx = {{
  agent: {{kind: 'main'}}, hasUI: true, model: {{provider: 'anthropic'}},
  sessionManager,
  modelRegistry,
  ...{json.dumps(context or {})},
}};
const start = () => handlers.session_start?.({{}}, ctx);
const pick = async (id, cli, prompt) => handlers.tool_call?.({{
  toolName: 'vibe_spawn', toolCallId: id, input: {{cli, prompt}},
}}, ctx);
const spawn = async (id, cli, prompt) => {{
  const result = await pick(id, cli, prompt);
  if (result?.block) return result;
  return new Spawn().execute(id, result?.input ?? {{cli, prompt}});
}};
Object.defineProperty(globalThis, 'gluttonSettings', {{get: () => activeSettings}});
let activeSettings = settings;
const {{default: ext}} = await import({json.dumps(str(installed))});
{code}
"""
    result = subprocess.run(
        ["bun", "--no-install", "-e", script], capture_output=True, text=True,
        timeout=20, preexec_fn=limit_bun_files,
        env={"PATH": os.environ["PATH"], "HOME": str(home), "FM_OMP_HARNESS": "omp",
             "TMPDIR": str(home / "tmp"), "BUN_INSTALL_CACHE_DIR": str(home / "tmp/bun-cache"),
             "BUN_RUNTIME_TRANSPILER_CACHE_PATH": "0",
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
ext(api); await start();
console.log(JSON.stringify([mode, await pick('one', 'good', '@model invalid high')]));
""", env=env, context=context, enabled=enabled) == ["normal", None]


def test_switch_is_read_at_start_not_each_turn(installed, tmp_path):
    assert run(installed, tmp_path, """
ext(api); await start();
fs.unlinkSync(process.env.FM_TASK_INBOX.replace('state/sample.inbox', 'config/gluttony'));
console.log(JSON.stringify([mode, (await pick('one', 'good', '@model invalid high')).block]));
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
ext(api); await start();
await spawn('one', {json.dumps(cli)}, {json.dumps(prompt)});
console.log(JSON.stringify(seen));
""", context={"model": {"provider": provider}})
    assert result == [["one", expected, "Work"]]


@pytest.mark.parametrize("provider,cli,choice", [
    ("anthropic", "fast", "anthropic/claude-haiku-5-5 low"),
    ("anthropic", "good", "inception/mercury-3 high"),
    ("anthropic", "good", "anthropic/claude-opus-5-5 medium"),
    ("anthropic", "fast", "anthropic/claude-opus-5-5 high"),
    ("openai-codex", "fast", "openai-codex/gpt-6-luna max"),
    ("openai-codex", "good", "openai-codex/gpt-6.1-sol high"),
    ("openai-codex", "good", "openai/gpt-6.1-sol medium"),
])
def test_rejects_out_of_set_choices(installed, tmp_path, provider, cli, choice):
    result = run(installed, tmp_path, f"""
ext(api); await start();
console.log(JSON.stringify(await pick('one', {json.dumps(cli)}, {json.dumps('@model ' + choice + chr(10) + 'Work')})));
""", context={"model": {"provider": provider}})
    assert result["block"] is True
    assert "Allowed:" in result["reason"]


def test_concurrent_spawns_leave_host_roles_unchanged_after_failure(installed, tmp_path):
    result = run(installed, tmp_path, """
ext(api); await start();
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


def test_reloaded_extension_keeps_worker_model_choices(installed, tmp_path):
    assert run(installed, tmp_path, f"""
ext(api); await start();
const reloadPath = {json.dumps(str(installed.with_name("reloaded.ts")))};
fs.copyFileSync({json.dumps(str(installed))}, reloadPath);
(await import(reloadPath)).default(api); await start();
await spawn('new-session', 'fast', '@model anthropic/claude-haiku-5-5 medium\\nWork');
console.log(JSON.stringify(seen));
""") == [["new-session", "anthropic/claude-haiku-5-5:medium", "Work"]]


@pytest.mark.parametrize("provider", ["anthropic", "openai-codex", "openai"])
@pytest.mark.parametrize("invocation", ["task", "eval"])
@pytest.mark.parametrize("agent,role", [("task", "task"), ("sonic", "smol")])
def test_subagents_bound_overrides_after_role_resolution(
    installed, tmp_path, provider, invocation, agent, role,
):
    result = run(installed, tmp_path, f"""
ext(api); await start();
const result = await handlers.before_subagent_spawn({{
  agent: {json.dumps(agent)}, invocationKind: {json.dumps(invocation)},
  modelRole: {json.dumps(role)}, patterns: ['anthropic/claude-opus-5-5:auto'],
}}, ctx);
console.log(JSON.stringify(result));
""", context={"agent": {"kind": "sub"},
             "model": {"provider": provider, "id": "claude-sonnet-5-5"}, "hasUI": False})
    expected = (
        ("inception/mercury-3:high" if agent == "sonic" else "anthropic/claude-sonnet-5-5:medium")
        if provider == "anthropic" else
        f"{provider}/{'gpt-6-luna:high' if agent == 'sonic' else 'gpt-6.1-sol:medium'}"
    )
    assert result == {"model": expected}


def test_worker_choice_beats_opus_agent_override(installed, tmp_path):
    assert run(installed, tmp_path, """
settings.overrides.sonic = 'anthropic/claude-opus-5-5:max';
ext(api); await start();
await spawn('selected', 'fast', '@model anthropic/claude-haiku-5-5 medium\\nWork');
console.log(JSON.stringify([seen, settings.overrides]));
""") == [
        [["selected", "anthropic/claude-haiku-5-5:medium", "Work"]],
        {"sonic": "anthropic/claude-opus-5-5:max"},
    ]


@pytest.mark.parametrize("provider,agent,role,saved,expected", [
    ("anthropic", "sonic", "smol", "anthropic/claude-haiku-5-5:max",
     "anthropic/claude-haiku-5-5:max"),
    ("anthropic", "task", "task", "anthropic/claude-sonnet-5-5:high",
     "anthropic/claude-sonnet-5-5:high"),
    ("anthropic", "task", "task", "anthropic/claude-haiku-5-5:high",
     "anthropic/claude-haiku-5-5:high"),
    ("anthropic", "task", "task", "anthropic/claude-opus-5-5:auto",
     "anthropic/claude-sonnet-5-5:medium"),
    ("openai-codex", "sonic", "smol", "openai-codex/gpt-6-luna:xhigh",
     "openai-codex/gpt-6-luna:xhigh"),
    ("openai", "task", "task", "openai/gpt-6.1-sol:high",
     "openai/gpt-6.1-sol:medium"),
])
def test_cold_restore_prefers_bounded_concrete_model(
    installed, tmp_path, provider, agent, role, saved, expected,
):
    result = run(installed, tmp_path, f"""
ext(api); await start();
const saved = {{
  type: 'session_init', agent: {json.dumps(agent)},
  modelRole: {json.dumps(role)}, resolvedModel: {json.dumps(saved)},
}};
const reopened = new SessionManager([saved]);
const init = reopened.getEntries()[0];
const restored = init.modelRole ? roles[init.modelRole] : init.resolvedModel;
console.log(JSON.stringify([restored, saved.resolvedModel, saved.modelRole]));
""", context={"model": {"provider": provider}})
    assert result == [expected, saved, role]


def test_other_home_keeps_host_spawn_and_restore_defaults(installed, tmp_path):
    assert run(installed, tmp_path, """
ext(api); await start();
process.env.FM_TASK_INBOX = process.env.FM_TASK_INBOX.replace('state/', 'other/state/');
ext(api); await start();
await spawn('other-home', 'good', 'Work');
const saved = {type: 'session_init', agent: 'task', modelRole: 'task',
  resolvedModel: 'anthropic/claude-sonnet-5-5:medium'};
const init = new SessionManager([saved]).getEntries()[0];
console.log(JSON.stringify([seen, init.modelRole]));
""") == [[["other-home", "original-good", "Work"]], "task"]


def test_subagent_keeps_valid_high_effort_choice(installed, tmp_path):
    assert run(installed, tmp_path, """
ext(api); await start();
const result = await handlers.before_subagent_spawn({
  agent: 'task', modelRole: 'task', patterns: ['anthropic/claude-sonnet-5-5:max'],
}, ctx);
console.log(JSON.stringify(result));
""", context={"agent": {"kind": "sub"}}) == {"model": "anthropic/claude-sonnet-5-5:max"}


@pytest.mark.parametrize("provider,model,level,expected", [
    ("anthropic", "claude-haiku-5-5", "low", "high"),
    ("anthropic", "claude-sonnet-5-5", "low", "medium"),
    ("anthropic", "claude-sonnet-5-5", "max", "max"),
    ("openai-codex", "gpt-6-luna", "max", "high"),
    ("openai", "gpt-6.1-sol", "high", "medium"),
])
def test_subagent_bounds_effort_after_host_resolution(
    installed, tmp_path, provider, model, level, expected,
):
    assert run(installed, tmp_path, f"""
thinkingLevel = {json.dumps(level)};
ext(api); await start();
console.log(JSON.stringify([mode, thinkingLevel]));
""", context={"agent": {"kind": "sub"}, "hasUI": False,
              "model": {"provider": provider, "id": model}}) == ["normal", expected]


@pytest.mark.parametrize("manager", ["undefined", "{}", "{getSessionId: () => ''}"])
def test_missing_spawn_identity_keeps_host_defaults(installed, tmp_path, manager):
    assert run(installed, tmp_path, f"""
ext(api); await start();
await new Spawn({{settings, sessionManager: {manager}}}).execute('unscoped', {{
  cli: 'good', prompt: 'Work',
}});
console.log(JSON.stringify(seen));
""") == [["unscoped", "original-good", "Work"]]


@pytest.mark.parametrize("cli,prompt,primary", [
    ("fast", "Work", "inception/mercury-3"),
    ("good", "Work", "anthropic/claude-sonnet-5-5"),
])
def test_missing_primary_credential_uses_haiku_not_opus(installed, tmp_path, cli, prompt, primary):
    result = run(installed, tmp_path, f"""
credentials.set({json.dumps(primary)}, undefined);
credentials.set('anthropic/claude-opus-5-5', 'director-token');
ext(api); await start();
await spawn('fallback', {json.dumps(cli)}, {json.dumps(prompt)});
console.log(JSON.stringify(seen));
""", context={"model": {"provider": "anthropic", "id": "claude-opus-5-5"}})
    level = "high" if cli == "fast" else "medium"
    assert result == [["fallback", f"anthropic/claude-haiku-5-5:{level}", "Work"]]


def test_missing_all_allowed_credentials_blocks_spawn(installed, tmp_path):
    result = run(installed, tmp_path, """
defaultCredential = undefined;
credentials.set('anthropic/claude-opus-5-5', 'director-token');
ext(api); await start();
const result = await spawn('blocked', 'fast', 'Work');
console.log(JSON.stringify([result, seen]));
""")
    assert result == [
        {"block": True, "reason": "Gluttony: no allowed worker model has a usable credential."},
        [],
    ]


def test_cold_restore_rewrites_retry_primary_and_chain(installed, tmp_path):
    result = run(installed, tmp_path, """
ext(api); await start();
const saved = {
  type: 'session_init', agent: 'task', modelRole: 'task',
  resolvedModel: 'anthropic/claude-sonnet-5-5:high',
  retryFallback: {primary: 'anthropic/claude-opus-5-5:max',
    chain: ['anthropic/claude-opus-5-5:auto', 'anthropic/claude-haiku-5-5:low',
      'anthropic/claude-sonnet-5-5:high']},
};
const restored = new SessionManager([saved]).getEntries()[0];
const attempts = [restored.retryFallback.primary, ...restored.retryFallback.chain];
console.log(JSON.stringify([attempts, saved.retryFallback.primary]));
""")
    assert result == [
        ["anthropic/claude-sonnet-5-5:high", "anthropic/claude-haiku-5-5:high"],
        "anthropic/claude-opus-5-5:max",
    ]


def test_restored_mercury_without_a_key_uses_haiku(installed, tmp_path):
    assert run(installed, tmp_path, """
credentials.set('inception/mercury-3', undefined);
ext(api); await start();
const saved = {type: 'session_init', agent: 'sonic', modelRole: 'smol',
  resolvedModel: 'inception/mercury-3:high'};
console.log(JSON.stringify(new SessionManager([saved]).getEntries()[0].resolvedModel));
""") == "anthropic/claude-haiku-5-5:high"


def test_restore_without_an_allowed_key_fails(installed, tmp_path):
    assert run(installed, tmp_path, """
defaultCredential = undefined;
credentials.set('anthropic/claude-opus-5-5', 'director-token');
ext(api); await start();
try {
  new SessionManager([{type: 'session_init', agent: 'sonic',
    resolvedModel: 'inception/mercury-3:high'}]).getEntries();
} catch (error) {
  console.log(JSON.stringify(error.message));
}
""") == "Gluttony: no allowed restored worker model has a usable credential."


@pytest.mark.parametrize("provider,primary,retry,expected", [
    ("openai-codex", "openai-codex/gpt-6-luna:high", "openai-codex/gpt-6.1-sol:medium", []),
    ("anthropic", "inception/mercury-3:high", "anthropic/claude-sonnet-5-5:medium",
     ["anthropic/claude-haiku-5-5:high"]),
])
def test_restored_fast_worker_cannot_retry_on_good_models(
    installed, tmp_path, provider, primary, retry, expected,
):
    assert run(installed, tmp_path, f"""
ext(api); await start();
const saved = {{type: 'session_init', agent: 'sonic', modelRole: 'smol',
  resolvedModel: {json.dumps(primary)},
  retryFallback: {{primary: {json.dumps(primary)}, chain: [{json.dumps(retry)}]}}}};
console.log(JSON.stringify(new SessionManager([saved]).getEntries()[0].retryFallback.chain));
""", context={"model": {"provider": provider}}) == expected


@pytest.mark.parametrize("has_haiku", [True, False])
def test_ordinary_subagent_authentication_stays_in_set(installed, tmp_path, has_haiku):
    result = run(installed, tmp_path, f"""
defaultCredential = undefined;
credentials.set('anthropic/claude-opus-5-5', 'director-token');
credentials.set('anthropic/claude-haiku-5-5', {'"test-token"' if has_haiku else 'undefined'});
ext(api); await start();
const result = await handlers.before_subagent_spawn({{
  agent: 'sonic', patterns: ['anthropic/claude-opus-5-5:auto'],
}}, ctx);
console.log(JSON.stringify(result));
""", context={"agent": {"kind": "sub"}})
    assert result == (
        {"model": "anthropic/claude-haiku-5-5:high"} if has_haiku else
        {"block": True, "reason": "Gluttony: no allowed subagent model has a usable credential."}
    )


@pytest.mark.parametrize("key", [
    "default", "task", "smol", "subagent:worker",
    "anthropic/claude-sonnet-5-5:high", "anthropic/*",
])
def test_live_subagent_bounds_every_retry_chain_without_changing_parent(installed, tmp_path, key):
    result = run(installed, tmp_path, f"""
settings.chains = {{
  [{json.dumps(key)}]: ['anthropic/claude-opus-5-5:max', 'anthropic/claude-haiku-5-5:high'],
}};
activeSettings = settings.overlay({{}});
thinkingLevel = 'high';
ext(api); await start();
console.log(JSON.stringify([activeSettings.chains[{json.dumps(key)}],
  settings.chains[{json.dumps(key)}]]));
""", context={"agent": {"kind": "sub"},
              "model": {"provider": "anthropic", "id": "claude-sonnet-5-5"}})
    assert result == [
        ["anthropic/claude-haiku-5-5:high"],
        ["anthropic/claude-opus-5-5:max", "anthropic/claude-haiku-5-5:high"],
    ]


def test_missing_private_api_still_enters_vibe(installed, tmp_path):
    assert run(installed, tmp_path, """
delete api.pi;
ext(api); await start();
console.log(JSON.stringify([mode, roles]));
""") == ["vibe", {"smol": "original-fast", "task": "original-good", "subagent": "original-sub"}]


@pytest.mark.parametrize("provider", ["openai-codex", "openai"])
def test_sol_dispatch_uses_ultrafast_without_changing_director(installed, tmp_path, provider):
    assert run(installed, tmp_path, """
ext(api); await start();
await Promise.all([spawn('good', 'good', 'Work'), spawn('fast', 'fast', 'Work')]);
console.log(JSON.stringify([seenTiers, settings.openaiTier]));
""", context={"model": {"provider": provider}}) == [["ultrafast", "priority"], "priority"]


@pytest.mark.parametrize("invocation", ["task", "eval", "restore"])
@pytest.mark.parametrize("provider,model,expected", [
    ("openai-codex", "gpt-6.1-sol", "ultrafast"),
    ("openai", "gpt-6.1-sol", "ultrafast"),
    ("openai-codex", "gpt-6-luna", "priority"),
    ("openai", "gpt-6-luna", "priority"),
    ("anthropic", "claude-sonnet-5-5", "priority"),
])
def test_worker_start_bounds_tier_without_changing_parent(
    installed, tmp_path, provider, invocation, model, expected,
):
    assert run(installed, tmp_path, f"""
ext(api); await start();
const model = {json.dumps(f"{provider}/{model}:medium")};
const role = {json.dumps("smol" if model == "gpt-6-luna" else "task")};
let selected;
if ({json.dumps(invocation)} === 'restore') {{
  const saved = {{type: 'session_init', agent: role === 'smol' ? 'sonic' : 'task',
    modelRole: role, resolvedModel: model}};
  selected = new SessionManager([saved]).getEntries()[0].resolvedModel;
}} else {{
  selected = (await handlers.before_subagent_spawn({{
    agent: role === 'smol' ? 'sonic' : 'task', modelRole: role,
    invocationKind: {json.dumps(invocation)}, patterns: [model],
  }}, ctx)).model;
}}
const [selector, level] = selected.split(':');
const [provider, id] = selector.split('/');
ctx.agent.kind = 'sub';
ctx.model = {{provider, id}};
thinkingLevel = level;
activeSettings = settings.overlay({{}});
await start();
console.log(JSON.stringify([activeSettings.openaiTier, settings.openaiTier]));
""", context={"model": {"provider": provider}}) == [expected, "priority"]


def test_disabled_gluttony_keeps_sol_tier(installed, tmp_path):
    assert run(installed, tmp_path, """
activeSettings = settings.overlay({});
ext(api); await start();
console.log(JSON.stringify([activeSettings.openaiTier, settings.openaiTier]));
""", enabled=False, context={"agent": {"kind": "sub"},
                            "model": {"provider": "openai-codex", "id": "gpt-6.1-sol"}}) == [
        "priority", "priority",
    ]
