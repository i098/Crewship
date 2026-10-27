"""Build the harbor and crawlable repository documentation using only the standard library.

The scene's features and release follow README.md, docs/features.md, and CHANGELOG.md.
README.md, SETUP.md, and docs/*.md also become HTML guides under /docs.
"""

import html
import json
import posixpath
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

HARBOR = Path(__file__).resolve().parent
ROOT = HARBOR.parent
REPO = "https://github.com/i098/Crewship"
ORIGIN = "https://crewship.si"
MARK = "<!-- points: site/build.py fills this list from README.md and CHANGELOG.md -->"
FOOT_MARK = "<!-- footer: site/build.py fills the architecture link -->"

# Each Features link maps to its scene object; unmapped docs share a summary and index link.
SCENE = {
    "docs/configuration.md": ("helm", "The helm"),
    "docs/dependencies.md": ("hold", "The cargo hold"),
    "docs/fleet-guards.md": ("lantern", "The bow lantern"),
    "docs/herdr.md": ("nest", "The crow's nest"),
    "tools/herdr-patch/README.md": ("spyglass", "The spyglass"),
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
            "/how",
            "How the text scene works.",
        ),
    ]
    return rows


def doc_routes():
    """One stable URL per published source; keep nested developer docs on GitHub."""
    sources = [ROOT / "README.md", ROOT / "SETUP.md", *sorted((ROOT / "docs").glob("*.md"))]
    return {p.relative_to(ROOT).as_posix(): f"/docs/{p.stem.lower()}" for p in sources}


def doc_link(link, source, routes, image=False):
    """Resolve links from their Markdown location, not from the generated HTML path."""
    parsed = urlsplit(html.unescape(link))
    if parsed.scheme or parsed.netloc:
        return link if parsed.scheme.lower() in ("http", "https", "mailto", "") else "#"
    if not parsed.path:
        return link
    path = posixpath.normpath(posixpath.join(posixpath.dirname(source), unquote(parsed.path)))
    if not image and path in routes:
        return urlunsplit(("", "", routes[path], parsed.query, parsed.fragment))
    base = "https://raw.githubusercontent.com/i098/Crewship/main/" if image else f"{REPO}/blob/main/"
    return urljoin(base + source, link)


INLINE = re.compile(
    r"\\[\\`*_{}\[\]()#+.!|>-]"
    r"|(?P<ticks>`+)(?P<code>.+?)(?P=ticks)(?!`)"
    r"|(?P<image>!?)\[(?P<label>(?:[^\[\]]|\[[^\[\]]*\])*)\]"
    r'\((?P<url><[^>]+>|(?:\\.|[^()\s]|\([^()]*\))+)(?:\s+"[^"]*")?\)'
    r"|(?P<auto><(?:https?://|mailto:)[^>]+>)"
    r"|(?P<strong>\*\*|__)(?P<bold>.+?)(?P=strong)"
    r"|(?P<em>\*|(?<!\w)_)(?P<italic>.+?)(?P=em)(?!\w)"
)


def doc_inline(text, source, routes):
    parts, end = [], 0
    for match in INLINE.finditer(text):
        parts.append(html.escape(text[end : match.start()]))
        if match.group("code") is not None:
            value = f'<code>{html.escape(match["code"])}</code>'
        elif match.group("url") is not None:
            url = doc_link(match["url"].strip("<>"), source, routes, bool(match["image"]))
            if match["image"]:
                value = (
                    f'<img src="{html.escape(url)}" alt="{html.escape(match["label"])}"'
                    ' loading="lazy">'
                )
            else:
                value = f'<a href="{html.escape(url)}">{doc_inline(match["label"], source, routes)}</a>'
        elif match.group("auto") is not None:
            url = match["auto"][1:-1]
            value = f'<a href="{html.escape(doc_link(url, source, routes))}">{html.escape(url)}</a>'
        elif match.group("bold") is not None:
            value = f'<strong>{doc_inline(match["bold"], source, routes)}</strong>'
        elif match.group("italic") is not None:
            value = f'<em>{doc_inline(match["italic"], source, routes)}</em>'
        else:
            value = html.escape(match[0][1:])
        parts.append(value)
        end = match.end()
    parts.append(html.escape(text[end:]))
    return "".join(parts)


