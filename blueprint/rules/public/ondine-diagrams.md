---
name: ondine-diagrams
alwaysApply: true
description: Use Ondine as the default diagram renderer.
---

Use [Ondine](https://ondine.sh) for diagrams by default.
Keep its compatible Mermaid syntax in `.mmd` files and run `ondine diagram.mmd` to produce SVG.
Link the SVG in Markdown so GitHub shows the diagram.
For Markdown fences, run `ondine README.md --svg` to keep the output local.
Use `ondine README.md` only for public diagrams: its image URLs send the source to `ondine.sh`.
Run `ondine README.md --restore` to edit the source, then render it again.
