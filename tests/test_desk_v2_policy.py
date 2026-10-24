"""Relay target choice and dispatch model selection, as pure functions."""

import json
import shutil
from pathlib import Path

import pytest
from test_imessage import ROOT, bun

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

RELAY = json.dumps(str(ROOT / "apps/imessage/relay.ts"))
POLICY = json.dumps(str(ROOT / "apps/imessage/dispatch-policy.ts"))
MATES = [{"id": "3", "home": "/h/3", "scope": "docs"}, {"id": "4", "home": "/h/4", "scope": "api"}]
REQUEST = {
    "requestId": "r1",
    "text": "fix the docs build",
    "firstmate": False,
    "mateEligible": True,
}


def relay(requests, metadata):
    return bun(f"""
import {{ relayTarget }} from {RELAY};
console.log(JSON.stringify(relayTarget({json.dumps(requests)}, {json.dumps(metadata)}, {json.dumps(MATES)}) ?? null));
""")


WORK = {"category": "work", "target": "3", "domains": ["3"]}


def test_relay_picks_the_single_listed_mate_for_work():
    assert relay([REQUEST], WORK)["id"] == "3"


@pytest.mark.parametrize(
    "metadata",
    [
        {**WORK, "category": "approval"},
        {**WORK, "domains": ["3", "4"]},
        {**WORK, "domains": ["4"]},
        {**WORK, "target": "9", "domains": ["9"]},
        {**WORK, "target": 3},
        None,
        [WORK],
    ],
)
def test_relay_refuses_anything_but_one_matching_work_domain(metadata):
    assert relay([REQUEST], metadata) is None


@pytest.mark.parametrize(
    "change",
    [
        {"firstmate": True},
        {"mateEligible": False},
        {"mutationPath": "/x"},
        {"text": "use the token for the deploy"},
    ],
)
def test_relay_keeps_protected_requests_with_firstmate(change):
    assert relay([{**REQUEST, **change}], WORK) is None


CATALOG = [
    {
        "provider": "anthropic",
        "id": "claude-opus-5-5",
        "reasoning": ["minimal", "low", "xhigh"],
        "apiKeyEnv": "ANTHROPIC_API_KEY",
    },
    {"provider": "openai", "id": "gpt-6-luna", "reasoning": ["low", "high"], "apiKeyEnv": None},
    {"provider": "anthropic", "id": "claude-fable-5-1", "reasoning": ["low"], "apiKeyEnv": None},
    {
        "provider": "inception",
        "id": "mercury-3",
        "reasoning": ["low", "high"],
        "apiKeyEnv": "INCEPTION_API_KEY",
    },
    {"provider": "other", "id": "thing", "reasoning": ["low"], "apiKeyEnv": None},
]
POLICY_JSON = {
    "rules": [{"use": {"harness": "omp", "model": "openai/gpt-6-luna", "effort": "high"}}]
}


def models(purpose="general"):
    return bun(f"""
import {{ dispatchModels }} from {POLICY};
console.log(JSON.stringify(dispatchModels({json.dumps(CATALOG)}, {json.dumps(POLICY_JSON)}, {json.dumps(purpose)})));
""")


def test_general_dispatch_lists_only_permitted_models_with_policy_efforts():
    listed = {m["id"]: m["reasoning"] for m in models()}
    assert listed == {
        "anthropic/claude-opus-5-5": ["minimal", "low"],
        "openai/gpt-6-luna": ["high"],
    }


def test_simple_coding_adds_only_the_high_effort_mercury():
    listed = {m["id"]: m["reasoning"] for m in models("simple-coding")}
    assert listed["inception/mercury-3"] == ["high"]


def selection(value, purpose="general"):
    return bun(f"""
import {{ dispatchModels, dispatchSelection }} from {POLICY};
const list = dispatchModels({json.dumps(CATALOG)}, {json.dumps(POLICY_JSON)});
console.log(JSON.stringify(dispatchSelection({json.dumps(value)}, list, {json.dumps(purpose)}) ?? null));
""")


def test_selection_accepts_a_listed_model_and_effort():
    assert selection({"model": "openai/gpt-6-luna", "reasoning": "high"}) == {
        "provider": "omp",
        "model": "openai/gpt-6-luna",
        "reasoning": "high",
        "apiKeyEnv": None,
    }


@pytest.mark.parametrize(
    "value",
    [
        {"model": "openai/gpt-6-luna", "reasoning": "low"},
        {"model": "anthropic/claude-fable-5-1", "reasoning": "low"},
        {"model": "inception/mercury-3", "reasoning": "high"},
        {"model": 1, "reasoning": "high"},
        "openai/gpt-6-luna",
    ],
)
def test_selection_refuses_unlisted_or_unpermitted_choices(value):
    assert selection(value) is None


