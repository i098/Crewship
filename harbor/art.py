"""Converts the harbor house's public-domain paintings into the glyph textures in public/harbor.js.

Run it from the repository root; it needs the network and Pillow, which the build does not:

    uv run --no-project --with pillow python harbor/art.py

Each work comes from Wikimedia Commons (CREDITS.md names the sources). The script scales it to
three texture sizes, then rewrites the ART block of harbor.js. Each texel becomes a glyph from
ART_GLYPHS in one of a few colours the room can draw.
The script groups pixels by colour and selects each group's drawable colour using both hue and glyph lightness.
Each texel then takes the glyph whose ink on the night background comes nearest the pixel's lightness.
"""

import io
import math
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

JS = Path(__file__).resolve().parent / "public" / "harbor.js"
# Each work: Commons file, texture size, its tone curve and how much it is saturated first, as
# glyphs show less colour than paint. The curve draws a pixel at Oklab lightness
# dark + (light - dark) * t ** power, where t runs from 0 to 1 across the work's own lightness.
# A texel is half as wide as it is tall, like a glyph cell. The print's curve keeps its blue wave
# clear of the paper sky; the moonlit paintings keep their dark grounds.
WORKS = {
    "wave": ("Tsunami_by_hokusai_19th_century.jpg", (120, 40), (0.25, 0.6, 2.5), 2.0),
    "palermo": (
        "Entrance_to_the_Port_of_Palermo_by_Moonlight,_1769.jpg",
        (114, 41),
        (0.12, 0.6, 1),
        1.4,
    ),
    "ship": (
        "Ivan_Aivazovsky_Segelschiff_auf_hoher_See_bei_Mondschein_1840er.jpg",
        (66, 42),
        (0.12, 0.6, 1),
        1.4,
    ),
    "fishermen": (
        "Joseph_Mallord_William_Turner_-_Fishermen_at_Sea_-_Google_Art_Project.jpg",
        (100, 37),
        (0.12, 0.6, 1),
        1.4,
    ),
}
COLOURS = 8  # colour groups per work
TINT = 1.0  # weight of hue against lightness when a colour group picks its drawable colour
# Ink share of each glyph in its cell, measured in DejaVu Sans Mono.
INK = {
    " ": 0,
    ".": 0.031,
    ":": 0.062,
    "-": 0.034,
    "=": 0.138,
    "+": 0.129,
    "*": 0.111,
    "#": 0.29,
    "%": 0.221,
    "@": 0.287,
}
# Texels are the characters from # to ~ without the backslash.
ALPHABET = "".join(chr(c) for c in range(35, 127) if c != 92)
# Materials a painting may use: not the slate default, the lamp glow or the highlight.
SKIP = {"", "l", "h"}
BACKGROUND, LAMP = "#060a14", "#ffd479"


def rgb(h):
    return [int(h[i : i + 2], 16) for i in (1, 3, 5)]


def mix(a, b, f):
    return [int(x * (1 - f) + y * f + 0.5) for x, y in zip(a, b)]


def linear(colour):
    return [((v / 255 + 0.055) / 1.055) ** 2.4 if v > 10 else v / 255 / 12.92 for v in colour]


def oklab(lin):
    lc = math.cbrt(0.4122214708 * lin[0] + 0.5363325363 * lin[1] + 0.0514459929 * lin[2])
    mc = math.cbrt(0.2119034982 * lin[0] + 0.6806995451 * lin[1] + 0.1073969566 * lin[2])
    sc = math.cbrt(0.0883024619 * lin[0] + 0.2817188376 * lin[1] + 0.6299787005 * lin[2])
    return (
        0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc,
        1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc,
        0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc,
    )


def tint(lab):
    """Hue and chroma relative to lightness, so dark colours keep their hue."""
    return lab[1] / max(lab[0], 0.15), lab[2] / max(lab[0], 0.15)


