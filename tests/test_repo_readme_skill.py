import re
from pathlib import Path

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/repo-readme"
SECTIONS = ["Features", "Quick start", "How it works", "Repository layout", "License"]


def test_front_matter_names_the_skill_and_its_trigger():
    head = (SKILL / "SKILL.md").read_text().split("---")[1]
    assert "name: repo-readme" in head
    assert re.search(r"^description: Use when .*README", head, re.M)


def test_template_keeps_the_section_order_and_the_hero_parts():
    text = (SKILL / "README.template.md").read_text()
    heads = re.findall(r"^## (.+)$", text, re.M)
    assert [h for h in heads if h in SECTIONS] == SECTIONS
    assert text.index("<h1") < text.index("Sponsor") < text.index("<img src=") < text.index("## Features")
    assert text.count("for-the-badge") >= 6


def test_skill_links_only_files_that_exist():
    for name in re.findall(r"`((?:checklist|README\.template)\.md)`", (SKILL / "SKILL.md").read_text()):
        assert (SKILL / name).is_file()
