#!/usr/bin/env python3
"""Crewship configuration, provisioning, and readiness checks."""

import argparse
import json
import os
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
STALE_FIRSTMATE_URL = "https://github.com/i098/firstmate.git"
LEGACY_BROWSER_KEYS = ("obscura_version", "obscura_sha256")
REMOVED_PROFILE = "shared_supabase"
REMOVED_FLEET_KEYS = ("supabase_project_id", "fixture_archive", "worktree_pools")
RETIRED_STACK = "oss-fleet/shared-supabase"
OLD_ROOT, NEW_ROOT = "factory", "crewship"
# Old profile names a host config may still use: old name -> the name the code reads.
PROFILE_ALIASES = {"shared_postgres": "project_databases"}
# The opt-in features of a new host, in checklist order: name -> (what it adds, what it needs).
# Every name is a profile, except board, which is a block (docs/board.md).
OPT_IN = {
    "public_skills": ("the public skills and rules for omp and Claude Code", ()),
    "agent_instructions": ("the global instructions for Claude Code, omp and Codex", ()),
    "development": ("the Rust toolchain and build tools", ()),
    "docker": ("the Docker engine and Compose", ()),
    "chat": ("the Discord and Slack terminal clients", ()),
    "gateway": ("one password for the host's web pages over a Cloudflare tunnel", ()),
    "jj": ("the Jujutsu (jj) version control tool", ()),
    "fdu": ("fdu, a fast gitignore-aware du for large worktrees", ()),
    "fleet_guards": ("the Docker guard, reapers and storage guard", ("docker",)),
    "project_databases": ("one dev database per project", ("docker",)),
    "fleet_browsers": ("the browser ladder", ()),
    "forgejo": ("a self-hosted Forgejo git server on loopback for agent pushes", ()),
    "tailscale": ("the Tailscale daemon", ()),
    "koncreet": ("the Koncreet host hardening toolkit, installed as root and never run", ()),
    "desktop": ("an XFCE desktop over noVNC", ()),
    "board": ("the crew message board", ("development",)),
}
# The files agent_instructions writes (scripts/instructions.py TARGETS), under the home.
INSTRUCTION_FILES = (".claude/CLAUDE.md", ".omp/agent/AGENTS.md", ".codex/AGENTS.md")
INSTRUCTION_MODES = {"skip": "leave them as they are", "overwrite": "replace them, after a timestamped .bak", "append": "add one marked block"}
# A container worker image has no Docker, no user services, no desktop and no Firstmate.
NOT_IN_CONTAINER = {
    "docker", "chat", "gateway", "fleet_guards", "project_databases", "tailscale", "desktop", "board", "koncreet", "forgejo",
}


