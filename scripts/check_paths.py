#!/usr/bin/env python3
"""Report existing and missing paths without following symlinks."""

import argparse
import json
import os


def classify_paths(paths):
    result = {"existing": [], "missing": []}
    for path in paths:
        try:
            os.lstat(path)
        except FileNotFoundError:
            result["missing"].append(path)
        else:
            result["existing"].append(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=json.loads, help="JSON array of paths")
    args = parser.parse_args()
    if not isinstance(args.paths, list) or not all(isinstance(path, str) for path in args.paths):
        parser.error("paths must be a JSON array of strings")
    try:
        result = classify_paths(args.paths)
    except OSError as error:
        parser.exit(1, f"check_paths: {error}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
