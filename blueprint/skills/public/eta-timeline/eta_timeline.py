#!/usr/bin/env python3
"""Render an ETA timeline PNG (840 px wide, dark) from JSON items with headless Chrome.

eta_timeline.py items.json --tz America/Los_Angeles [--now ISO] [--out eta.png] [--send [CAPTION]]
Without --out the PNG goes to a temp file; --send deletes it right after fm-imessage returns.
--send without --out first sends a timeline card (fm-imessage --card -); the PNG is the fallback.
items.json: [{"label": "...", "group": "...", "start": "ISO", "end": "ISO", "state": "planned|done|moved"}]
An ISO time without an offset is read in --tz. start == end draws a dot; done always draws a dot at its end.
"""

import argparse
import glob
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

COLORS = {"done": "#57ab5a", "moved": "#d29922", "planned": "#539bf5"}
STEPS = (15, 30, 60, 120, 180, 360, 720, 1440)  # minutes between ticks
W, LEFT = 760, 300


def parse(text, tz):
    t = datetime.fromisoformat(text)
    return t.replace(tzinfo=tz) if t.tzinfo is None else t.astimezone(tz)


def duration(m):
    h, r = divmod(m, 60)
    return f"{m} min" if m < 60 else f"{h} h {r} min" if r else f"{h} h"


def tick_label(t):
    return t.strftime("%-I:%M %p") if t.hour or t.minute else t.strftime("%a 12:00 AM")


