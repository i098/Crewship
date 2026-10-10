"""harbor/build.py fills the landing page's points of interest from the repository."""

import importlib.util
import re
import struct
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("harbor_build", ROOT / "harbor/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


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


def built(tmp_path, monkeypatch, readme):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text(readme)
    (root / "CHANGELOG.md").write_text((ROOT / "CHANGELOG.md").read_text())
    monkeypatch.setattr(build, "ROOT", root)
    manifest = Manifest()
    manifest.feed((build.build(tmp_path / "dist") / "index.html").read_text())
    return manifest


def test_mapped_features_and_docs_index_appear_once(tmp_path, monkeypatch, capsys):
    readme = (ROOT / "README.md").read_text()
    unmapped = "docs/brand-new-page.md"
    readme = readme.replace("\n## More docs:", f"\n## More docs: [Brand new]({unmapped})", 1)
    links = [link for _, link, _ in build.features(readme) if link in build.SCENE]
    extra_count = sum(link not in build.SCENE for _, link, _ in build.features(readme))
    manifest = built(tmp_path, monkeypatch, readme)

    hrefs = Counter(a["href"] for a in manifest.links)
    assert {link: hrefs[f"{build.REPO}/blob/main/{link}"] for link in links} == dict.fromkeys(
        links, 1
    )
    assert hrefs[f"{build.REPO}#features"] == 1
    assert hrefs[f"{build.REPO}/blob/main/{unmapped}"] == 0
    assert f"+ {extra_count - 3} more" in manifest.text["docsboard"]
    assert len(manifest.spots) == len(set(manifest.spots))
    assert all(a.get("target") == "_blank" for a in manifest.links)
    assert "docsboard" in manifest.spots
    assert unmapped in capsys.readouterr().err


def test_mapped_rows_get_their_own_spot_and_no_board(tmp_path, monkeypatch, capsys):
    readme = (ROOT / "README.md").read_text()
    mapped = [row for row in build.features(readme) if row[1] in build.SCENE]
    section = readme.split("<summary><b>Show all features</b></summary>", 1)[1].split("</details>", 1)[0]
    only = "\n".join(f"- [{title}]({link}): {desc}" for title, link, desc in mapped)
    readme = readme.replace(section, f"\n{only}\n", 1)
    more_docs = readme.split("\n## More docs:", 1)[1].split("\n## ", 1)[0]
    readme = readme.replace(more_docs, "", 1)
    manifest = built(tmp_path, monkeypatch, readme)

    assert "docsboard" not in manifest.spots
    assert {build.SCENE[link][0] for _, link, _ in mapped} <= set(manifest.spots)
    assert capsys.readouterr().err == ""


def test_long_descriptions_are_short_and_escape_html(tmp_path, monkeypatch):
    readme = (ROOT / "README.md").read_text()
    readme = readme.replace(
        "sign-in, model roles, fallbacks, and the advisor",
        "<script>alert(1)</script> " + "long description " * 20,
    )
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text(readme)
    (root / "CHANGELOG.md").write_text((ROOT / "CHANGELOG.md").read_text())
    monkeypatch.setattr(build, "ROOT", root)
    page = (build.build(tmp_path / "dist") / "index.html").read_text()
    manifest = Manifest()
    manifest.feed(page)
    assert "<script>alert(1)</script>" not in page
    assert "<script>alert(1)</script>" in manifest.text["mast"]
    assert len(manifest.text["mast"]) <= len("omp agents") + 52
    assert len(manifest.links) == len(manifest.spots)


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
    tagline = re.search(r"^\*\*(.+)\*\*$", (ROOT / "README.md").read_text(), re.M)[1]

    assert head.meta["og:title"] == "Crewship"
    assert head.meta["og:description"] == tagline
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
