"""The static site publishes harbor signs and crawlable repository documentation."""

import importlib.util
import json
import re
import struct
import xml.etree.ElementTree as ET
from collections import Counter
from functools import partial
from html import unescape
from html.parser import HTMLParser
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("harbor_build", ROOT / "site/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)
SERVE_SPEC = importlib.util.spec_from_file_location("harbor_serve", ROOT / "site/serve.py")
serve = importlib.util.module_from_spec(SERVE_SPEC)
SERVE_SPEC.loader.exec_module(serve)


class Manifest(HTMLParser):
    """The built page's points of interest: their spots and every link inside them."""

    def __init__(self):
        super().__init__()
        self.spots, self.links, self.inside, self.text = [], [], False, {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li" and "data-spot" in attrs:
            self.spots.append(attrs["data-spot"])
            self.text[attrs["data-spot"]] = ""
            self.inside = True
        elif tag == "a" and self.inside:
            self.links.append(attrs)

    def handle_data(self, data):
        if self.inside and self.spots:
            self.text[self.spots[-1]] += data

    def handle_endtag(self, tag):
        if tag == "li":
            self.inside = False


def built(tmp_path, monkeypatch, readme, index=None):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text(readme)
    (root / "SETUP.md").write_text((ROOT / "SETUP.md").read_text())
    (root / "CHANGELOG.md").write_text((ROOT / "CHANGELOG.md").read_text())
    (root / "docs").mkdir()
    (root / "docs/features.md").write_text(
        (ROOT / "docs/features.md").read_text() if index is None else index
    )
    monkeypatch.setattr(build, "ROOT", root)
    manifest = Manifest()
    manifest.feed((build.build(tmp_path / "dist") / "index.html").read_text())
    return manifest


def test_mapped_features_and_docs_index_appear_once(tmp_path, monkeypatch, capsys):
    readme = (ROOT / "README.md").read_text()
    unmapped = "docs/brand-new-page.md"
    readme = readme.replace(
        "\n## More docs\n",
        f"\n## More docs\n- [Brand new]({unmapped})\n",
        1,
    )
    index = (ROOT / "docs/features.md").read_text()
    links = [link for _, link, _ in build.features(readme, index) if link in build.SCENE]
    manifest = built(tmp_path, monkeypatch, readme)

    hrefs = Counter(a["href"] for a in manifest.links)
    assert {link: hrefs[f"{build.REPO}/blob/main/{link}"] for link in links} == dict.fromkeys(
        links, 1
    )
    assert hrefs[f"{build.REPO}#features"] == 1
    assert hrefs[f"{build.REPO}/blob/main/{unmapped}"] == 1
    assert len(manifest.spots) == len(set(manifest.spots))
    assert all(a.get("target") == "_blank" for a in manifest.links)
    assert "docsboard" in manifest.spots
    assert unmapped in capsys.readouterr().err


def test_mapped_rows_get_their_own_spot_and_no_board(tmp_path, monkeypatch, capsys):
    readme = (ROOT / "README.md").read_text()
    index = (ROOT / "docs/features.md").read_text()
    mapped = [row for row in build.features(readme, index) if row[1] in build.SCENE]
    section = readme.split("\n## Features\n", 1)[1].split("\n## ", 1)[0]
    only = "\n".join(f"- [{title}]({link}): {desc}" for title, link, desc in mapped)
    readme = readme.replace(section, f"\n{only}\n", 1)
    more_docs = readme.split("\n## More docs\n", 1)[1].split("\n## ", 1)[0]
    readme = readme.replace(more_docs, "", 1)
    manifest = built(tmp_path, monkeypatch, readme, index="")

    assert "docsboard" not in manifest.spots
    assert {build.SCENE[link][0] for _, link, _ in mapped} <= set(manifest.spots)
    assert capsys.readouterr().err == ""


def test_every_scene_object_has_a_manifest_entry(tmp_path, monkeypatch):
    """harbor.js show() reads the entry of any object the player aims at."""
    manifest = built(tmp_path, monkeypatch, (ROOT / "README.md").read_text())
    scene = set(re.findall(r'\bspot: "(\w+)"', (ROOT / "site/public/harbor.js").read_text()))
    assert scene - set(manifest.spots) == set()


def test_long_descriptions_are_short_and_escape_html(tmp_path, monkeypatch):
    readme = (ROOT / "README.md").read_text()
    readme = readme.replace(
        "Discord, Slack, and",
        "<script>alert(1)</script> " + "long description " * 20,
    )
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text(readme)
    (root / "SETUP.md").write_text((ROOT / "SETUP.md").read_text())
    (root / "CHANGELOG.md").write_text((ROOT / "CHANGELOG.md").read_text())
    (root / "docs").mkdir()
    (root / "docs/features.md").write_text((ROOT / "docs/features.md").read_text())
    monkeypatch.setattr(build, "ROOT", root)
    page = (build.build(tmp_path / "dist") / "index.html").read_text()
    manifest = Manifest()
    manifest.feed(page)
    assert "<script>alert(1)</script>" not in page
    assert "<script>alert(1)</script>" in manifest.text["antenna"]
    assert len(manifest.text["antenna"]) <= len("Chat clients") + 52


class Head(HTMLParser):
    """The built page's meta properties and names, and its link rels, with their values."""

    def __init__(self):
        super().__init__()
        self.meta, self.links = {}, {}
        self.anchors, self.ids = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and "content" in attrs:
            self.meta[attrs.get("property") or attrs.get("name")] = attrs["content"]
        elif tag == "link":
            self.links[attrs["rel"]] = attrs["href"]
        elif tag == "a":
            self.anchors.append(attrs["href"])
        if "id" in attrs:
            self.ids.append(attrs["id"])


def png_size(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR", path
    return struct.unpack(">II", data[16:24])


def test_link_preview_tags_point_at_absolute_urls_and_real_images(tmp_path):
    dist = build.build(tmp_path / "dist")
    head = Head()
    head.feed((dist / "index.html").read_text())

    assert head.meta["og:title"] == "Crewship"
    assert head.meta["og:type"] == "website"
    assert head.meta["twitter:card"] == "summary_large_image"
    assert head.meta["og:url"] == "https://crewship.si/"
    assert head.meta["twitter:image"] == head.meta["og:image"]
    image = urlparse(head.meta["og:image"])
    assert (image.scheme, image.netloc) == ("https", "crewship.si")
    assert png_size(dist / image.path.lstrip("/")) == (1200, 630)
    assert (head.meta["og:image:width"], head.meta["og:image:height"]) == ("1200", "630")
    assert png_size(dist / head.links["apple-touch-icon"]) == (180, 180)
    assert (dist / head.links["icon"]).read_text().startswith("<svg ")


def test_pages_carry_json_ld(tmp_path):
    dist = build.build(tmp_path / "dist")

    def ld(name):
        page = (dist / name).read_text()
        return [
            json.loads(b)
            for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page)
        ]

    types = {n["@type"] for n in ld("index.html")[0]["@graph"]}
    assert types == {"WebSite", "SoftwareApplication"}
    faq = ld("about.html")[0]
    assert faq["@type"] == "FAQPage"
    page = (dist / "about.html").read_text()
    visible = re.findall(
        r"<h3>(.*?)</h3>\s*<p>(.*?)</p>", page.split("Short factual answers")[1], re.S
    )
    assert [(q["name"], q["acceptedAnswer"]["text"]) for q in faq["mainEntity"]] == visible
    assert 'href="/how"' in (dist / "about.html").read_text()


def test_preview_serves_published_urls_and_rejects_unknown_routes(tmp_path):
    dist = build.build(tmp_path / "dist")
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(serve.Handler, directory=dist)) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection(*server.server_address, timeout=5)
        try:
            for path, filename in [
                ("/", "index.html"),
                ("/how", "how.html"),
                ("/how?preview=1", "how.html"),
                ("/about", "about.html"),
                ("/about?preview=1", "about.html"),
                ("/docs", "docs.html"),
                ("/docs?preview=1", "docs.html"),
                ("/docs/setup", "docs/setup.html"),
                ("/docs/setup?preview=1", "docs/setup.html"),
                ("/harbor.css", "harbor.css"),
                ("/harbor.js", "harbor.js"),
                ("/robots.txt", "robots.txt"),
                ("/sitemap.xml", "sitemap.xml"),
            ]:
                connection.request("GET", path)
                response = connection.getresponse()
                body = response.read()
                assert response.status == 200, path
                assert response.getheader("Location") is None, path
                assert body == (dist / filename).read_bytes(), path
                if filename == "robots.txt":
                    assert body == (ROOT / "site/public" / filename).read_bytes()
                if filename == "sitemap.xml":
                    sitemap = ET.fromstring(body)
                    assert [
                        url.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc").text
                        for url in sitemap
                    ] == [
                        "https://crewship.si/",
                        "https://crewship.si/how",
                        "https://crewship.si/about",
                        "https://crewship.si/docs",
                        "https://crewship.si/docs/readme",
                        "https://crewship.si/docs/setup",
                        *[
                            f"https://crewship.si/docs/{p.stem}"
                            for p in sorted((ROOT / "docs").glob("*.md"))
                        ],
                    ]
                if filename == "robots.txt":
                    robots = RobotFileParser()
                    robots.parse(body.decode().splitlines())
                    assert robots.site_maps() == ["https://crewship.si/sitemap.xml"]
                    for agent in ("Googlebot", "OAI-SearchBot", "GPTBot", "ClaudeBot"):
                        for route in ("/", "/how", "/about", "/docs", "/docs/setup"):
                            assert robots.can_fetch(agent, route)
                if filename.endswith(".html"):
                    assert response.getheader("Content-Type").startswith("text/html")
                    head = Head()
                    head.feed(body.decode())
                    assert head.links["canonical"] == "https://crewship.si" + urlparse(path).path
                    assert head.meta["og:url"] == head.links["canonical"], path
            for method, path, status in [
                ("HEAD", "/how?preview=1", 200),
                ("HEAD", "/about?preview=1", 200),
                ("HEAD", "/docs?preview=1", 200),
                ("HEAD", "/docs/setup?preview=1", 200),
                ("GET", "/docs/missing", 404),
                ("GET", "/docs/missing/", 404),
                ("GET", "/missing", 404),
                ("GET", "/missing.js", 404),
                ("HEAD", "/missing", 404),
            ]:
                connection.request(method, path)
                response = connection.getresponse()
                response.read()
                assert response.status == status, (method, path)
            for path, location in [
                ("/index.html", "/"),
                ("/how.html", "/how"),
                ("/about/", "/about"),
                ("/docs/", "/docs"),
                ("/docs.html?preview=1", "/docs?preview=1"),
                ("/docs/index", "/docs"),
                ("/docs/index.html", "/docs"),
                ("/docs/setup/", "/docs/setup"),
                ("/docs/setup.html", "/docs/setup"),
                ("/docs/setup/index.html", "/docs/setup"),
            ]:
                connection.request("GET", path)
                response = connection.getresponse()
                response.read()
                assert response.status == 307, path
                assert response.getheader("Location") == location, path
        finally:
            connection.close()
            server.shutdown()
            thread.join()


def test_markdown_renders_repository_syntax_and_escapes_unsafe_html():
    markdown = r"""# Guide & reference

Read **bold** and *italic* with `a < b`, [setup](../SETUP.md#start),
[local](other.md?view=1#section), [source](../scripts/ship.py), and <https://example.com>.
![Screenshot](images/demo.png)
[![Build](https://example.com/build.svg)](https://example.com/build)

## Repeated `heading`
## Repeated `heading`

- Parent
  - Nested **item**

  Continuation.

3. Third
4. Fourth

   ```sh
   echo "<script> & untouched"
   ```

> Quoted **text**.
>
> Another paragraph.

| Name | Value |
| --- | --- |
| `one\|two` | [other](other.md#section) |

<picture>
<source media="(prefers-color-scheme: dark)" srcset="images/dark.svg">
<img src="images/demo.png" alt="A &amp; B" onerror="alert(1)">
</picture>

<script>alert(1)</script>
[unsafe](javascript:alert%281%29)
"""
    body = build.render_markdown(
        markdown, "docs/guide.md", {"SETUP.md": "/docs/setup", "docs/other.md": "/docs/other"}
    )
    assert '<h1 id="guide--reference">Guide &amp; reference</h1>' in body
    assert '<h2 id="repeated-heading">' in body
    assert '<h2 id="repeated-heading-1">' in body
    assert "<strong>bold</strong>" in body and "<em>italic</em>" in body
    assert "<code>a &lt; b</code>" in body
    assert '<a href="/docs/setup#start">setup</a>' in body
    assert '<a href="/docs/other?view=1#section">local</a>' in body
    assert 'href="https://github.com/i098/Crewship/blob/main/scripts/ship.py"' in body
    assert 'src="https://raw.githubusercontent.com/i098/Crewship/main/docs/images/demo.png"' in body
    assert '<a href="https://example.com/build"><img' in body
    assert '<source media="(prefers-color-scheme: dark)"' in body
    assert "<ul>\n<li><p>Parent</p>\n<ul>" in body
    assert '<ol start="3">' in body and "<p>Continuation.</p>" in body
    assert '<pre><code class="language-sh">echo &quot;&lt;script&gt; &amp; untouched&quot;' in body
    assert "<blockquote><p>Quoted <strong>text</strong>.</p>" in body
    assert "<th>Name</th>" in body and "<td><code>one|two</code></td>" in body
    assert "onerror=" not in body and "<script>" not in body and "javascript:" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_every_document_is_indexed_with_unique_metadata_and_working_links(tmp_path):
    dist = build.build(tmp_path / "dist")
    sources = [ROOT / "README.md", ROOT / "SETUP.md", *sorted((ROOT / "docs").glob("*.md"))]
    routes = {"/docs", *(f"/docs/{source.stem.lower()}" for source in sources)}
    assert set(build.doc_routes()) == {source.relative_to(ROOT).as_posix() for source in sources}
    pages, titles = {}, []
    for route in routes:
        page = (dist / f"{route.lstrip('/')}.html").read_text()
        head = Head()
        head.feed(page)
        pages[route] = head
        title = unescape(re.search(r"<title>(.*?)</title>", page)[1])
        titles.append(title)
        assert title.endswith(" - Crewship docs")
        assert head.links["canonical"] == f"https://crewship.si{route}"
        assert 0 < len(head.meta["description"]) <= 160
        assert head.meta["og:url"] == head.links["canonical"]
        assert (head.meta["og:title"], head.meta["og:description"]) == (title, head.meta["description"])
        assert {"/", "/about", "/docs"} <= set(head.anchors)
        assert head.links["stylesheet"] == "/harbor.css"
        assert len(head.ids) == len(set(head.ids)), route
        assert len(re.findall(r"<h1\b", page)) == 1, route
        structured = json.loads(
            re.search(r'<script type="application/ld\+json">(.*?)</script>', page)[1]
        )
        assert structured["@type"] == "BreadcrumbList"
        assert structured["itemListElement"][-1]["item"] == head.links["canonical"]
    assert len(titles) == len(set(titles))
    assert routes - {"/docs"} <= set(pages["/docs"].anchors)
    for route, head in pages.items():
        for link in head.anchors:
            parsed = urlparse(link)
            if parsed.scheme or parsed.netloc or (parsed.path and not parsed.path.startswith("/docs")):
                continue
            target = parsed.path or route
            assert target in pages, (route, link)
            if parsed.fragment:
                assert parsed.fragment in pages[target].ids, (route, link)
    for link in re.findall(r"https://crewship.si(/docs[\w/-]*)", (dist / "llms.txt").read_text()):
        assert link in pages