def build_page(items, tz, now):
    """Return (html, height). items: dicts with datetime start/end."""
    times = [i[k] for i in items for k in ("start", "end")] + [now]
    step = next(
        (s for s in STEPS if (max(times) - min(times)).total_seconds() / 60 / s <= 5), STEPS[-1]
    )
    t0 = min(times).replace(second=0, microsecond=0)
    t0 -= timedelta(
        minutes=(t0.hour * 60 + t0.minute) % step
    )  # tick on a multiple of step from midnight
    span = max(step, -(-int((max(times) - t0).total_seconds() // 60) // step) * step)

    def x(t):
        return LEFT + (t - t0).total_seconds() / 60 / span * (W - LEFT)

    rows, y, last = [], 80, None
    for it in items:
        if it["group"] != last:
            rows.append(f'<div class="grp" style="top:{y}px">{html.escape(it["group"])}</div>')
            y, last = y + 34, it["group"]
        col = COLORS[it["state"]]
        rows.append(f'<div class="lbl" style="top:{y}px">{html.escape(it["label"])}</div>')
        if it["state"] == "done" or it["start"] == it["end"]:
            rows.append(
                f'<div class="dot" style="top:{y + 6}px;left:{x(it["end"]) - 8}px;background:{col}"></div>'
            )
        else:
            left, mins = x(it["start"]), round((it["end"] - it["start"]).total_seconds() / 60)
            rows.append(
                f'<div class="bar" style="top:{y + 2}px;left:{left}px;width:{x(it["end"]) - left}px;background:{col}">{duration(mins)}</div>'
            )
        y += 40
    ticks = "".join(
        f'<div class="tick" style="left:{x(t)}px">{tick_label(t)}</div><div class="vline" style="left:{x(t)}px;height:{y - 50}px"></div>'
        for t in (t0 + timedelta(minutes=m) for m in range(0, span + 1, step))
    )
    nowx = x(now)
    now_html = f'<div class="now" style="left:{nowx}px;height:{y - 40}px"></div><div class="nowl" style="left:{nowx - 14}px">now</div>'
    page = f"""<html><head><style>
body{{margin:0;background:#0d1117;color:#e6edf3;font:22px DejaVu Sans,sans-serif}}
.c{{position:relative;width:{W + 40}px;height:{y + 40}px;padding:24px}}
h1{{font-size:30px;margin:0;position:absolute;top:18px;left:24px}}
.grp{{position:absolute;left:24px;color:#8b949e;font-size:18px;letter-spacing:2px;text-transform:uppercase}}
.lbl{{position:absolute;left:24px;width:{LEFT - 40}px;font-size:19px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.bar{{position:absolute;height:28px;border-radius:14px;color:#0d1117;font-size:15px;font-weight:bold;line-height:28px;text-align:center;white-space:nowrap;overflow:visible;min-width:60px}} .dot{{position:absolute;width:16px;height:16px;border-radius:8px}}
.tick{{position:absolute;top:{y + 4}px;transform:translateX(-50%);color:#8b949e;font-size:17px}}
.vline{{position:absolute;top:60px;width:1px;background:#21262d}}
.leg{{position:absolute;top:24px;left:400px;font-size:15px;color:#8b949e}} .leg span{{display:inline-block;width:14px;height:14px;border-radius:7px;margin:0 6px 0 14px;vertical-align:-2px}}
.now{{position:absolute;top:56px;width:2px;background:#e5534b}} .nowl{{position:absolute;top:40px;color:#e5534b;font-size:15px}}
</style></head><body><div class="c"><h1>Timeline, your time</h1><div class="leg"><span style="background:#57ab5a"></span>done <span style="background:#539bf5"></span>planned <span style="background:#d29922"></span>moved <span style="background:#e5534b;width:4px;border-radius:0"></span>now</div>{ticks}{now_html}{"".join(rows)}</div></body></html>"""
    return page, y


def chrome():
    found = (
        os.environ.get("CHROME")
        or next(
            iter(
                sorted(
                    glob.glob(
                        os.path.expanduser("~/.omp/puppeteer/chrome/linux-*/chrome-linux64/chrome")
                    ),
                    reverse=True,
                )
            ),
            None,
        )
        or next(filter(None, map(shutil.which, ("google-chrome", "chromium", "chrome"))), None)
    )
    if not found:
        sys.exit("no Chrome found: set CHROME to a Chrome binary")
    return found


def render(items, tz, now, out):
    page, y = build_page(items, tz, now)
    with tempfile.TemporaryDirectory() as d:
        src = Path(d, "timeline.html")
        src.write_text(page)
        subprocess.run(
            [
                chrome(),
                "--headless=new",
                "--no-sandbox",
                "--hide-scrollbars",
                f"--screenshot={out}",
                f"--window-size=840,{max(y + 90, 630)}",
                src.as_uri(),
            ],
            capture_output=True,
            check=True,
        )


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("items", help="JSON file of items")
    p.add_argument(
        "--tz", required=True, help="IANA timezone of the operator, e.g. America/Los_Angeles"
    )
    p.add_argument("--now", help="ISO time for the now line (default: the current time)")
    p.add_argument("--out", help="keep the PNG here (default: a temp file, deleted after --send)")
    p.add_argument(
        "--send",
        nargs="?",
        const="",
        metavar="CAPTION",
        help="send a timeline card, else the PNG with fm-imessage --image",
    )
    a = p.parse_args()
    tz = ZoneInfo(a.tz)
    now = parse(a.now, tz) if a.now else datetime.now(tz)
    raw = json.loads(Path(a.items).read_text())
    items = []
    for r in raw:
        if r.get("state", "planned") not in COLORS:
            sys.exit(f"bad state {r.get('state')!r}: use planned, done or moved")
        items.append(
            {
                "label": r["label"],
                "group": r["group"],
                "state": r.get("state", "planned"),
                "start": parse(r["start"], tz),
                "end": parse(r["end"], tz),
            }
        )
    if not items:
        sys.exit("no items")
    if a.send is not None and not a.out and len(items) <= 50 and shutil.which("fm-imessage"):
        hm = "%-I:%M %p"
        card = {
            "kind": "timeline",
            "key": "eta",
            "title": (a.send or "ETA")[:120],
            "subtitle": f"Times in {a.tz}"[:200],
            "items": [
                {
                    "when": i["end"].strftime(hm)
                    if i["start"] == i["end"]
                    else f"{i['start'].strftime(hm)} – {i['end'].strftime(hm)}",
                    "text": (
                        f"{i['group']}: {i['label']}"
                        + ("" if i["state"] == "planned" else f" ({i['state']})")
                    )[:200],
                }
                for i in items
            ],
        }
        sent = subprocess.run(["fm-imessage", "--card", "-"], input=json.dumps(card), text=True)
        if sent.returncode == 0:
            return
    out = a.out or tempfile.mkstemp(suffix=".png", prefix="eta-timeline-")[1]
    render(items, tz, now, out)
    if a.send is None:
        print(out)
        return
    try:
        if not shutil.which("fm-imessage"):
            sys.exit("fm-imessage not found: send the PNG another way")
        subprocess.run(["fm-imessage", "--image", out, *([a.send] if a.send else [])], check=True)
    finally:
        if not a.out:
            os.unlink(out)


if __name__ == "__main__":
    main()