class DocHTML(HTMLParser):
    """Keep repository pictures and links, never arbitrary HTML or event attributes."""

    def __init__(self, source, routes):
        super().__init__()
        self.source, self.routes, self.parts = source, routes, []

    def handle_starttag(self, tag, attrs):
        allowed = {
            "a": ("href",),
            "picture": (),
            "source": ("srcset", "media"),
            "img": ("src", "alt"),
            "br": (),
        }
        if tag == "div":
            return
        if tag not in allowed:
            self.parts.append(html.escape(self.get_starttag_text()))
            return
        safe = []
        for key, value in attrs:
            if key not in allowed[tag] or value is None:
                continue
            if key in ("href", "src", "srcset"):
                value = doc_link(value, self.source, self.routes, key != "href")
            safe.append(f' {key}="{html.escape(value)}"')
        if tag == "img":
            safe.append(' loading="lazy"')
        self.parts.append(f"<{tag}{''.join(safe)}>")

    def handle_endtag(self, tag):
        if tag in ("a", "picture"):
            self.parts.append(f"</{tag}>")
        elif tag not in ("div", "source", "img", "br"):
            self.parts.append(html.escape(f"</{tag}>"))

    def handle_data(self, data):
        self.parts.append(html.escape(data))


FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
HTML_HEADING = re.compile(r"<h([1-6])(?:\s[^>]*)?>(.*?)</h\1>", re.I)
LIST = re.compile(r"^(\s*)([-+*]|\d+[.)])\s+(.+)$")
RAW_HTML = re.compile(r"</?(?:a|div|picture|source|img|br)\b", re.I)
RULE = re.compile(r"^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")


def plain_text(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", markup)).split())


def table_cells(line):
    return [
        cell.replace(r"\|", "|")
        for cell in re.split(r"(?<!\\)\|", line.strip().removeprefix("|").removesuffix("|"))
    ]


def render_markdown(markdown, source, routes, headings=None):
    """Render the repository's Markdown subset, including nested lists and safe pictures."""
    headings = {} if headings is None else headings
    lines, output, i = markdown.splitlines(), [], 0

    def table_at(index):
        return (
            index + 1 < len(lines)
            and "|" in lines[index]
            and all(re.fullmatch(r"\s*:?-{3,}:?\s*", c) for c in table_cells(lines[index + 1]))
        )

    def block_at(index):
        line = lines[index].strip()
        return (
            FENCE.match(line) or HEADING.match(line) or HTML_HEADING.fullmatch(line)
            or LIST.match(lines[index]) or line.startswith((">", "<!--"))
            or RAW_HTML.match(line) or RULE.fullmatch(line) or table_at(index)
        )

    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        fence = FENCE.match(line)
        if fence:
            code = []
            while i < len(lines) and not re.fullmatch(
                rf"\s*{re.escape(fence[1][0])}{{{len(fence[1])},}}\s*", lines[i]
            ):
                code.append(lines[i])
                i += 1
            i += 1
            language = re.sub(r"[^a-zA-Z0-9_+-]", "", fence[2].strip().split(" ")[0])
            output.append(
                f'<pre><code class="language-{language}">'
                + html.escape("\n".join(code) + "\n") + "</code></pre>"
            )
        elif line.startswith("<!--"):
            while "-->" not in line and i < len(lines):
                line = lines[i]
                i += 1
        elif (heading := HEADING.match(line)) or (heading := HTML_HEADING.fullmatch(line)):
            level = len(heading[1]) if heading[1].startswith("#") else int(heading[1])
            text = doc_inline(heading[2], source, routes)
            slug = re.sub(r"[^\w\s-]", "", plain_text(text).lower()).strip()
            slug = re.sub(r"\s", "-", slug)
            number = headings.get(slug, 0)
            headings[slug] = number + 1
            anchor = f"{slug}-{number}" if number else slug
            output.append(f'<h{level} id="{html.escape(anchor)}">{text}</h{level}>')
        elif RULE.fullmatch(line):
            output.append("<hr>")
        elif line.startswith(">"):
            quote = [re.sub(r"^>\s?", "", line)]
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            output.append(
                "<blockquote>" + render_markdown("\n".join(quote), source, routes, headings)
                + "</blockquote>"
            )
        elif item := LIST.match(lines[i - 1]):
            ordered = item[2][0].isdigit()
            tag = "ol" if ordered else "ul"
            start = f' start="{int(item[2][:-1])}"' if ordered else ""
            output.append(f"<{tag}{start}>")
            i -= 1
            indent = len(item[1])
            while i < len(lines):
                item = LIST.match(lines[i])
                if not item or len(item[1]) != indent or item[2][0].isdigit() != ordered:
                    break
                width = item.start(3)
                content = [item[3]]
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if next_line.strip() and len(next_line) - len(next_line.lstrip()) <= indent:
                        break
                    content.append(next_line[width:])
                    i += 1
                output.append(
                    "<li>" + render_markdown("\n".join(content), source, routes, headings) + "</li>"
                )
            output.append(f"</{tag}>")
        elif table_at(i - 1):
            output.append('<div class="scroll"><table><thead><tr>')
            output.extend(f"<th>{doc_inline(c.strip(), source, routes)}</th>" for c in table_cells(line))
            output.append("</tr></thead><tbody>")
            i += 1
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                output.append("<tr>")
                output.extend(
                    f"<td>{doc_inline(c.strip(), source, routes)}</td>" for c in table_cells(lines[i])
                )
                output.append("</tr>")
                i += 1
            output.append("</tbody></table></div>")
        elif RAW_HTML.match(line):
            raw = DocHTML(source, routes)
            raw.feed(line)
            output.append("".join(raw.parts))
        else:
            paragraph = [line]
            while i < len(lines) and lines[i].strip() and not block_at(i):
                paragraph.append(lines[i].strip())
                i += 1
            output.append(f'<p>{doc_inline(" ".join(paragraph), source, routes)}</p>')
    return "\n".join(output)


def doc_page(title, description, route, body, source=None):
    canonical = ORIGIN + route
    crumbs = [("Crewship", ORIGIN + "/"), ("Documentation", ORIGIN + "/docs")]
    if source:
        crumbs.append((title, canonical))
    structured = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": url}
            for i, (name, url) in enumerate(crumbs, 1)
        ],
    }, ensure_ascii=False).replace("<", "\\u003c")
    source_link = (
        f' · <a href="{REPO}/blob/main/{html.escape(source)}">View Markdown source</a>'
        if source else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(title)} - Crewship docs</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{canonical}">
