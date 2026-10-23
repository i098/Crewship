import json
import shutil

import pytest
from test_imessage import ROOT, bun

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
MODULE = json.dumps(str(ROOT / "apps/imessage/dispatch-policy.ts"))
SOURCE = f"""
import {{ dispatchModels, dispatchSelection, loadDispatchModels }} from {MODULE};
const catalog = [
  {{ provider: "anthropic", id: "claude-haiku-5-5", reasoning: ["low", "medium", "high", "xhigh", "max"], apiKeyEnv: "ANTHROPIC_API_KEY" }},
  {{ provider: "anthropic", id: "claude-opus-5-5", reasoning: ["low", "medium", "high", "xhigh", "max"], apiKeyEnv: "ANTHROPIC_API_KEY" }},
  {{ provider: "anthropic", id: "claude-fable-5-1", reasoning: ["low", "medium", "high"], apiKeyEnv: "ANTHROPIC_API_KEY" }},
  {{ provider: "inception", id: "mercury-3", reasoning: ["low", "medium", "high"], apiKeyEnv: "INCEPTION_API_KEY" }},
  {{ provider: "openai-codex", id: "gpt-6-luna", reasoning: ["low", "medium", "high", "xhigh"], apiKeyEnv: null }},
];
const policy = {{ rules: [{{ use: catalog.map((model) => ({{ harness: "omp", model: `${{model.provider}}/${{model.id}}` }})) }}] }};
"""


def test_enabled_direct_openai_model_does_not_need_a_primary_recommendation():
    result = bun(SOURCE + """
policy.rules[0].use = [{ harness: "omp", model: "anthropic/claude-haiku-5-5" }];
catalog.push({ provider: "openai", id: "gpt-6.1-sol", reasoning: ["low", "high"], apiKeyEnv: "OPENAI_API_KEY" });
console.log(JSON.stringify(dispatchModels(catalog, policy).map((model) => model.id)));
""")
    assert result == [
        "anthropic/claude-haiku-5-5", "anthropic/claude-opus-5-5", "openai-codex/gpt-6-luna", "openai/gpt-6.1-sol",
    ]


def test_fable_remains_fallback_only_even_if_listed():
    result = bun(SOURCE + "console.log(JSON.stringify(dispatchModels(catalog, policy).map((model) => model.id)));")
    assert "anthropic/claude-fable-5-1" not in result


def test_opus_has_a_high_ceiling_without_a_fixed_profile_effort():
    result = bun(SOURCE + "console.log(JSON.stringify(dispatchModels(catalog, policy).find((model) => model.id.includes('opus')).reasoning));")
    assert result == ["low", "medium", "high"]


@pytest.mark.parametrize("model", ["inception/mercury-3", "anthropic/claude-opus-5-5"])
def test_explicit_profile_effort_is_fixed_not_a_ceiling(model):
    result = bun(SOURCE + f"""
policy.rules[0].use = [{{ harness: "omp", model: {json.dumps(model)}, effort: "high" }}];
console.log(JSON.stringify(dispatchModels(catalog, policy, "simple-coding").find((choice) => choice.id === {json.dumps(model)}).reasoning));
""")
    assert result == ["high"]


def test_unknown_profiles_and_other_harness_efforts_do_not_change_enabled_choices():
    result = bun(SOURCE + """
policy.rules[0].use = [{ harness: "omp", model: "unknown/model" }, { harness: "claude", model: "anthropic/claude-haiku-5-5", effort: "high" }];
console.log(JSON.stringify(dispatchModels(catalog, policy).find((choice) => choice.id === "anthropic/claude-haiku-5-5").reasoning));
""")
    assert result == ["low", "medium", "high", "xhigh", "max"]


