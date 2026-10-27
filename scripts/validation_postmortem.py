#!/usr/bin/env python3
import argparse
from datetime import UTC, datetime
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / "docs/validation-postmortems.md"
FIELDS = ("run", "step", "root-cause", "fix", "prevention")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Append a failed validation run post-mortem.")
    for field in FIELDS:
        parser.add_argument(f"--{field}", required=True)
    args = parser.parse_args(argv)
    cells = []
    for field in FIELDS:
        value = " ".join(getattr(args, field.replace("-", "_")).split())
        if not value:
            parser.error(f"--{field} must not be empty")
        cells.append(value.replace("|", "&#124;"))
    row = "| " + " | ".join([datetime.now(UTC).date().isoformat(), *cells]) + " |\n"
    with LOG.open("a+b") as log:
        if log.tell():
            log.seek(-1, 2)
            if log.read(1) != b"\n":
                row = "\n" + row
        log.write(row.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
