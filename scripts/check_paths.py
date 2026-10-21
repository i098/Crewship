#!/usr/bin/env python3
"""Report path existence and optional directory types without following symlinks."""

import argparse
import json
import os
import stat


def classify_paths(paths, *, include_directories=False):
    result = {"existing": [], "missing": []}
    if include_directories:
        result["directories"] = []
    for path in paths:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            result["missing"].append(path)
        else:
            result["existing"].append(path)
            if include_directories and stat.S_ISDIR(info.st_mode):
                result["directories"].append(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=json.loads, help="JSON array of paths")
    parser.add_argument(
        "--directories", action="store_true", help="include real directory paths in the report"
    )
    args = parser.parse_args()
    if not isinstance(args.paths, list) or not all(isinstance(path, str) for path in args.paths):
        parser.error("paths must be a JSON array of strings")
    try:
        result = classify_paths(args.paths, include_directories=args.directories)
    except OSError as error:
        parser.exit(1, f"check_paths: {error}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