def test_default_profile_and_duplicate_profiles_keep_one_choice():
    result = bun(SOURCE + """
policy.rules[0].use = { harness: "omp", model: "inception/mercury-3", effort: "high" };
policy.default = { harness: "omp", model: "inception/mercury-3", effort: "high" };
console.log(JSON.stringify(dispatchModels(catalog, policy, "simple-coding").filter((choice) => choice.id === "inception/mercury-3")));
""")
    assert len(result) == 1
    assert result[0]["reasoning"] == ["high"]


def test_matching_fixed_effort_is_not_broadened_by_an_unrestricted_default():
    result = bun(SOURCE + """
policy.rules[0].use = { harness: "omp", model: "anthropic/claude-haiku-5-5", effort: "medium" };
policy.default = { harness: "omp", model: "anthropic/claude-haiku-5-5" };
console.log(JSON.stringify(dispatchModels(catalog, policy).find((choice) => choice.id === "anthropic/claude-haiku-5-5").reasoning));
""")
    assert result == ["medium"]


def test_selection_uses_only_trusted_execution_and_credential_fields():
    result = bun(SOURCE + """
const models = dispatchModels(catalog, policy, "simple-coding");
console.log(JSON.stringify(dispatchSelection({ model: "inception/mercury-3", reasoning: "high",
  provider: "forged", apiKeyEnv: "FORGED_SECRET", home: "/forged" }, models, "simple-coding")));
""")
    assert result == {"provider": "inception", "model": "mercury-3", "reasoning": "high", "apiKeyEnv": "INCEPTION_API_KEY"}


def test_oauth_selection_keeps_full_model_id_and_no_environment_key():
    result = bun(SOURCE + """
console.log(JSON.stringify(dispatchSelection({ model: "openai-codex/gpt-6-luna", reasoning: "low" }, dispatchModels(catalog, policy))));
""")
    assert result == {"provider": "omp", "model": "openai-codex/gpt-6-luna", "reasoning": "low", "apiKeyEnv": None}


def test_general_dispatch_keeps_claude_and_openai_but_excludes_mercury():
    result = bun(SOURCE + "console.log(JSON.stringify(dispatchModels(catalog, policy).map((model) => model.id)));")
    assert result == ["anthropic/claude-haiku-5-5", "anthropic/claude-opus-5-5", "openai-codex/gpt-6-luna"]


@pytest.mark.parametrize("forged", [{}, {"purpose": "simple-coding"}, {"category": "simple-coding"}])
def test_general_selection_rejects_mercury_even_with_a_coding_catalog(forged):
    result = bun(SOURCE + f"""
const models = dispatchModels(catalog, policy, "simple-coding");
const value = {{ model: "inception/mercury-3", reasoning: "high", ...{json.dumps(forged)} }};
console.log(JSON.stringify(dispatchSelection(value, models) ?? null));
""")
    assert result is None


@pytest.mark.parametrize("supported", [["low", "medium", "high"], ["low", "medium"]])
def test_trusted_simple_coding_allows_only_supported_mercury_high(supported):
    result = bun(SOURCE + f"""
catalog.find((model) => model.id === "mercury-3").reasoning = {json.dumps(supported)};
const models = dispatchModels(catalog, policy, "simple-coding");
console.log(JSON.stringify(models.find((model) => model.id === "inception/mercury-3")?.reasoning ?? []));
""")
    assert result == (["high"] if "high" in supported else [])


@pytest.mark.parametrize("selection", [
    None, {}, {"model": "unknown/model", "reasoning": "high"},
    {"model": "anthropic/claude-opus-5-5", "reasoning": "xhigh"},
    {"model": "anthropic/claude-fable-5-1", "reasoning": "high"},
    {"model": "inception/mercury-3", "reasoning": "auto"},
    {"model": "inception/mercury-3", "reasoning": "unsupported"},
])
def test_unsupported_selection_is_rejected_without_fallback(selection):
    result = bun(SOURCE + f"console.log(JSON.stringify(dispatchSelection({json.dumps(selection)}, dispatchModels(catalog, policy)) ?? null));")
    assert result is None


