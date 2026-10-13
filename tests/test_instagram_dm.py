import importlib.util
import sys
from pathlib import Path

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/instagram-dm"
# The public-skill privacy scan reads every file in the skill folder: leave no .pyc there.
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("instagram_dm", SKILL / "instagram_dm.py")
ig = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ig)


def test_every_post_link_becomes_a_reel_url_once():
    text = (
        "see https://www.instagram.com/p/AbC_1-x/?igsh=z https://instagram.com/reel/AbC_1-x/ "
        'and "https://www.instagram.com/someone/reels/Q9/" https://www.instagram.com/tv/T1/'
    )
    assert ig.reel_urls(text) == [f"https://www.instagram.com/reel/{c}/" for c in ("AbC_1-x", "Q9", "T1")]


def test_other_links_are_ignored():
    assert ig.reel_urls("https://www.instagram.com/someone/ https://example.com/p/abc") == []
