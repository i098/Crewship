import copy
import importlib.util
import json
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "blueprint/schemas/crewship.schema.json").read_text())
DEFAULT = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
SPEC = importlib.util.spec_from_file_location("provisions", ROOT / "scripts/provisions.py")
provisions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provisions)

# Host config switch -> the doc its Features line links.
FEATURES = {
    "crewship.profiles.agents": "docs/omp.md",
    "crewship.profiles.public_skills": "docs/omp.md#skills",
    "crewship.profiles.chat": "docs/chat.md",
    "crewship.profiles.gateway": "docs/gateway.md",
    "crewship.profiles.tailscale": "docs/security.md#remote-access",
    "crewship.profiles.desktop": "docs/recovery.md#desktop-access",
    "crewship.profiles.fleet_guards": "docs/fleet-guards.md",
    "crewship.profiles.shared_postgres": "docs/shared-postgres.md",
    "crewship.profiles.jj": "docs/jj.md",
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
    "crewship.gateway",
    "crewship.imessage.bluebubbles",
    "crewship.imessage.cards",
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


def section(path):
    return [line for line in path.read_text().splitlines() if line.startswith("- ")]


def relative(link):
    """A docs/ link as written inside docs/features.md, which lives beside the other docs."""
    return link.removeprefix("docs/") if link.startswith("docs/") else f"../{link}"


def ticks(names):
    return ", ".join(f"`{name}`" for name in names)


def test_every_config_switch_has_a_features_line_tagged_opt_in_when_off_by_default():
    found = dict(switches())
    assert set(found) == FEATURES.keys() | EXCLUDED, "map the new switch in FEATURES or EXCLUDED"
    lines = section(ROOT / "docs/features.md")
    text = (ROOT / "README.md").read_text()
    highlights = text.split("## Features", 1)[1].split("\n## ", 1)[0]
    for path, link in FEATURES.items():
        assert (ROOT / link.split("#")[0]).is_file(), link
        matches = [line for line in lines if f"]({relative(link)})" in line]
        if f"]({link})" in highlights:
            assert not matches, f"{path}: {link} is a highlight and must not repeat in the list"
            continue
        assert len(matches) == 1, f"{path}: one Features line must link {link}"
        assert matches[0].endswith(" (opt-in)") == found[path], matches[0]


def test_schema_accepts_the_jj_profile_and_rejects_unknown_ones():
    validator = jsonschema.Draft202012Validator(SCHEMA)
    for key, ok in (("jj", True), ("jjj", False)):
        host = copy.deepcopy(DEFAULT)
        host["crewship"]["profiles"][key] = True
        assert (not list(validator.iter_errors(host))) is ok
    assert DEFAULT["crewship"]["profiles"]["jj"] is False


def test_default_config_lists_the_current_defaults():
    omp = yaml.safe_load((ROOT / "blueprint/config/omp.yml").read_text())
    profiles = DEFAULT["crewship"]["profiles"]
    unset = [
        path.removeprefix("crewship.")
        for path, off in switches()
        if off and ".profiles." not in path and path not in EXCLUDED
    ]
    lines = {
        line.split(":**")[0].removeprefix("- **"): line
        for line in section(ROOT / "docs/default-config.md")
    }

    on = [name for name, enabled in profiles.items() if enabled]
    assert lines["Profiles on by default"].endswith(ticks(on))
    assert lines["Opt-in profiles"].endswith(ticks(n for n in profiles if n not in on))
    assert lines["Opt-in settings"].endswith(ticks(unset))
    for plugin in provisions.OMP_PLUGINS:
        assert f"`{plugin}`" in lines["Plugins and extensions"]

    # The Models, Fallbacks and Gates lines name models in words, so pin the ids they stand for.
    assert omp["modelRoles"]["default"] == "anthropic/claude-opus-5-5:high"
    assert "Opus 5.5 at high thinking runs the home" in lines["Models"]
    assert omp["advisor"]["enabled"] is False and "advisor off" in lines["Models"]
    dispatch = json.loads((ROOT / "blueprint/config/crew-dispatch.json").read_text())
    tiers = [[rule_use["model"] for rule_use in rule["use"]] for rule in dispatch["rules"]]
    assert tiers == [
        ["anthropic/claude-haiku-5-5", "openai-codex/gpt-6-luna"],
        ["anthropic/claude-sonnet-5-5"],
        ["anthropic/claude-opus-5-5"],
    ], "update the Models line in Default config"
    assert dispatch["default"] == dispatch["rules"][1]["use"]
    assert omp["retry"]["fallbackChains"] == {
        "anthropic/claude-opus-5-5": ["anthropic/claude-fable-5-1:medium"],
        "anthropic/claude-fable-5-1": ["anthropic/claude-opus-5"],
        "anthropic/claude-sonnet-5": ["anthropic/claude-fable-5-1", "anthropic/claude-opus-5"],
    }, "update the Fallbacks line in Default config"
    gate = yaml.safe_load((ROOT / "blueprint/config/no-mistakes-omp.yml").read_text())
    assert gate["modelRoles"]["default"] == "anthropic/claude-sonnet-5-5:high"
    assert "Sonnet 5.5 at high thinking, and Opus 5.5 for hard work" in lines["Gates"]