<meta name="theme-color" content="#0a0f1c">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="stylesheet" href="/harbor.css">
<script type="application/ld+json">{structured}</script>
</head>
<body class="how about docs">
<header class="top">
  <nav aria-label="Site links"><a href="/">Return to Harbor</a><a href="/about">About</a><a href="/docs">Docs</a></nav>
</header>
<main><article class="post">
{body}
</article></main>
<footer class="foot"><p><a href="/docs">All documentation</a>{source_link}</p></footer>
</body>
</html>
"""


def build_docs(dist):
    routes, entries = doc_routes(), []
    (dist / "docs").mkdir()
    for source, route in routes.items():
        body = render_markdown((ROOT / source).read_text(), source, routes)
        heading = re.search(r"<h1\b[^>]*>(.*?)</h1>", body, re.S)
        title = plain_text(heading[1]) if heading else Path(source).stem
        description = next(
            (plain_text(p) for p in re.findall(r"<p>(.*?)</p>", body, re.S) if plain_text(p)),
            title,
        )
        if len(description) > 160:
            description = description[:157].rsplit(" ", 1)[0] + "..."
        (dist / f"{route.lstrip('/')}.html").write_text(
            doc_page(title, description, route, body, source)
        )
        entries.append(
            f'<li><a href="{route}">{html.escape(title)}</a><p>{html.escape(description)}</p></li>'
        )
    description = "Crewship guides for installation, configuration, coding agents, and host operations."
    index = (
        '<h1 id="documentation">Crewship documentation</h1>'
        f"<p>{description}</p><ul>" + "\n".join(entries) + "</ul>"
    )
    (dist / "docs.html").write_text(doc_page("Documentation", description, "/docs", index))
    urls = ["/", "/how", "/about", "/docs", *routes.values()]
    (dist / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{ORIGIN}{url}</loc></url>\n" for url in urls)
        + "</urlset>\n"
    )


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
    build_docs(dist)
    return dist


if __name__ == "__main__":
    print(build())