@pytest.mark.parametrize("policy", [None, {}, {"rules": [None]}, {"rules": [{"use": {"harness": "omp"}}]}])
def test_malformed_policy_fails_closed(policy):
    result = bun(SOURCE + f"""
let failed = false;
try {{ dispatchModels(catalog, {json.dumps(policy)}); }} catch {{ failed = true; }}
console.log(JSON.stringify(failed));
""")
    assert result is True


def test_advertised_catalog_efforts_are_accepted_by_the_installed_cli():
    if not shutil.which("omp"):
        pytest.skip("needs the installed omp catalog")
    result = bun(SOURCE + """
const { realpathSync } = await import("node:fs");
const { dirname } = await import("node:path");
const base = dirname(realpathSync(Bun.which("omp")));
const { parseCliThinkingLevel } = await import(Bun.resolveSync("@oh-my-pi/pi-tui/thinking", base));
const { getBundledModels } = await import(Bun.resolveSync("@oh-my-pi/pi-catalog/models", base));
const { getSupportedEfforts } = await import(Bun.resolveSync("@oh-my-pi/pi-catalog/model-thinking", base));
const entries = ["anthropic", "openai-codex"].flatMap((provider) => getBundledModels(provider))
  .map((model) => ({ provider: model.provider, id: model.id, reasoning: getSupportedEfforts(model), apiKeyEnv: null }));
const choices = dispatchModels(entries, policy);
console.log(JSON.stringify({
  rejects: choices.flatMap((model) => model.reasoning.filter((level) => parseCliThinkingLevel(level) !== level)),
  hasMax: choices.some((model) => model.reasoning.includes("max")),
  opus: choices.find((model) => model.id === "anthropic/claude-opus-5-5").reasoning,
}));
""")
    assert result == {"rejects": [], "hasMax": True, "opus": ["low", "medium", "high"]}


