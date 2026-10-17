#!/usr/bin/env python3
"""Print the global native Treehouse pool root and the legacy home pool root."""

import os
import re
import sys
import tomllib
from pathlib import Path


def pool_roots():
    home = Path.home()
    config = home / ".config/treehouse/config.toml"
    root = os.environ.get("TREEHOUSE_ROOT", "")
    if not root:
        try:
            with config.open("rb") as stream:
                root = tomllib.load(stream).get("root", "")
        except FileNotFoundError:
            pass
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            print(f"treehouse-roots: cannot read native config: {error}", file=sys.stderr)
    roots = []
    if isinstance(root, str) and root:
        # Match Go os.ExpandEnv, including special names and malformed braces.
        expanded = re.sub(
            r"\$(?:\{([^}]*)\}|\{|([*#$@!?0-9-]|[A-Za-z_][A-Za-z0-9_]*))",
            lambda match: os.environ.get(match[1] or match[2] or "", ""), root,
        )
        if Path(expanded).is_absolute():
            roots.append(Path(expanded) / ".treehouse")
        else:
            print("treehouse-roots: relative native root needs a repository; skipped", file=sys.stderr)
    roots.append(home / ".treehouse")
    return dict.fromkeys(str(path.resolve()) for path in roots)


if __name__ == "__main__":
    print("\n".join(pool_roots()))
