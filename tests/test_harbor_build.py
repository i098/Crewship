"""site/build.py fills the landing page's points of interest from the repository."""

import importlib.util
import re
import struct
import xml.etree.ElementTree as ET
from collections import Counter
from functools import partial
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

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and "content" in attrs:
            self.meta[attrs.get("property") or attrs.get("name")] = attrs["content"]
        elif tag == "link":
            self.links[attrs["rel"]] = attrs["href"]


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


def test_preview_serves_published_urls_and_rejects_unknown_routes(tmp_path):
    dist = build.build(tmp_path / "dist")
    with ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(serve.Handler, directory=dist)
    ) as server:
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
                if filename in ("robots.txt", "sitemap.xml"):
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
                    ]
                if filename == "robots.txt":
                    robots = RobotFileParser()
                    robots.parse(body.decode().splitlines())
                    assert robots.site_maps() == ["https://crewship.si/sitemap.xml"]
                    for agent in ("Googlebot", "OAI-SearchBot", "GPTBot", "ClaudeBot", "PerplexityBot"):
                        for route in ("/", "/how", "/about"):
                            assert robots.can_fetch(agent, route), (agent, route)
                if filename.endswith(".html"):
                    assert response.getheader("Content-Type").startswith("text/html")
                    head = Head()
                    head.feed(body.decode())
                    assert head.links["canonical"] == "https://crewship.si" + urlparse(path).path
            for method, path, status in [
                ("HEAD", "/how?preview=1", 200),
                ("HEAD", "/about?preview=1", 200),
                ("GET", "/missing", 404),
                ("GET", "/missing.js", 404),
                ("HEAD", "/missing", 404),
            ]:
                connection.request(method, path)
                response = connection.getresponse()
                response.read()
                assert response.status == status, (method, path)
        finally:
            connection.close()
            server.shutdown()
            thread.join()