@pytest.mark.parametrize("purpose", ["general", "simple-coding"])
def test_loader_uses_static_catalog_and_read_only_host_configuration(tmp_path, purpose):
    if not shutil.which("omp"):
        pytest.skip("needs the installed omp catalog")
    home = tmp_path / "firstmate"
    agent = tmp_path / "agent"
    (home / "config").mkdir(parents=True)
    agent.mkdir()
    (home / "config/crew-dispatch.json").write_bytes((ROOT / "blueprint/config/crew-dispatch.json").read_bytes())
    (agent / "config.yml").write_text(json.dumps({
        "enabledModels": ["anthropic/claude-haiku-5-5", "anthropic/claude-opus-5-5", "inception/mercury-3"],
        "disabledProviders": ["anthropic"],
    }))
    (agent / "models.yml").write_bytes((ROOT / "blueprint/config/omp-models.yml").read_bytes())
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = bun(SOURCE + f"""
process.env.PI_CODING_AGENT_DIR = {json.dumps(str(agent))};
globalThis.fetch = () => {{ throw new Error("network forbidden"); }};
const models = await loadDispatchModels({json.dumps(str(home))}, {json.dumps(str(agent))}, {json.dumps(str(home))}, {json.dumps(purpose)});
console.log(JSON.stringify(models.map(({{ id, reasoning, apiKeyEnv }}) => ({{ id, reasoning, apiKeyEnv }}))));
""")
    assert result == ([{"id": "inception/mercury-3", "reasoning": ["high"], "apiKeyEnv": "INCEPTION_API_KEY"}]
                      if purpose == "simple-coding" else [])
    assert {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_loader_allows_only_enabled_direct_openai_models(tmp_path):
    if not shutil.which("omp"):
        pytest.skip("needs the installed omp catalog")
    home = tmp_path / "home"
    agent = tmp_path / "agent"
    (home / "config").mkdir(parents=True)
    agent.mkdir()
    (home / "config/crew-dispatch.json").write_bytes((ROOT / "blueprint/config/crew-dispatch.json").read_bytes())
    (agent / "config.yml").write_text(json.dumps({"enabledModels": ["openai/gpt-6.1-sol"]}))
    result = bun(SOURCE + f"""
process.env.PI_CODING_AGENT_DIR = {json.dumps(str(agent))};
globalThis.fetch = () => {{ throw new Error("network forbidden"); }};
console.log(JSON.stringify((await loadDispatchModels({json.dumps(str(home))}, {json.dumps(str(agent))})).map((model) => model.id)));
""")
    assert result == ["openai/gpt-6.1-sol"]


@pytest.mark.parametrize("environment,expected", [
    ({}, None),
    ({"ANTHROPIC_API_KEY": "test-key"}, "ANTHROPIC_API_KEY"),
    ({"ANTHROPIC_OAUTH_TOKEN": "test-token"}, "ANTHROPIC_OAUTH_TOKEN"),
    ({"ANTHROPIC_API_KEY": "test-key", "ANTHROPIC_OAUTH_TOKEN": "test-token"}, "ANTHROPIC_OAUTH_TOKEN"),
    ({"ANTHROPIC_API_KEY": "test-key", "ANTHROPIC_OAUTH_TOKEN": "  "}, "ANTHROPIC_API_KEY"),
    ({"ANTHROPIC_API_KEY": " \t "}, None),
    ({"ANTHROPIC_API_KEY": " ", "ANTHROPIC_OAUTH_TOKEN": "\t"}, None),
    ({"CLAUDE_CODE_USE_FOUNDRY": "true", "ANTHROPIC_FOUNDRY_API_KEY": " ", "ANTHROPIC_OAUTH_TOKEN": "test-token"}, "ANTHROPIC_OAUTH_TOKEN"),
    ({"CLAUDE_CODE_USE_FOUNDRY": "true", "ANTHROPIC_FOUNDRY_API_KEY": "test-foundry", "ANTHROPIC_OAUTH_TOKEN": "test-token"}, "ANTHROPIC_FOUNDRY_API_KEY"),
    ({"CLAUDE_CODE_USE_FOUNDRY": "false", "ANTHROPIC_FOUNDRY_API_KEY": "test-foundry", "ANTHROPIC_API_KEY": "test-key"}, "ANTHROPIC_API_KEY"),
    ({"CLAUDE_CODE_USE_FOUNDRY": " ON ", "ANTHROPIC_OAUTH_TOKEN": "test-token", "ANTHROPIC_API_KEY": "test-key"}, "ANTHROPIC_OAUTH_TOKEN"),
    ({"ANTHROPIC_FOUNDRY_API_KEY": "test-foundry"}, None),
])
def test_anthropic_credential_name_matches_canonical_environment_precedence(tmp_path, environment, expected):
    if not shutil.which("omp"):
        pytest.skip("needs the installed omp catalog")
    home = tmp_path / "home"
    agent = tmp_path / "agent"
    (home / "config").mkdir(parents=True)
    agent.mkdir()
    (home / "config/crew-dispatch.json").write_bytes((ROOT / "blueprint/config/crew-dispatch.json").read_bytes())
    (agent / "config.yml").write_text(json.dumps({"enabledModels": ["anthropic/claude-haiku-5-5"]}))
    result = bun(SOURCE + f"""
const path = process.env.PATH;
for (const name of Object.keys(process.env)) delete process.env[name];
Object.assign(process.env, {{ PATH: path, HOME: {json.dumps(str(home))}, LANG: "C.UTF-8", ...{json.dumps(environment)} }});
globalThis.fetch = () => {{ throw new Error("network forbidden"); }};
const models = await loadDispatchModels({json.dumps(str(home))}, {json.dumps(str(agent))});
console.log(JSON.stringify(models.map((model) => model.apiKeyEnv)));
""")
    assert result == [expected]
