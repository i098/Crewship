---
name: manim
description: Use when an explanation of math, an algorithm, a data flow or a system gets clearer as an animated diagram, or when the operator asks for a Manim animation. Write a Manim scene and render it to mp4 or gif.
---

# Explain with a Manim animation

Use Manim (Community Edition, https://pypi.org/project/manim/) when a still picture cannot show change over time: a proof step, a transform, a graph that grows, a packet that moves between boxes. For a plain chart or table, do not animate.

## Install

Prefer Manim Community Edition (`manim` on PyPI). It has the stable API and the docs at https://docs.manim.community. The original 3b1b Manim (`manimgl` on PyPI, OpenGL, Grant Sanderson's own tool) has a different API: use it only when the operator asks for it.

System dependencies: `ffmpeg`, Cairo and Pango (`libcairo2-dev libpango1.0-dev` on Debian). LaTeX is only for `MathTex` and `Tex`; use `Text` when you can.

You do not need a permanent install. `render.py` runs `manim` when it is on the PATH. Otherwise it runs `uv run --with manim manim`.

## Scene template

```python
from manim import *

class Demo(Scene):
    def construct(self):
        a, b = Square(color=BLUE), Circle(color=GREEN)
        self.play(Create(a))
        self.play(Transform(a, b))
        self.play(Write(Text("square to circle").to_edge(DOWN)))
        self.wait()
```

Keep a scene under 15 s. Use one idea per scene. Write the file in a temp dir, not in the repository.

## Render

Run the script that sits next to this file:

`render.py /tmp/demo.py Demo` renders an mp4 at medium quality (720p, 30 fps).
`render.py /tmp/demo.py Demo --gif` renders a gif. Use `-q l` for a fast draft and `-q h` for 1080p.

It writes to one cache dir, `~/.cache/crewship-manim/` (`XDG_CACHE_HOME` moves it), prunes anything older than 1 day on each run, and prints the path of the output. Do not keep renders anywhere else.

## Send

iMessage takes images, not mp4. Run `render.py /tmp/demo.py Demo --gif --send "caption"`: it renders the gif and runs `fm-imessage --image`. It stops with a message when `fm-imessage` does not exist. In other chats, share the mp4 path.

## Checked before this skill

Existing community Manim skills are large API references or multi-agent pipelines that write renders into the project `media/` dir. None fits the temp-dir and 1-day-prune rule, so this skill is a small original.

## Install of this skill

Crewship installs this skill with every other public skill: `~/.omp/agent/skills/manim/` for omp and `~/.claude/skills/manim/` for Claude Code (see [Skills](../../../../docs/omp.md#skills)). To install it by hand, copy this folder to both paths.
