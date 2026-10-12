"""site/ is the crewship.si website: it must never reach a host or an image."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
HARBOR = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "site").rglob("*") if p.is_file())


def _docker_excludes(path, patterns):
    """Docker's .dockerignore rule: the last pattern matching the path or a parent decides."""
    parts = path.split("/")
    excluded = False
    for raw in patterns:
        negate = raw.startswith("!")
        glob = raw[negate:].strip("/")
        regex = (
            re.escape(glob).replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        )
        if any(re.fullmatch(regex, "/".join(parts[:i])) for i in range(1, len(parts) + 1)):
            excluded = not negate
    return excluded


def _ansible_sources(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "src" and isinstance(value, str):
                yield value
            yield from _ansible_sources(value)
    elif isinstance(node, list):
        for item in node:
            yield from _ansible_sources(item)


def test_harbor_never_reaches_an_image_or_a_host():
    assert HARBOR, "site/ has no files"

    # Images: the Dockerfile copies the whole build context, so .dockerignore must drop site/.
    patterns = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert [p for p in HARBOR if not _docker_excludes(p, patterns)] == []

    # Hosts: the playbook copies named paths out of the checkout, never the checkout itself.
    variables = {k: v for f in sorted((ROOT / "blueprint/ansible/group_vars/all").glob("*.yml")) for k, v in yaml.safe_load(f.read_text()).items()}
    variables["crewship_repo"] = "REPO"
    variables["crewship_blueprint"] = "REPO/blueprint"

    def expand(value):
        for _ in range(5):
            value = re.sub(
                r"\{\{\s*(\w+)\s*\}\}",
                lambda m: str(variables.get(m.group(1), m.group(0))),
                value,
            )
        return value

    sources = [
        expand(src)
        for task_file in sorted((ROOT / "blueprint/ansible").rglob("*.yml"))
        for src in _ansible_sources(yaml.safe_load(task_file.read_text()))
    ]
    from_checkout = [s[len("REPO") :].strip("/") for s in sources if s.startswith("REPO")]
    assert from_checkout, "no playbook source resolved to the checkout"
    assert "" not in from_checkout
    assert [s for s in from_checkout if s == "site" or s.startswith("site/")] == []
