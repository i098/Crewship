#!/usr/bin/env python3
"""Report path existence and optional directory types or ownership without following symlinks."""

import argparse
import grp
import json
import os
import pwd
import stat


def classify_paths(paths, *, include_directories=False, ownership=None):
    result = {"existing": [], "missing": []}
    if include_directories:
        result["directories"] = []
    if ownership is not None:
        result["owned_directories"] = []
    for path in paths:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            result["missing"].append(path)
        else:
            result["existing"].append(path)
            if include_directories and stat.S_ISDIR(info.st_mode):
                result["directories"].append(path)
            if ownership is not None and stat.S_ISDIR(info.st_mode) and (info.st_uid, info.st_gid) == ownership:
                result["owned_directories"].append(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=json.loads, help="JSON array of paths")
    parser.add_argument(
        "--directories", action="store_true", help="include real directory paths in the report"
    )
    parser.add_argument(
        "--owned-by", nargs=2, metavar=("USER", "GROUP"),
        help="include real directories with this owner and group",
    )
    args = parser.parse_args()
    if not isinstance(args.paths, list) or not all(isinstance(path, str) for path in args.paths):
        parser.error("paths must be a JSON array of strings")
    try:
        ownership = (
            (pwd.getpwnam(args.owned_by[0]).pw_uid, grp.getgrnam(args.owned_by[1]).gr_gid)
            if args.owned_by else None
        )
        result = classify_paths(args.paths, include_directories=args.directories, ownership=ownership)
    except (KeyError, OSError) as error:
        parser.exit(1, f"check_paths: {error}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
