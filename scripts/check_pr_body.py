#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / ".github/PULL_REQUEST_TEMPLATE.md"
HEADING = re.compile(r"^##[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
CHECKBOX = re.compile(r"^ {0,3}[-*] \[([ xX])\] (.+)$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
CODE_SPAN = r"(?<!`)(`+)(?!`)(.*?)\1(?!`)"
COMMENT_TOKEN = re.compile(CODE_SPAN + r"|<!--")
MARKUP = re.compile(CODE_SPAN + r"|</?[A-Za-z][\w-]*(?:\s+[^<>]*)?\s*/?>")


def strip_comments(line, comment):
    output = []
    while line:
        if comment:
            _, closed, line = line.partition("-->")
            if not closed:
                break
            comment = False
            continue
        token = COMMENT_TOKEN.search(line)
        if not token:
            output.append(line)
            break
        output.append(line[:token.start()])
        if token[1]:
            output.append(token[0])
        else:
            comment = True
        line = line[token.end():]
    return "".join(output), comment


def sections(markdown):
    result = [("", [])]
    fence = ""
    comment = False
    for line in markdown.splitlines():
        if not fence:
            line, comment = strip_comments(line, comment)
        marker = FENCE.match(line)
        in_code = bool(fence or marker)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                if not marker[2].strip():
                    fence = ""
        elif marker:
            fence = marker[1]
        heading = HEADING.fullmatch(line) if not in_code else None
        if heading:
            result.append((heading[1], []))
        elif not marker:
            result[-1][1].append((line, in_code))
    return result


def check_body(body, template):
    errors = []
    first = body.lstrip().splitlines()[0] if body.strip() else ""
    if not re.fullmatch(r"Closes #[1-9][0-9]*[ \t]*", first):
        errors.append("Start the body with Closes # followed by a positive issue number.")

    actual = sections(body)
    for heading, template_lines in sections(template):
        if not heading:
            continue
        matches = [lines for name, lines in actual if name == heading]
        if len(matches) != 1:
            errors.append(f"Include exactly one ## {heading} section.")
            continue
        lines = matches[0]
        text = (
            line if code else MARKUP.sub(lambda match: match[0] if match[1] else "", line)
            for line, code in lines
        )
        if not any(re.search(r"\w", line) for line in text):
            errors.append(f"Fill the ## {heading} section.")
        items = [CHECKBOX.fullmatch(line) for line, code in lines if not code]
        items = [item for item in items if item]
        for line, code in template_lines:
            required = CHECKBOX.fullmatch(line) if not code else None
            if not required:
                continue
            label = required[2]
            found = [item for item in items if item[2] == label or item[2].startswith(label + " ")]
            if len(found) != 1:
                errors.append(f"Keep exactly one checklist item: {label}")
            elif found[0][1] == " ":
                reason = found[0][2][len(label):].strip()
                if not re.fullmatch(r"Not applicable:\s*.*\w.*", reason, flags=re.I):
                    errors.append(f"Check the completed item or add Not applicable: <reason>: {label}")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Check a PR body against the repository template.")
    parser.add_argument("body_file", nargs="?", default="-", help="body file, or - for stdin")
    args = parser.parse_args()
    body = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text()
    errors = check_body(body, TEMPLATE.read_text())
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("PR body matches the repository template.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
