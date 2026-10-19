#!/usr/bin/env python3
"""Install the repository's skills for omp and Claude Code, and its rules for omp.

blueprint/skills/public/<name>/ and blueprint/rules/public/<name>.md ship with Crewship;
a folder with no SKILL.md of its own groups skills as <group>/<name>/: the group installs whole, with its
links kept, and each skill in it installs as a link <name> -> <group>/<name>, so they share the group's files.
blueprint/skills/private/<name>/ and blueprint/rules/private/<name>.md stay on the host and win
over a public one of the same name. With --private-source (a local directory,
or a git URL fetched at --private-ref, default HEAD), the skills at its top
level and the rules in its rules/ folder are first copied into blueprint/skills/private/
and blueprint/rules/private/; without it, the items an earlier fill added are removed
from there. Each item is then copied into every root of its kind in KINDS. A
manifest records the names this script installed, so an item the operator put
there by hand is never replaced or removed. stdout is one JSON result.

--public chooses the public items: yes installs them, no leaves them out, and auto
installs them only on a host whose manifest already lists some. Public items an
earlier run installed are never removed because of this choice.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]


def find_skills(d):
    """Skills by installed name; a skill in a group maps to a PurePosixPath, installed as a link into the group."""
    found = {p.parent.name: p.parent for p in sorted(d.glob("*/SKILL.md"))}
    for p in sorted(d.glob("*/*/SKILL.md")):
        group = p.parent.parent
        if not (group / "SKILL.md").exists():
            found[group.name] = group
            found[p.parent.name] = PurePosixPath(group.name, p.parent.name)
    return found


# kind: (its items in a folder by installed name, its folder in the private source, its roots)
KINDS = {
    "skills": (find_skills, ".", (".omp/agent/skills", ".claude/skills")),
    "rules": (
        lambda d: {p.name: p for p in sorted(d.glob("*.md")) if p.name != "README.md"},
        "rules",
        (".omp/agent/rules",),
    ),
}
MANIFEST = ".local/share/crewship/skills.json"
CACHE = ".cache/crewship/private-skills"


def fetch(source, ref, cache):
    """Return the private source directory; a git URL is fetched into cache."""
    if source.startswith("/"):
        if not Path(source).is_dir():  # a missing source must never read as "no skills"
            raise FileNotFoundError(source)
        return Path(source)
    # Credentials come from the account's own git and GitHub sign-in; never prompt.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if not (cache / ".git").is_dir():
        subprocess.run(["git", "init", "-q", str(cache)], check=True, env=env)
    for step in (["fetch", "-q", "--depth", "1", source, ref], ["checkout", "-qf", "FETCH_HEAD"]):
        subprocess.run(["git", "-C", str(cache), *step], check=True, env=env)
    return cache


def tree(path):
    if path.is_file():
        return path.read_bytes(), path.stat().st_mode & 0o111
    if not path.is_dir():
        return None
    return {p.relative_to(path).as_posix(): tree(p) for p in path.rglob("*") if p.is_file()}


def remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def sync(wanted, base, mine, skipped, keep=()):
    """Copy each wanted item into base and remove the ones in mine that are no longer wanted, except keep."""
    changed = False
    for name, source in wanted.items():
        target = base / name
        if name not in mine and (target.exists() or target.is_symlink()):
            skipped.append(str(target))
            continue
        mine.add(name)  # claimed before the copy, so a failed copy is retried
        link = not isinstance(source, Path)
        same = target.is_symlink() and target.readlink() == Path(source) if link else tree(target) == tree(source)
        if same:
            continue
        remove(target)
        base.mkdir(parents=True, exist_ok=True)
        if link:
            target.symlink_to(source)
        elif source.is_dir():
            # a group keeps its links, so its skills share one copy of its files
            shutil.copytree(source, target, symlinks=not (source / "SKILL.md").exists())
        else:
            shutil.copy(source, target)
        changed = True
    for name in mine - wanted.keys() - set(keep):
        remove(base / name)
        mine.discard(name)
        changed = True
    return changed


def install(home, repo=REPO, private_source=None, private_ref="HEAD", skip_rules=(), public="yes"):
    record = home / MANIFEST
    blueprint = repo / "blueprint"
    owned = json.loads(record.read_text()) if record.is_file() else {}
    keys = [key for kind, (_, _, roots) in KINDS.items() for key in (f"{kind}/private", *roots)]
    owned = {key: set(owned.get(key, [])) for key in keys}
    before = json.dumps({r: sorted(n) for r, n in owned.items()}, sort_keys=True) + "\n"
    publics = {kind: find(blueprint / kind / "public") for kind, (find, _, _) in KINDS.items()}
    if public == "auto":  # a host that has public items keeps them current
        has = any(owned[root] & publics[kind].keys() for kind, (_, _, roots) in KINDS.items() for root in roots)
        public = "yes" if has else "no"
    changed, installed, skipped = False, {}, []
    try:
        private = fetch(private_source, private_ref, home / CACHE) if private_source else None
        for kind, (find, folder, roots) in KINDS.items():
            filled = find(private / folder) if private else {}
            changed |= sync(filled, blueprint / kind / "private", owned[f"{kind}/private"], skipped)
            # private last, so it wins a name clash
            wanted = {**(publics[kind] if public == "yes" else {}), **find(blueprint / kind / "private")}
            if kind == "rules":
                wanted = {name: path for name, path in wanted.items() if name not in skip_rules}
            installed[kind] = sorted(wanted)
            # public items already on the host stay when public is off, except a skipped rule
            keep = set() if public == "yes" else publics[kind].keys() - (set(skip_rules) if kind == "rules" else set())
            for root in roots:
                changed |= sync(wanted, home / root, owned[root], skipped, keep)
    finally:
        text = json.dumps({r: sorted(n) for r, n in owned.items()}, sort_keys=True) + "\n"
        if text != before:
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(text)
    return {"changed": changed, "installed": installed, "skipped": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--private-source")
    parser.add_argument("--private-ref", default="HEAD")
    parser.add_argument("--skip-rule", action="append", default=[])
    parser.add_argument("--public", choices=("yes", "no", "auto"), default="yes")
    args = parser.parse_args()
    home = args.home.resolve(strict=True)
    print(json.dumps(install(home, REPO, args.private_source, args.private_ref, args.skip_rule, args.public)))
