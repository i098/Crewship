#!/usr/bin/env python3
"""Pre-push PR check: commit subjects, issue link, Review plan line, screenshots for UI changes.

scripts/check_pr.py BODY_FILE [--base origin/main] [--ui | --no-ui] [--title TITLE]
Run it before opening a PR. Run scripts/check_pr_body.py too; it checks the template sections.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

from check_pr_body import (
    COMMIT_REMEDY,
    changes_ui,
    check_issue_reference,
    check_screenshots,
    closing_keyword_errors,
    commit_messages,
    sections,
)

TYPES = "build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test"
SUBJECT = re.compile(rf"(?:{TYPES})(?:\([a-z0-9][a-z0-9._/-]*\))?!?: \S.*")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
PLAN = re.compile(r"\s{0,3}(?:[-*] )?\**Review plan\**:\**\s*\S", re.I)


def check_commits(subjects):
    errors = []
    for subject in subjects:
        if len(subject) > 100:
            errors.append(f"Commit subject is over 100 characters: {subject}")
        elif not SUBJECT.fullmatch(subject) or subject.endswith("."):
            errors.append(
                f"Commit subject is not '<type>(<scope>): <text>' with no final period: {subject}"
            )
    return errors


def prose(body):
    """Body lines outside code fences."""
    fence, lines = "", []
    for line in body.splitlines():
        marker = FENCE.match(line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = ""
        elif marker:
            fence = marker[1]
        else:
            lines.append(line)
    return lines


def check_body(body, ui):
    lines = prose(body)
    errors = check_issue_reference(body)
    if not any(PLAN.match(line) for line in lines):
        errors.append("Add a 'Review plan: <how a reviewer checks this>' line to the body.")
    if ui:
        errors.extend(check_screenshots(sections(body)))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("body_file", help="PR body file, or - for stdin")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--title", default="", help="pull request title to check")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ui", action="store_true", help="force the screenshot check")
    group.add_argument("--no-ui", action="store_true", help="skip the screenshot check")
    args = parser.parse_args()
    body = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text()
    try:
        messages = commit_messages(args.base)
        subjects = [message.split("\n", 1)[0] for message in messages]
        ui = args.ui or (not args.no_ui and changes_ui(args.base))
    except subprocess.CalledProcessError as error:
        print(error.stderr.strip() or f"git failed for base {args.base}", file=sys.stderr)
        return 2
    errors = (
        check_commits(subjects)
        + closing_keyword_errors(messages, remedy=COMMIT_REMEDY)
        + closing_keyword_errors([args.title], "Title")
        + check_body(body, ui)
    )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("PR is ready to open.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