PACKAGES = {
    "pi-catalog": {
        "models": """
const models = [
  { provider: "openai", id: "gpt-5", efforts: ["low", "high"] },
  { provider: "openai", id: "gpt-6-luna", efforts: ["low", "high"] },
  { provider: "anthropic", id: "claude-opus-5-5", efforts: ["low", "xhigh"] },
  { provider: "anthropic", id: "claude-sonnet-5-5", efforts: ["low"] },
  { provider: "other", id: "thing", efforts: ["low"] },
];
export const getBundledProviders = () => [...new Set(models.map((m) => m.provider))];
export const getBundledModels = (provider) => models.filter((m) => m.provider === provider);
""",
        "model-thinking": "export const getSupportedEfforts = (model) => model.efforts;",
    },
    "pi-coding-agent": {
        "config/settings": """
import { readFileSync } from "node:fs";
import { join } from "node:path";
export const Settings = { loadReadOnly: async ({ agentDir }) => JSON.parse(readFileSync(join(agentDir, "settings.json"), "utf8")) };
""",
        "config/model-settings": """
export const cfgDisabledProviders = { get: (settings) => settings.disabledProviders ?? [] };
export const cfgEnabledModels = { get: (settings) => settings.enabledModels ?? [] };
""",
        "config/model-resolver": """
export const filterAvailableModelsByEnabledPatterns = (models, patterns) =>
  patterns.length ? models.filter((m) => patterns.includes(`${m.provider}/${m.id}`)) : models;
""",
        "config/custom-models": """
export const buildCustomModelOverlay = (provider, baseUrl, api, _a, _b, _c, _d, _e, _f, definition) =>
  ({ provider, id: definition.id, api, baseUrl, efforts: definition.efforts });
export const finalizeCustomModel = (model) => model;
""",
        "config/model-patch": """
export const applyModelPatch = (model, patch) => ({ ...model, ...patch });
export const applyModelOverride = (model, override) => ({ ...model, ...override });
""",
        "config/models-config": """
export const validateProviderConfiguration = () => {};
export const ModelsConfigFile = { schema: { assert: (value) => value } };
""",
        "config/resolve-config-value": "export const isCommandConfigValue = (value) => value.startsWith('!');",
    },
    "pi-ai": {
        "env-api-key": "export const getEnvApiKeyName = (provider) => (provider === 'openai' ? 'OPENAI_API_KEY' : undefined);",
        "utils/foundry": "export const isFoundryEnabled = () => false;",
    },
    "pi-utils": {
        "index": "export const $env = process.env; export const $envExact = (name) => process.env[name];",
    },
}


def fixture_omp(root):
    for package, modules in PACKAGES.items():
        directory = root / "node_modules" / "@oh-my-pi" / package
        for name, source in modules.items():
            (directory / f"{name}.js").parent.mkdir(parents=True, exist_ok=True)
            (directory / f"{name}.js").write_text(source)
        exports = {".": "./index.js"} if package == "pi-utils" else {"./*": "./*.js"}
        (directory / "package.json").write_text(
            json.dumps({"name": f"@oh-my-pi/{package}", "type": "module", "exports": exports})
        )
    executable = root / "bin" / "omp"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    return executable.parent


def test_loader_lists_available_models_from_catalog_overlay_and_policy(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "PATH", f"{fixture_omp(tmp_path)}:{Path(shutil.which('bun')).parent}:/usr/bin:/bin"
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent, home = tmp_path / "agent", tmp_path / "home"
    (home / "config").mkdir(parents=True)
    agent.mkdir()
    (agent / "settings.json").write_text(
        json.dumps(
            {
                "enabledModels": [
                    "openai/gpt-5",
                    "openai/gpt-6-luna",
                    "anthropic/claude-opus-5-5",
                    "other/thing",
                    "inception/mercury-3",
                ]
            }
        )
    )
    (agent / "models.yml").write_text(
        "providers:\n  inception:\n    baseUrl: https://example.invalid/v1\n    api: openai-completions\n"
        '    apiKey: "!printenv MERCURY_KEY"\n    models:\n      - id: mercury-3\n        efforts: [low, high]\n'
    )
    (home / "config" / "crew-dispatch.json").write_text(
        json.dumps(
            {"rules": [{"use": {"harness": "omp", "model": "openai/gpt-5", "effort": "high"}}]}
        )
    )
    args = f"{json.dumps(str(home))}, {json.dumps(str(agent))}, auth, {json.dumps(str(home))}"
    result = bun(f"""
import {{ loadDispatchModels }} from {POLICY};
const auth = {{ source: (p) => (p === "openai" ? "key" : undefined), keyless: () => false }};
console.log(JSON.stringify({{
  general: await loadDispatchModels({args}),
  coding: await loadDispatchModels({args}, "simple-coding"),
}}));
""")
    general = {m["id"]: m for m in result["general"]}
    assert general["openai/gpt-5"]["reasoning"] == ["high"]
    assert general["openai/gpt-5"]["apiKeyEnv"] == "OPENAI_API_KEY"
    assert general["openai/gpt-6-luna"]["reasoning"] == ["low", "high"]
    assert set(general) == {"openai/gpt-5", "openai/gpt-6-luna"}
    mercury = {m["id"]: m for m in result["coding"]}["inception/mercury-3"]
    assert mercury == {
        "id": "inception/mercury-3",
        "provider": "inception",
        "model": "mercury-3",
        "reasoning": ["high"],
        "apiKeyEnv": "MERCURY_KEY",
    }
