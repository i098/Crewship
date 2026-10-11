import importlib.util
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schemas/crewship.schema.json").read_text())
DEFAULT = yaml.safe_load((ROOT / "config/default.yml").read_text())
SPEC = importlib.util.spec_from_file_location("provisions", ROOT / "scripts/provisions.py")
provisions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provisions)
SPEC = importlib.util.spec_from_file_location("ci_pool", ROOT / "maintenance/ci-pool.py")
ci_pool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci_pool)

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
    roles = omp["modelRoles"]
    group_vars = yaml.safe_load((ROOT / "ansible/group_vars/all.yml").read_text())
    extensions = {
        Path(value).stem
        for value in group_vars.values()
        if isinstance(value, str) and "/.omp/agent/extensions/" in value
    }
    patches = {path.stem for path in (ROOT / "patches/firstmate").glob("*.patch")}
    profiles = DEFAULT["crewship"]["profiles"]
    unset = [
        path.removeprefix("crewship.")
        for path, off in switches()
        if off and ".profiles." not in path and path not in EXCLUDED
    ]
    lines = section("Default config")
    for line in [
        f"- Agent harness: [omp](docs/omp.md), home model `{roles['default']}`, "
        f"advisor {'on' if omp['advisor']['enabled'] else 'off'}",
        "- omp plugins: " + ticks(provisions.OMP_PLUGINS),
        "- Profiles on: " + ticks(name for name, on in profiles.items() if on),
        "- Profiles off (opt-in): " + ticks(name for name, on in profiles.items() if not on),
        "- Unset (opt-in): " + ticks(unset),
    ]:
        assert line in lines

    dispatch = json.loads((ROOT / "config/crew-dispatch.json").read_text())
    small, ordinary, hard = [
        [choice["model"] for choice in rule["use"]] for rule in dispatch["rules"]
    ]
    assert (
        f"- Models: dynamic per-task selection; small {ticks(small)}; "
        f"ordinary (default) {ticks(ordinary)}; hard only {ticks(hard)}."
    ) in lines
    assert dispatch["default"] == dispatch["rules"][1]["use"]
    assert "- The spawning agent picks the thinking level." in lines
    model_overrides = yaml.safe_load((ROOT / "config/omp-models.yml").read_text())
    windows = model_overrides["providers"]["openai-codex"]["modelOverrides"]
    for window in windows.values():
        assert (
            f"- Codex context: {window['contextWindow'] // 1000}K default, "
            f"{window['maxContextWindow'] // 1000000}M maximum, "
            f"`extendedContext` {'on' if omp['extendedContext'] else 'off'}."
        ) in lines
    gate = yaml.safe_load((ROOT / "config/no-mistakes-omp.yml").read_text())
    assert (
        f"- Gate models: per-run pins; routine `{ordinary[1]}:medium`; "
        f"ordinary (default) `{gate['modelRoles']['default']}`; hard `{hard[0]}:high`."
    ) in lines

    hook_env = ci_pool.HOOK_ENV
    assert (
        f"- Hooks: `crewship-quality-gate` at omp turn end, SessionStart banners from "
        f"{ticks(provisions.OMP_PLUGINS)}, `{hook_env}` (opt-in with the [CI pool](docs/ci-pool.md))"
    ) in lines
    assert "crewship-quality-gate" in extensions

    def named(prefix):
        return {line.split("`")[1] for line in lines if line.startswith(prefix)}

    assert named("- omp extension `") == extensions
    assert named("- Firstmate patch `") == patches

    rule_line = next(line for line in lines if line.startswith("- omp rules "))
    names = re.findall(r"`([^`]+)`", rule_line)
    public_rules = {
        path.stem for path in (ROOT / "rules/public").glob("*.md") if path.name != "README.md"
    }
    assert set(names) == public_rules
    assert len(names) == len(public_rules)
