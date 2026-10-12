#!/usr/bin/env python3
"""Copy a host's Herdr sidebar layout into THIS machine's Herdr config.

Sidebar layouts are client-side in Herdr: they come from the config of the
machine you view from, even over `herdr --remote`. Run on the viewing machine:

    ssh <host> cat .local/bin/herdr-sidebar-to-client.py | python3 - <host> [config-path]

It reads the host's ~/.config/herdr/config.toml over ssh, then in the local config:
  - sets sidebar_width / sidebar_max_width inside the existing [ui] table (adds [ui] if missing),
  - replaces or adds [ui.sidebar.agents] and [ui.sidebar.spaces],
  - sets sidebar_bg inside [theme.custom] (adds the table if missing).
Everything else in the local file is left as is. A timestamped backup is written first.
"""

import os
import re
import shutil
import subprocess
import sys
import time


def table(text, name):
    """Body of [name] up to the next table header, or None."""
    m = re.search(rf"(?ms)^\[{re.escape(name)}\]\n(.*?)(?=^\[|\Z)", text)
    return m.group(1) if m else None


def key(body, k):
    m = re.search(rf"(?m)^{k}\s*=\s*(.+)$", body or "")
    return m.group(1).strip() if m else None


def set_key(text, tname, k, v):
    body = table(text, tname)
    if body is None:
        return text.rstrip("\n") + f"\n\n[{tname}]\n{k} = {v}\n"
    new = re.sub(rf"(?m)^{k}\s*=.*$", f"{k} = {v}", body) if key(body, k) else f"{k} = {v}\n" + body
    return re.sub(
        rf"(?ms)^\[{re.escape(tname)}\]\n.*?(?=^\[|\Z)",
        lambda _: f"[{tname}]\n{new}",
        text,
        count=1,
    )


def set_table(text, tname, body):
    if table(text, tname) is None:
        return text.rstrip("\n") + f"\n\n[{tname}]\n{body.rstrip()}\n"
    return re.sub(
        rf"(?ms)^\[{re.escape(tname)}\]\n.*?(?=^\[|\Z)",
        lambda _: f"[{tname}]\n{body.rstrip()}\n\n",
        text,
        count=1,
    )


def merge(local, remote):
    """The local config text with the remote config's sidebar layout copied in."""
    ui = table(remote, "ui")
    agents, spaces = table(remote, "ui.sidebar.agents"), table(remote, "ui.sidebar.spaces")
    bg = key(table(remote, "theme.custom"), "sidebar_bg")
    if not (ui and agents and spaces):
        sys.exit("host config has no sidebar layout; nothing copied")
    t = local
    for k in ("sidebar_width", "sidebar_max_width"):
        v = key(ui, k)
        if v:
            t = set_key(t, "ui", k, v)
    t = set_table(t, "ui.sidebar.agents", agents)
    t = set_table(t, "ui.sidebar.spaces", spaces)
    if bg:
        t = set_key(t, "theme.custom", "sidebar_bg", bg)
    return t.strip("\n") + "\n"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: herdr-sidebar-to-client.py <host> [config-path]")
    local = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else "~/.config/herdr/config.toml")
    ssh = subprocess.run(
        ["ssh", sys.argv[1], "cat .config/herdr/config.toml"],
        capture_output=True,
        text=True,
    )
    if ssh.returncode:
        sys.exit(ssh.stderr.strip() or f"ssh {sys.argv[1]} failed with exit code {ssh.returncode}")
    merged = merge(open(local).read() if os.path.exists(local) else "", ssh.stdout)
    if os.path.exists(local):
        shutil.copy2(local, f"{local}.bak-sidebar-{time.strftime('%Y%m%dT%H%M%S')}")
    os.makedirs(os.path.dirname(local) or ".", exist_ok=True)
    open(local, "w").write(merged)
    print(f"sidebar layout written to {local}")
