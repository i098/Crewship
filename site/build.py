"""Builds site/dist from site/public and fills the points of interest from the repository.

The features come from README's Features list and More docs row and from docs/features.md,
and the release from CHANGELOG.md, so the page follows Crewship as it changes. Standard library only.
"""

import html
import posixpath
import re
import shutil
import sys
from pathlib import Path

HARBOR = Path(__file__).resolve().parent
ROOT = HARBOR.parent
REPO = "https://github.com/i098/Crewship"
MARK = "<!-- points: site/build.py fills this list from README.md and CHANGELOG.md -->"
FOOT_MARK = "<!-- footer: site/build.py fills the architecture link -->"

# Each Features link maps to its scene object; unmapped docs share a summary and index link.
SCENE = {
    "docs/configuration.md": ("helm", "The helm"),
    "docs/dependencies.md": ("hold", "The cargo hold"),
    "docs/fleet-guards.md": ("lantern", "The bow lantern"),
    "docs/herdr.md": ("nest", "The crow's nest"),
    "herdr-patch/README.md": ("spyglass", "The spyglass"),
    "docs/omp.md": ("mast", "The mast"),
    "docs/chat.md": ("antenna", "The radio mast"),
    "docs/imessage.md": ("bell", "The ship's bell"),
    "docs/capacity.md": ("barrels", "The barrels"),
    "docs/ci-pool.md": ("containers", "The containers"),
    "docs/architecture.md": ("lighthouse", "The lighthouse"),
    "docs/recovery.md": ("lifeboat", "The lifeboat"),
    "docs/security.md": ("cabin", "The cabin"),
    "docs/secrets.md": ("strongbox", "The strongbox"),
    "docs/google-workspace.md": ("mailbox", "The mailbox"),
    "docs/agent-host-move.md": ("tender", "The tender"),
}


def features(readme, index=""):
    """(title, link, description) for each Features link: README highlights (and the links inside
    them), the docs/features.md list given as `index`, and the More docs row."""
    section = readme.split("\n## Features\n", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^- \*{0,2}\[([^\]]+)\]\(([^)]+)\):\*{0,2} (.+)$", section, re.M)
    rows += [
        (title, link, desc)
        for _, _, desc in rows
        for title, link in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", desc)
    ]
    # The list sits in docs/, so its links are relative to it. It only gives scene objects their
    # entry; its other rows stay out of the docs board's sign.
    rows.extend(
        (title, link, desc)
        for title, link, desc in (
            (title, posixpath.normpath(f"docs/{link}"), desc)
            for title, link, desc in re.findall(
                r"^- \[([^\]]+)\]\(([^)]+)\): (.+)$", index, re.M
            )
        )
        if link in SCENE
    )
    more_docs = readme.split("\n## More docs\n", 1)[1].split("\n## ", 1)[0]
    rows.extend(
        (title, link, "Documentation")
        for title, link in re.findall(r"^- \[([^\]]+)\]\(([^)]+)\)$", more_docs, re.M)
    )
    return rows


def inline(text, limit=None):
    """Markdown inline text as HTML: links become their words, code spans stay code."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text).replace("**", "")
    if limit and len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "\u2026"
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text, quote=False))


def first_sentence(markdown):
    prose = next(p for p in markdown.split("\n\n") if p.strip() and p.strip()[0] not in "#<[!|>`-")
    return " ".join(prose.replace("**", "").split()).split(". ", 1)[0].rstrip(".") + "."


def points(readme, changelog, index=""):
    """(spot, title, href, body HTML) for every point of interest."""
    rows, extra = [], []
    for title, link, desc in features(readme, index):
        href = f"{REPO}/blob/main/{link}"
        if link in SCENE:
            rows.append((SCENE[link][0], title, href, inline(desc, 52)))
        else:
            print(
                f"harbor: no scene object for {link}; listing it on the docs board", file=sys.stderr
            )
            url = f"{REPO}/{link[len('../../') :]}" if link.startswith("../../") else href
            extra.append(
                (
                    title.removeprefix("Private ")
                    .removeprefix("Shared ")
                    .replace("Browser ladder", "Browsers")
                    .lower(),
                    url,
                )
            )
    if extra:
        links = ", ".join(
            f'<a target="_blank" rel="noopener" href="{html.escape(url)}">{html.escape(name)}</a>'
            for name, url in extra
        )
        rows.append(("docsboard", "More docs", f"{REPO}#features", links))
    version = re.search(r"^## \[(\d[^\]]*)\]", changelog, re.M).group(1)
    quick = readme.split("\n## Quick start\n", 1)[1]
    rows += [
        (
            "gangway",
            "Quick start",
            f"{REPO}#quick-start",
            inline(first_sentence(quick), 52),
        ),
        (
            "sign",
            "Crewship on GitHub",
            REPO,
            inline(first_sentence(readme), 52),
        ),
        (
            "office",
            f"Releases (v{version})",
            f"{REPO}/releases",
            f"The latest release is v{version}.",
        ),
        (
            "how",
            "How this is built",
            "how.html",
            "How the text scene works.",
        ),
    ]
    return rows


def build(dist=HARBOR / "dist"):
    readme = (ROOT / "README.md").read_text()
    changelog = (ROOT / "CHANGELOG.md").read_text()
    index = (ROOT / "docs/features.md").read_text()
    items = "\n".join(
        f'      <li data-spot="{spot}"{" data-doc" if "/blob/main/" in href else ""}>'
        f'<a target="_blank" rel="noopener" href="{href}">'
        f"{html.escape(title)}</a><p>{body}</p></li>"
        for spot, title, href, body in points(readme, changelog, index)
    )
    shutil.rmtree(dist, ignore_errors=True)
    shutil.copytree(HARBOR / "public", dist)
    page = dist / "index.html"
    footer = f'Read the <a target="_blank" rel="noopener" href="{REPO}/blob/main/docs/architecture.md">Architecture</a>.'
    page.write_text(page.read_text().replace(MARK, items).replace(FOOT_MARK, footer))
    return dist


if __name__ == "__main__":
    print(build())
