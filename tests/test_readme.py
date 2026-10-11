import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schemas/crewship.schema.json").read_text())
DEFAULT = yaml.safe_load((ROOT / "config/default.yml").read_text())
SPEC = importlib.util.spec_from_file_location("provisions", ROOT / "scripts/provisions.py")
provisions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provisions)

# Host config switch -> the doc its Features line links.
FEATURES = {
    "crewship.profiles.agents": "docs/omp.md",
    "crewship.profiles.chat": "docs/chat.md",
    "crewship.profiles.tailscale": "docs/security.md#remote-access",
    "crewship.profiles.desktop": "docs/recovery.md#desktop-access",
    "crewship.profiles.fleet_guards": "docs/fleet-guards.md",
    "crewship.profiles.shared_postgres": "docs/shared-postgres.md",
    "crewship.profiles.fleet_browsers": "docs/fleet-guards.md#browser-ladder",
    "crewship.data_dir": "docs/configuration.md#data-disk",
    "crewship.firstmate.checklist": "docs/configuration.md#new-host-questions",
    "crewship.mac_ssh": "docs/security.md#ssh-to-a-mac",
    "crewship.imessage": "docs/imessage.md",
    "crewship.github_board": "docs/github-board.md",
    "crewship.board": "docs/board.md",
    "crewship.ci_pool": "docs/ci-pool.md",
}
EXCLUDED = {
    # Base installs, listed under "Profiles on" in Default config.
    "crewship.profiles.development",
    "crewship.profiles.firstmate",
    "crewship.profiles.docker",
    # Settings of a feature that another switch turns on.
    "crewship.docker",
    "crewship.fleet",
    "crewship.fleet.docker_guard",
    "crewship.browsers",
    "crewship.imessage.bluebubbles",
    # Host-only skills: documented in docs/omp.md, not a README feature.
    "crewship.skills",
}


def switches(node=SCHEMA, path=()):
    """Every profile, optional `crewship` key and optional block: path -> off by default."""
    for key, sub in node.get("properties", {}).items():
        here = path + (key,)
        optional = key not in node.get("required", ())
        if (
            path[-1:] == ("profiles",)
            or optional
            and (len(here) == 2 or sub.get("type") == "object")
        ):
            value = DEFAULT
            for part in here:
                value = value.get(part) if isinstance(value, dict) else None
            yield ".".join(here), value in (None, False, "")
        yield from switches(sub, here)


def section(summary):
    text = (ROOT / "README.md").read_text()
    body = text.split(f"<summary><b>{summary}</b></summary>", 1)[1].split("</details>", 1)[0]
    return [line for line in body.splitlines() if line.startswith("- ")]


def ticks(names):
    return ", ".join(f"`{name}`" for name in names)


def test_every_config_switch_has_a_features_line_tagged_opt_in_when_off_by_default():
    found = dict(switches())
    assert set(found) == FEATURES.keys() | EXCLUDED, "map the new switch in FEATURES or EXCLUDED"
    lines = section("Show all features")
    text = (ROOT / "README.md").read_text()
    highlights = text.split("## Features", 1)[1].split("<details>", 1)[0]
    for path, link in FEATURES.items():
        assert (ROOT / link.split("#")[0]).is_file(), link
        matches = [line for line in lines if f"]({link})" in line]
        if f"]({link})" in highlights:
            assert not matches, f"{path}: {link} is a highlight and must not repeat in the list"
            continue
        assert len(matches) == 1, f"{path}: one Features line must link {link}"
        assert matches[0].endswith(" (opt-in)") == found[path], matches[0]


def test_default_config_lists_the_current_defaults():
    omp = yaml.safe_load((ROOT / "config/omp.yml").read_text())
    profiles = DEFAULT["crewship"]["profiles"]
    unset = [
        path.removeprefix("crewship.")
        for path, off in switches()
        if off and ".profiles." not in path and path not in EXCLUDED
    ]
    lines = {line.split(":**")[0].removeprefix("- **"): line for line in section("Default config")}

    assert (
        ticks(profiles_on := [n for n, on in profiles.items() if on])
        in lines["Profiles on by default"]
    )
    assert lines["Opt-in profiles"].endswith(ticks(n for n in profiles if n not in profiles_on))
    assert lines["Opt-in settings"].endswith(ticks(unset))

    agents = lines["Agents and models"]
    advisor = "on" if omp["advisor"]["enabled"] else "off"
    assert f"home model is `{omp['modelRoles']['default']}`, with the advisor {advisor}" in agents
    dispatch = json.loads((ROOT / "config/crew-dispatch.json").read_text())
    small, ordinary, hard = [
        [choice["model"] for choice in rule["use"]] for rule in dispatch["rules"]
    ]
    assert dispatch["default"] == dispatch["rules"][1]["use"]
    for models in (small, ordinary, hard):
        assert " or ".join(f"`{model}`" for model in models) in agents

    limits = lines["Model limits and fallbacks"]
    model_overrides = yaml.safe_load((ROOT / "config/omp-models.yml").read_text())
    for window in model_overrides["providers"]["openai-codex"]["modelOverrides"].values():
        assert f"{window['contextWindow'] // 1000}K by default" in limits
        assert f"{window['maxContextWindow'] // 1000000}M at most" in limits
    chains = omp["retry"]["fallbackChains"]
    assert chains == {
        "anthropic/claude-fable-5-1": ["anthropic/claude-opus-5"],
        "anthropic/claude-sonnet-5": ["anthropic/claude-fable-5-1", "anthropic/claude-opus-5"],
    }, "update the fallback sentence in Default config"

    gate = yaml.safe_load((ROOT / "config/no-mistakes-omp.yml").read_text())
    assert f"`{gate['modelRoles']['default']}` by default" in lines["Gates"]
    assert f"`{hard[0]}:high` for hard work" in lines["Gates"]

    for plugin in provisions.OMP_PLUGINS:
        assert f"`{plugin}`" in lines["Plugins and extensions"]
