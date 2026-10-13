#!/usr/bin/env python3
"""Render a Manim scene to mp4 or gif in one cache dir that is pruned after 1 day.

render.py scene.py SceneName [--gif] [-q l|m|h] [--send "caption"]
Prints the output path. --send runs `fm-imessage --image` (gif or still PNG; iMessage cannot take mp4).
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "crewship-manim"
MAX_AGE = 86400


def prune(cache=CACHE, now=None):
    now = time.time() if now is None else now
    for p in cache.glob("*"):
        if now - p.stat().st_mtime > MAX_AGE:
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def command(scene, name, quality, gif, media):
    base = ["manim"] if shutil.which("manim") else ["uv", "run", "--with", "manim", "manim"]
    # --format=gif also writes a gif; -s saves the last frame as PNG
    return base + [f"-q{quality}", "--media_dir", str(media), *(["--format=gif"] if gif else []), str(scene), name]


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("scene")
    a.add_argument("name")
    a.add_argument("--gif", action="store_true")
    a.add_argument("-q", default="m", choices="lmh")
    a.add_argument("--send")
    a = a.parse_args(argv)
    CACHE.mkdir(parents=True, exist_ok=True)
    prune()
    media = Path(os.environ.get("MANIM_MEDIA") or CACHE / f"run-{os.getpid()}")
    subprocess.run(command(a.scene, a.name, a.q, a.gif, media), check=True)
    ext = "gif" if a.gif else "mp4"
    out = max(media.rglob(f"{a.name}.{ext}"), key=lambda p: p.stat().st_mtime)
    print(out)
    if a.send:
        if not a.gif or not shutil.which("fm-imessage"):
            sys.exit("--send needs --gif and the fm-imessage command")
        subprocess.run(["fm-imessage", "--image", str(out), a.send], check=True)


if __name__ == "__main__":
    main()
