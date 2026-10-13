#!/usr/bin/env python3
"""Render an OpenMontage Remotion props file to mp4 in one cache dir that is pruned after 1 day.

render.py PROPS [--seconds N] [--send "caption"]
PROPS is a props .json path or the name of a checked-in demo (code-to-screen, world-in-numbers, focusflow-pitch).
Prints the mp4 path. --send also sends a poster PNG with `fm-imessage --image` (iMessage takes no mp4).
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "crewship" / "videos"
HOME = Path(os.environ.get("OPENMONTAGE_DIR", Path.home() / ".local/share/openmontage"))
MAX_AGE = 86400
FPS = 30  # ponytail: the Explainer composition runs at 30 fps; read it from the props if that changes


def prune(cache=CACHE, now=None):
    now = time.time() if now is None else now
    for p in cache.glob("*"):
        if now - p.stat().st_mtime > MAX_AGE:
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def command(props, out, seconds=None):
    cmd = ["npx", "remotion", "render", "src/index.tsx", "Explainer", str(out), "--props", str(props), "--codec", "h264"]
    return cmd + ([f"--frames=0-{int(seconds * FPS) - 1}"] if seconds else [])


def main(argv=None):
    a = argparse.ArgumentParser()
    a.add_argument("props")
    a.add_argument("--seconds", type=float)
    a.add_argument("--send")
    a = a.parse_args(argv)
    composer = HOME / "remotion-composer"
    if not composer.is_dir():
        sys.exit(f"OpenMontage is not installed at {HOME}: see SKILL.md, Install")
    props = Path(a.props)
    if not props.suffix:
        props = composer / "public/demo-props" / f"{a.props}.json"
    CACHE.mkdir(parents=True, exist_ok=True)
    prune()
    out = CACHE / f"{props.stem}-{int(time.time())}.mp4"
    subprocess.run(command(props.resolve(), out, a.seconds), cwd=composer, check=True, stdout=sys.stderr)
    print(out)
    if a.send:
        if not shutil.which("fm-imessage"):
            sys.exit("--send needs the fm-imessage command")
        png = out.with_suffix(".png")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", str(png)], check=True)
        subprocess.run(["fm-imessage", "--image", str(png), a.send], check=True)


if __name__ == "__main__":
    main()