def validate_document(document, schema_name):
    schema = json.loads((ROOT / "blueprint/schemas" / schema_name).read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    try:
        jsonschema.Draft202012Validator(schema).validate(document)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ValueError(f"{schema_name}: invalid {location} ({error.validator})") from None


def validate_config(document):
    config = document.get("crewship") if isinstance(document, dict) else None
    if isinstance(config, dict) and (
        isinstance(config.get("profiles"), dict) and REMOVED_PROFILE in config["profiles"]
        or isinstance(config.get("fleet"), dict)
        and any(key in config["fleet"] for key in REMOVED_FLEET_KEYS)
    ):
        raise ValueError(
            "Shared Supabase support was removed. Remove profiles.shared_supabase, "
            "fleet.supabase_project_id, fleet.fixture_archive, and fleet.worktree_pools "
            "from the host config; use profiles.project_databases "
            "(docs/project-databases.md). Existing stacks and volumes remain untouched."
        )
    validate_document(document, "crewship.schema.json")
    profiles = document["crewship"]["profiles"]
    for alias, name in PROFILE_ALIASES.items():
        if alias in profiles:
            if profiles.setdefault(name, profiles[alias]) != profiles[alias]:
                raise ValueError(f"profiles.{alias} is another name of profiles.{name}; set only one")
            del profiles[alias]
            print(f"NOTE: crewship.profiles.{alias} is now crewship.profiles.{name}; "
                  "the old name still works, rename it in your host config.", file=sys.stderr)
    config = document["crewship"]
    home, workspace = Path(config["home"]), Path(config["workspace"])
    if (
        ".." in home.parts
        or ".." in workspace.parts
        or home == Path("/home")
        or not workspace.is_relative_to(home)
        or workspace == home
    ):
        raise ValueError(
            "workspace must be a proper descendant of an operator home; traversal is forbidden"
        )
    if config["user"] == "root":
        raise ValueError("use a non-root operator account")
    if config["profiles"]["firstmate"] and not config["profiles"]["agents"]:
        raise ValueError("Firstmate requires the agents profile")
    if config["profiles"].get("fleet_guards"):
        if not (config["profiles"]["docker"] and config["profiles"]["firstmate"]):
            raise ValueError("fleet guards require the docker and firstmate profiles")
    if config["profiles"].get("project_databases"):
        if not (config["profiles"]["docker"] and config["profiles"]["firstmate"]):
            raise ValueError("project databases require the docker and firstmate profiles")
    skills = config.get("skills", {})
    if "private_ref" in skills and skills["private_source"].startswith("/"):
        raise ValueError("skills.private_ref applies only to a git source; remove it for a local path")
    for block in ("imessage", "github_board"):
        if block in config and not config["profiles"]["firstmate"]:
            raise ValueError(f"{block} requires the firstmate profile")
    if "board" in config and not (
        config["profiles"]["firstmate"] and config["profiles"]["development"]
    ):
        raise ValueError(
            "board requires the firstmate profile and the development profile (it builds with cargo)"
        )
    if "ci_pool" in config:
        pool = config["ci_pool"]
        if not config["profiles"]["docker"]:
            raise ValueError("the CI pool requires the docker profile")
        if ".." in Path(pool["data_dir"]).parts:
            raise ValueError("ci_pool.data_dir must not traverse; give a plain path")
        # Unit instance names; the same rule as slug() in blueprint/maintenance/ci-pool.py.
        slugs = [re.sub(r"[^a-z0-9]+", "-", e["repo"].lower()).strip("-") for e in pool["repos"]]
        if len(set(slugs)) != len(slugs):
            raise ValueError("ci_pool.repos names a repository twice (or two that share a unit name)")
    prune = config["browser_prune"]
    if prune["enabled"] and not config["profiles"]["agents"]:
        raise ValueError("browser pruning requires the agents profile")
    if (
        prune["max_gap_seconds"] < 2 * prune["poll_seconds"]
        or prune["idle_seconds"] < 2 * prune["poll_seconds"]
    ):
        raise ValueError("pruning idle/gap windows must allow at least two observation intervals")
    return document


def migrate_config(path, document):
    """Rewrite the old config root key; preserve all other keys and values."""
    if not isinstance(document, dict) or OLD_ROOT not in document:
        return document
    if NEW_ROOT in document:
        raise ValueError("host config contains both old and new keys; resolve them before rewriting")
    document = {NEW_ROOT if key == OLD_ROOT else key: value for key, value in document.items()}
    backup = path.with_name(path.name + ".bak")
    # Exclusive creation keeps the first backup and refuses an ambiguous retry.
    try:
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError(
            f"Backup already exists: {backup}; keep it and move it aside before retrying {path}"
        ) from None
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(path.read_bytes())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(document, stream, sort_keys=False)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(
        f"Rewrote {path} to Crewship config keys; original comments remain only in backup: {backup}",
        file=sys.stderr,
    )
    return document


def load_config(path):
    try:
        document = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        raise ValueError("malformed host YAML; configuration contents omitted") from None
    document = migrate_config(path, document)
    validate_config(document)
    if any(key in document["crewship"].get("browsers", {}) for key in LEGACY_BROWSER_KEYS):
        print(
            "WARNING: crewship.browsers.obscura_version and crewship.browsers.obscura_sha256 "
            "are no longer used and are ignored; Obscura always resolves to its latest release. "
            f"Remove them from {path} when convenient.",
            file=sys.stderr,
        )
    return document


def parse_choice(text, names):
    """Names, checklist numbers, all or none, split by commas or spaces; ValueError on any other word."""
    chosen = []
    for word in text.replace(",", " ").split():
        word = PROFILE_ALIASES.get(word.lower(), word.lower())
        if word == "none":
            continue
        if word == "all":
            chosen += names
        elif word.isdigit() and 0 < int(word) <= len(names):
            chosen.append(names[int(word) - 1])
        elif word in OPT_IN:
            chosen.append(word)
        else:
            raise ValueError(f"unknown choice {word!r}; names: {', '.join(names)}")
    return chosen


def choose(args, names):
    """The opt-ins of a new host: --with, else a checklist on a terminal, else none."""
    if args.with_ is not None:
        chosen = parse_choice(" ".join(args.with_), names)
        missing = [name for name in chosen if name not in names]
        if missing:
            raise ValueError(f"{', '.join(missing)} cannot be turned on with --container")
    elif sys.stdin.isatty():
        print("Crewship installs the core: omp agents and Firstmate. Choose what else to install.")
        for number, name in enumerate(names, 1):
            print(f"  {number:>2}. {name:<16} {OPT_IN[name][0]}")
        while True:
            try:
                answer = input("Numbers or names, separated by spaces; all; Enter for none: ")
                chosen = parse_choice(answer, names)
                break
            except ValueError as error:
                print(error)
            except EOFError:
                chosen = []
                break
    else:
        chosen = []
    for name in list(chosen):  # what a choice needs comes with it
        chosen += [need for need in OPT_IN[name][1] if need not in chosen]
    return chosen


def ask_instructions_mode(args, chosen, home):
    """The checklist's mode for a file the instructions would touch; None when it does not ask (append is the default)."""
    if "agent_instructions" not in chosen or args.with_ is not None or not sys.stdin.isatty():
        return None
    found = [rel for rel in INSTRUCTION_FILES if (Path(home) / rel).exists() or (Path(home) / rel).is_symlink()]
    if not found:
        return None
    print(f"These files already exist: {', '.join('~/' + rel for rel in found)}. What should Crewship do with them?")
    for mode, text in INSTRUCTION_MODES.items():
        print(f"  {mode:<10} {text}")
    while True:
        try:
            answer = input("skip, overwrite or append; Enter for append: ").strip().lower() or "append"
        except EOFError:
            return None
        if answer in INSTRUCTION_MODES:
            return answer
        print(f"unknown mode {answer!r}")


def initialize(args):
    config = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    current = pwd.getpwuid(os.getuid())
    user = args.user or (current.pw_name if current.pw_uid != 0 else "coder")
    home = args.home or (
        current.pw_dir if user == current.pw_name and current.pw_uid != 0 else f"/home/{user}"
    )
    config["crewship"].update(user=user, home=home, workspace=str(Path(home) / "Dev"))
    if args.container:
        config["crewship"].update(start_services=False, enable_linger=False)
        config["crewship"]["profiles"]["firstmate"] = False
        config["crewship"]["browser_prune"]["enabled"] = False
    names = [name for name in OPT_IN if not (args.container and name in NOT_IN_CONTAINER)]
    chosen = choose(args, names)
    mode = ask_instructions_mode(args, chosen, home)
    if mode:
        config["crewship"]["instructions_mode"] = mode
    for name in OPT_IN:
        if name == "board":
            if name in chosen:
                config["crewship"]["board"] = {}
        elif not (args.container and name in NOT_IN_CONTAINER):
            config["crewship"]["profiles"][name] = name in chosen
    destination = ROOT / ".local/host.yml"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Validate before writing; a bad argument must not strand an unusable config.
    validate_config(config)
    with destination.open("x") as stream:
        yaml.safe_dump(config, stream, sort_keys=False)
    destination.chmod(0o600)
    print(f"Created {destination}; review profiles before ./ship.sh launch.")


def provision(document, check):
    home = Path(document["crewship"]["home"])
    if (home / RETIRED_STACK).exists():
        print(
            "Existing Supabase stack remains untouched: to remove it manually, stop the "
            "crewship-/flotilla-shared-supabase and worktree-env-seed user units, run "
            "~/oss-fleet/shared-supabase/node_modules/.bin/supabase stop --workdir "
            "~/oss-fleet/shared-supabase, then remove those units, the CLI shim and scripts; "
            "keep all Docker volumes. Use docs/project-databases.md for the replacement."
        )
    environment = {**os.environ, "ANSIBLE_CONFIG": str(ROOT / "blueprint/ansible/ansible.cfg")}
    argv = [
        "ansible-playbook",
        "-i",
        str(ROOT / "blueprint/ansible/inventory.yml"),
        str(ROOT / "blueprint/ansible/site.yml"),
        "--extra-vars",
        json.dumps(document),
    ]
    if check:
        argv.append("--check")
    if (
        os.geteuid() != 0
        and subprocess.run(
            ["sudo", "-n", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
    ):
        if not sys.stdin.isatty():
            raise ValueError(
                "sudo access required; run interactively to supply the become password"
            )
        argv.append("--ask-become-pass")
    return subprocess.run(argv, cwd=ROOT, env=environment).returncode


def host_environment(config):
    home = Path(config["home"])
    return {
        **os.environ,
        "HOME": str(home),
        "PATH": str(home / ".local/bin") + ":/usr/local/bin:/usr/bin:/bin",
    }


def tool_checks(config, environment):
    tools = ["herdr", "node", "bun", "uv", "git", "rg", "sgrep"]
    if config["profiles"]["agents"]:
        tools += [
            "omp",
            "gh",
            "no-mistakes",
            "treehouse",
            "gws",
            "gh-axi",
            "chrome-devtools-axi",
            "tasks-axi",
            "quota-axi",
            "lavish-axi",
            "acpx",
        ]
    if config["profiles"]["development"]:
        tools += ["rustc", "cargo"]
    if config["profiles"].get("gateway"):  # off unless the host config turns it on
        tools.append("cloudflared")
    for name in tools:
        path = shutil.which(name, path=environment["PATH"])
        if not path:
            yield name, False, f"MISSING {name}"
            continue
        try:
            result = subprocess.run(
                [path, "--version"], env=environment, capture_output=True, text=True, timeout=20
            )
            if result.returncode:
                yield name, False, f"FAILED {name}: exit {result.returncode}"
            else:
                text = (result.stdout or result.stderr).splitlines()
                yield name, True, f"OK {name}: {text[0] if text else path}"
        except (OSError, subprocess.TimeoutExpired):
            yield name, False, f"FAILED {name}: version command unavailable or timed out"


def github_signed_in(environment):
    try:
        return subprocess.run(
            ["gh", "auth", "status", "--hostname", "github.com"],
            env=environment, cwd=environment["HOME"], capture_output=True, timeout=20,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def omp_signed_in(environment):
    try:
        probe = subprocess.run(
            ["omp", "models", "--json"], env=environment,
            cwd=environment["HOME"], capture_output=True, text=True, timeout=30,
        )
        models = json.loads(probe.stdout)["models"]
        return probe.returncode == 0 and isinstance(models, list) and bool(models)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return False


def doctor(document):
    config = document["crewship"]
    environment = host_environment(config)
    checks = list(tool_checks(config, environment))
    failed = [name for name, ok, _ in checks if not ok]
    for _, _, message in checks:
        print(message)
    if config["profiles"]["agents"]:
        authenticated = github_signed_in(environment)
        print(
            "GitHub authentication: "
            + ("present" if authenticated else "manual gh auth login required")
        )
        print(
            "Provider access: authenticate OMP interactively; subscriptions/model availability are not inferred."
        )
    if config["start_services"]:
        print(
            "Native services: verify systemctl --user status herdr chrome-autoprune.timer as the operator."
        )
    print(
        "Software checks: "
        + (
            "FAILED " + ", ".join(failed)
            if failed
            else "passed; authentication/network prerequisites are separate"
        )
    )
    return 1 if failed else 0


def firstmate_checks(config, environment):
    pending = []
    if not config["profiles"]["firstmate"]:
        return pending
    home = Path(config["home"])
    if not (Path(config["workspace"]) / "firstmate/bin/fm-home-seed.sh").is_file():
        pending.append("Firstmate installation")
    if not (home / ".local/share/crewship/new-host-questions-done").is_file():
        pending.append("new-host questions")
    if config["start_services"]:
        runtime = f"/run/user/{os.getuid()}"
        environment = {
            **environment,
            "XDG_RUNTIME_DIR": runtime,
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus",
        }
        try:
            service = subprocess.run(
                ["systemctl", "--user", "is-active", "--quiet", "herdr.service"],
                env=environment, capture_output=True, timeout=20,
            )
            if service.returncode:
                pending.append("Herdr service")
        except (OSError, subprocess.TimeoutExpired):
            pending.append("Herdr service")
    return pending


def setup_status(document, config_path):
    config = document["crewship"]
    command = shlex.join([str(ROOT / "ship.sh"), "launch", "--config", str(config_path)])
    resume = shlex.join([str(ROOT / "ship.sh"), "setup", "--config", str(config_path)])
    if pwd.getpwuid(os.getuid()).pw_name != config["user"]:
        resume = shlex.join([
            "sudo", "-iu", config["user"], str(ROOT / "ship.sh"),
            "setup", "--config", str(config_path),
        ])
        for section in ("Software", "Sign-ins", "Fleet ready"):
            print(f"{section}: unchecked; run: {resume}")
        return 1
    environment = host_environment(config)
    failed = [name for name, ok, _ in tool_checks(config, environment) if not ok]
    print(f"Software: missing or failed {', '.join(failed)}; run: {command}"
          if failed else "Software: ready")
    missing = []
    if config["profiles"]["agents"]:
        if not github_signed_in(environment):
            gh = shlex.quote(shutil.which("gh", path=environment["PATH"]) or "gh")
            missing.append(f"{gh} auth login --hostname github.com --git-protocol https --web")
        if not omp_signed_in(environment):
            missing.append(shlex.quote(str(Path(config["home"]) / ".local/bin/omp")))
    print(f"Sign-ins: pending; run: {' && '.join(missing)}"
          if missing else "Sign-ins: ready")
    pending = firstmate_checks(config, environment)
    if failed or missing:
        print(f"Fleet ready: no; finish the commands above, then run: {resume}")
    elif pending:
        print(f"Fleet ready: no ({', '.join(pending)}); run: {command}")
    elif not config["profiles"]["firstmate"]:
        print("Fleet ready: not enabled (worker-only profile)")
    elif not config["start_services"]:
        edit_config = f"${{EDITOR:-nano}} {shlex.quote(str(config_path))}"
        print(f"Fleet ready: no (start_services is false); enable services with: {edit_config}")
        return 1
    else:
        print("Fleet ready: setup checks passed; a live agent task is not verified")
    return int(bool(failed or missing or pending))


def questions(document, config_path):
    """Open Firstmate on omp to ask the operator the new-host move questions."""
    config = document["crewship"]
    home = Path(config["home"])
    environment = host_environment(config)
    marker = home / ".local/share/crewship/new-host-questions-done"
    if (
        not sys.stdin.isatty()
        or os.environ.get("CI")
        or pwd.getpwuid(os.getuid()).pw_name != config["user"]
    ):
        print(
            "New-host questions skipped (needs an interactive terminal); "
            f"rerun ./ship.sh launch interactively as {config['user']} to start them "
            f"(asked once, then {marker} records it)"
        )
        return 0
    if marker.exists():
        print(
            f"New-host questions already asked ({marker} exists); delete it and rerun "
            f"./ship.sh launch interactively as {config['user']} to ask them again"
        )
        return 0
    omp = home / ".local/bin/omp"
    firstmate = Path(config["workspace"]) / "firstmate"
    if not omp_signed_in(environment):
        print(
            f"New-host questions not started: sign in to omp with /login (run omp as "
            f"{config['user']}), then rerun ./ship.sh launch interactively"
        )
        return 0
    source = f"the runbook {ROOT / 'docs/agent-host-move.md'}"
    checklist = config["firstmate"].get("checklist")
    if checklist:
        api = f"repos/{checklist['repo']}/contents/{checklist['path']}"
        try:
            readable = (
                subprocess.run(
                    ["gh", "api", api, "--silent"], env=environment, capture_output=True, timeout=20
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            readable = False
        if readable:
            source = (
                f"the operator's private checklist (read it with `gh api {api} "
                "-H 'Accept: application/vnd.github.raw'`; never copy its contents "
                "into a public repository)"
            )
        else:
            print(
                f"Checklist {checklist['repo']}:{checklist['path']} is not readable; using {source}"
            )
    prompt = (
        "Crewship software is installed on this host. Walk me through the new-host move "
        "decisions one question at a time, waiting for my answer before the next: which "
        "secondmate homes, services, tools and unpushed work to bring over from the old "
        f"host. Use {source} as the checklist."
    )
    if "github_board" not in config:
        prompt += (
            " Then ask one short question: turn on the optional GitHub board, which mirrors "
            f"Firstmate work to issues and a Project? If yes, follow {ROOT / 'docs/github-board.md'}."
        )
    if "board" not in config and config["profiles"]["development"]:
        prompt += (
            " Then ask one short question: turn on the crew board, a host-local message "
            f"board for agent-to-agent messages? If yes, follow {ROOT / 'docs/board.md'}."
        )
    if not config["profiles"].get("project_databases"):
        prompt += (
            " Then ask one short question: enable the optional per-project dev databases? "
            "It is off by default and needs Docker and Firstmate. "
            "If yes, set crewship.profiles.project_databases to true in "
            f"{config_path} and follow {ROOT / 'docs/project-databases.md'}."
        )
    returncode = subprocess.run([omp, prompt], cwd=firstmate, env=environment).returncode
    if returncode:
        print(
            f"New-host questions did not complete (omp exited {returncode}); rerun "
            f"./ship.sh launch interactively as {config['user']} to ask them again"
        )
        return returncode
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    return 0


def main():
    parser = argparse.ArgumentParser(prog="ship.sh", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dock = commands.add_parser(
        "dock", help="create ignored host config for this login; never overwrite"
    )
    dock.add_argument("--user")
    dock.add_argument("--home")
    dock.add_argument("--container", action="store_true")
    dock.add_argument(
        "--with",
        dest="with_",
        action="append",
        metavar="NAMES",
        help="opt-in features to turn on, comma separated, instead of the checklist "
        f"(none for none): {', '.join(OPT_IN)}",
    )
    for name, text in (
        ("inspect", "check the host config against the schema; old config keys are rewritten once"),
        ("chart", "preview provisioning changes; old config keys are rewritten once"),
        ("launch", "provision this host from the host config; old config keys are rewritten once"),
        ("survey", "check expected tools; old config keys are rewritten once"),
        ("setup", "report software, sign-ins and Firstmate readiness; rerun after each missing step"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    if args.command == "dock":
        initialize(args)
        return 0
    path = args.config or (
        ROOT / ".local/host.yml"
        if args.command == "setup" or (ROOT / ".local/host.yml").exists()
        else ROOT / "blueprint/config/default.yml"
    )
    path = path.resolve()
    if args.command == "setup" and not path.is_file():
        if args.config:
            recovery = f"restore the selected config with: ${{EDITOR:-nano}} {shlex.quote(str(path))}"
        else:
            recovery = f"run: {shlex.join([str(ROOT / 'ship.sh'), 'dock'])}"
        print(f"Software: unchecked (missing config {path}); {recovery}")
        print(f"Sign-ins: unchecked; {recovery}")
        print(f"Fleet ready: no; {recovery}")
        return 1
    document = load_config(path)
    if args.command == "setup":
        return setup_status(document, path)
    if args.command == "inspect":
        print(f"Valid host configuration: {path}")
        return 0
    if args.command == "survey":
        return doctor(document)
    if args.command == "launch" and args.config is None and not (ROOT / ".local/host.yml").exists():
        raise ValueError(
            "run ./ship.sh dock and review .local/host.yml before launching, or pass an explicit --config"
        )
    result = provision(document, args.command == "chart")
    config = document["crewship"]
    if args.command == "launch" and config["profiles"]["firstmate"]:
        if config["firstmate"]["url"] == STALE_FIRSTMATE_URL:
            print(
                f"WARNING: firstmate.url is the stale fork {STALE_FIRSTMATE_URL}; this host "
                "is not tracking upstream Firstmate. Move it with the steps in "
                f"{ROOT / 'docs/configuration.md'} (Moving off the old Firstmate fork).",
                file=sys.stderr,
            )
        if result == 0:
            questions(document, path)
    return result


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, jsonschema.ValidationError, subprocess.TimeoutExpired) as error:
        print(f"ship.sh: {error}", file=sys.stderr)
        sys.exit(1)