def drawable(source, glyphs):
    """(material, level, tint, lightness of each glyph) for each colour the room draws a texel in."""
    start = source.index("const BASE = {")
    block = source[start : source.index("};", start)]
    base = {a or b: c for a, b, c in re.findall(r'(?:"(\w*)"|(\w+)): "(#[0-9a-f]{6})"', block)}
    dark = linear(rgb(BACKGROUND))
    colours = []
    for material, colour in base.items():
        if material in SKIP:
            continue
        for level in range(8):
            if level < 7:
                shade = mix(rgb(BACKGROUND), rgb(colour), min(1, 0.12 + (level + 1) * 0.15))
            else:
                shade = mix(rgb(colour), [255, 255, 255], 0.25)
            # Room light warms every level above 1, except blue (b): see shadeRoom in harbor.js.
            if material != "b" and level > 1:
                shade = mix(shade, rgb(LAMP), 0.45)
            lin = linear(shade)
            ink = [oklab([d + INK[g] * (v - d) for v, d in zip(lin, dark)])[0] for g in glyphs]
            colours.append((material, level, tint(oklab(lin)), ink))
    return colours


def fetch(name):
    url = (
        f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(name)}?width=960"
    )
    headers = {"User-Agent": "Crewship harbor art (https://github.com/i098/Crewship)"}
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=60
    ) as response:
        return Image.open(io.BytesIO(response.read())).convert("RGB")


def convert(colours, glyphs, name, size, tone, saturation):
    """The work's palette string and its texture at full, half and quarter size."""
    image = ImageEnhance.Color(fetch(name)).enhance(saturation)
    scaled = [
        image.resize((math.ceil(size[0] / 2**k), math.ceil(size[1] / 2**k)), Image.Resampling.BOX)
        for k in range(3)
    ]
    groups = scaled[0].quantize(
        COLOURS, Image.Quantize.MEDIANCUT, kmeans=8, dither=Image.Dither.NONE
    )
    # The mode filter merges specks of colour: each colour change starts another text run when the page draws.
    indexed = [
        list(
            s.quantize(palette=groups, dither=Image.Dither.NONE)
            .filter(ImageFilter.ModeFilter(3))
            .tobytes()
        )
        for s in scaled
    ]
    labs = [[oklab(linear(c)) for c in zip(*[iter(s.tobytes())] * 3)] for s in scaled]
    order = sorted(lab[0] for lab in labs[0])
    low, high = order[len(order) // 50], order[-len(order) // 50]

    def lightness(lab):
        dark, light, power = tone
        return dark + (light - dark) * max(0, min(1, (lab[0] - low) / (high - low))) ** power

    pick = {}
    for group in sorted({g for level in indexed for g in level}):
        members = [
            lab for level, index in zip(labs, indexed) for lab, g in zip(level, index) if g == group
        ]
        sample = members[:: max(1, len(members) // 150)]

        def cost(colour):
            _, _, hue, ink = colour
            return sum(
                min((lightness(lab) - i) ** 2 for i in ink)
                + TINT * sum((a - b) ** 2 for a, b in zip(hue, tint(lab)))
                for lab in sample
            )

        pick[group] = min(range(len(colours)), key=lambda c: cost(colours[c]))
    used = sorted(set(pick.values()), key=lambda c: colours[c][:2])
    textures = []
    for level, index in zip(labs, indexed):
        texels = []
        for lab, group in zip(level, index):
            ink = colours[pick[group]][3]
            glyph = min(range(len(glyphs)), key=lambda g: (ink[g] - lightness(lab)) ** 2)
            texels.append(ALPHABET[used.index(pick[group]) * len(glyphs) + glyph])
        textures.append("".join(texels))
    return "".join(f"{colours[c][0]}{colours[c][1]}" for c in used), textures


def main():
    source = JS.read_text()
    glyphs = re.search(r'const ART_GLYPHS = "([^"]*)"', source)[1]
    colours = drawable(source, glyphs)
    lines = ["const ART = {"]
    for key, (name, size, tone, saturation) in WORKS.items():
        pal, textures = convert(colours, glyphs, name, size, tone, saturation)
        if len(pal) // 2 * len(glyphs) > len(ALPHABET):
            raise SystemExit(f"{key}: too many colours for the texel alphabet")
        lines.append(f'  {key}: ["{pal}", {size[0]}, {size[1]},')
        lines += [f'    "{texture}"{"]," if n == 2 else ","}' for n, texture in enumerate(textures)]
        print(key, f"{size[0]}x{size[1]}", pal)
    lines.append("};")
    start = source.index("const ART = {")
    end = source.index("\n};\n", start) + 3
    JS.write_text(source[:start] + "\n".join(lines) + source[end:])


if __name__ == "__main__":
    main()
