#!/usr/bin/env python3
"""Rewrite tests/shard_durations.json from a pytest JUnit file.

    uv run pytest -n auto tests --junitxml=junit.xml
    python scripts/refresh_shard_durations.py junit.xml
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path(__file__).parents[1] / "tests" / "shard_durations.json"


def nodeid(case):
    module = case.get("classname", "").split(".")
    # JUnit gives dotted module[.Class]; the module path is the leading run of lowercase file parts.
    parts = []
    for i, part in enumerate(module):
        parts.append(part)
        if (Path(*parts).with_suffix(".py")).exists():
            rest = module[i + 1 :]
            return "/".join(parts) + ".py::" + "::".join(rest + [case.get("name")])
    raise SystemExit(f"cannot map {case.get('classname')} to a test file")


def main(junit):
    seconds = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        key = nodeid(case)
        seconds[key] = round(seconds.get(key, 0) + float(case.get("time", 0)), 3)
    OUT.write_text(json.dumps(dict(sorted(seconds.items())), indent=0) + "\n")
    print(f"{len(seconds)} tests, {sum(seconds.values()):.0f} s -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
