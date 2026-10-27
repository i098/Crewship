import re
from pathlib import Path

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/repo-readme"
SECTIONS = ["Features", "Quick start", "How it works", "Repository layout", "License"]


def test_front_matter_names_the_skill_and_its_trigger():
    head = (SKILL / "SKILL.md").read_text().split("---")[1]
    assert "name: repo-readme" in head
    assert "like similar repos" in head


def test_skill_studies_peers_and_forbids_activity_badges():
    skill = (SKILL / "SKILL.md").read_text()
    assert "Find 3-5 popular OSS repositories" in skill
    assert all(item in skill for item in ("section order", "hero", "badges", "screenshot", "quick start length"))
    assert "Do not use Last commit or Updated badges." in skill
    assert len(skill.splitlines()) < 60


def test_template_has_no_activity_badges():
    text = (SKILL / "README.template.md").read_text()
    assert not re.search(r"Last commit|Updated", text, re.I)


def test_template_keeps_the_section_order_and_the_hero_parts():
    text = (SKILL / "README.template.md").read_text()
    heads = re.findall(r"^## (.+)$", text, re.M)
    assert [h for h in heads if h in SECTIONS] == SECTIONS
    assert text.index("<h1") < text.index("Sponsor") < text.index("<img src=") < text.index("## Features")
    assert text.count("for-the-badge") >= 5


def test_skill_links_only_files_that_exist():
    for name in re.findall(r"`((?:checklist|README\.template)\.md)`", (SKILL / "SKILL.md").read_text()):
        assert (SKILL / name).is_file()
