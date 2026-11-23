#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys
from html import unescape
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / ".github/PULL_REQUEST_TEMPLATE.md"
HEADING = re.compile(r"^##[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
CHECKBOX = re.compile(r"^ {0,3}[-*] \[([ xX])\] (.+)$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
LITERAL_HTML = re.compile(r"^ {0,3}<(pre|script|style|textarea)(?=[ \t>]|$)[^>]*>?", re.I)
BLOCK_HTML = re.compile(
    r"^ {0,3}</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|"
    r"col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|"
    r"form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|"
    r"menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|"
    r"tbody|td|tfoot|th|thead|title|tr|track|ul)(?=[ \t]|/?>|$)",
    re.I,
)
STANDALONE_HTML = re.compile(r"^ {0,3}</?[A-Za-z][\w-]*(?:[ \t]+[^<>]*)?\s*/?>[ \t]*$")
CODE_SPAN = r"(?<!`)(`+)(?!`)(.*?)\1(?!`)"
COMMENT_TOKEN = re.compile(CODE_SPAN + r"|<!--")
MARKUP = re.compile(CODE_SPAN + r"|</?[A-Za-z][\w-]*(?:\s+[^<>]*)?\s*/?>")
LINK_DEFINITION = re.compile(
    r"^ {0,3}\[(?:\\.|[^\[\]\\\n])+\]:[ \t]*(?:\n[ \t]*)?"
    r"(?:<[^<>\n]*>|[^\s<>]+)"
    r"""(?:[ \t]*(?:\n[ \t]*)?(?:"[^"]*"|'[^']*'|\([^)]*\)))?[ \t]*(?=\n|$)""",
    re.M,
)
UI_GLOBS = (
    "site/public/**/*.html",
    "site/public/**/*.css",
    "site/public/**/*.js",
    "site/build.py",
    "tools/*-tui/**/*.ts",
    "tools/fleet-health/**/*.ts",
    "tools/tui-theme/**/*.ts",
)
UI_EXCLUDES = ("site/public/google2a77445d3f9ccb0e.html", "tools/**/*.test.ts")
SCREENSHOT = re.compile(
    r" {0,3}!\[(Before|After)\]\(https://github\.com/user-attachments/assets/"
    r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\)[ \t]*"
)
NEW_VIEW = re.compile(r" {0,3}Before: none, new view[ \t]*")


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


def literal_html_lines(opening, line, lines):
    tag = opening[1].lower()
    end = re.compile(rf"</{tag}>", re.I)
    line = line[opening.end():]
    while True:
        closing = end.search(line)
        if tag in {"pre", "textarea"}:
            yield (line[:closing.start()] if closing else line), True
        if closing or (line := next(lines, None)) is None:
            return


def raw_html_lines(line, lines, comment):
    yield unescape(MARKUP.sub("", line)), True
    for inner in lines:
        if not inner.strip():
            break
        inner, comment = strip_comments(inner, comment)
        yield unescape(MARKUP.sub("", inner)), True
    return comment


def fenced_lines(fence, lines):
    end = re.compile(rf"^ {{0,3}}{fence[0]}{{{len(fence)},}}\s*$")
    for line in lines:
        if end.fullmatch(line):
            break
        yield line, True


def body_lines(markdown):
    lines = iter(markdown.splitlines())
    comment = False
    at_boundary = True
    for line in lines:
        if not comment and (opening := LITERAL_HTML.match(line)):
            yield from literal_html_lines(opening, line, lines)
        else:
            line, comment = strip_comments(line, comment)
            if BLOCK_HTML.match(line) or (at_boundary and STANDALONE_HTML.fullmatch(line)):
                comment = yield from raw_html_lines(line, lines, comment)
            elif marker := FENCE.match(line):
                yield from fenced_lines(marker[1], lines)
            else:
                yield line, False
                at_boundary = not line.strip() or bool(HEADING.fullmatch(line))
                continue
        at_boundary = True


def sections(markdown):
    result = [("", [])]
    for line, in_code in body_lines(markdown):
        heading = HEADING.fullmatch(line) if not in_code else None
        if heading:
            result.append((heading[1], []))
        else:
            result[-1][1].append((line, in_code))
    return result


def has_content(lines):
    if any(code and re.search(r"\w", line) for line, code in lines):
        return True
    text = LINK_DEFINITION.sub("", "\n".join(line if not code else "" for line, code in lines))
    if any(
        line.startswith(("    ", "\t")) and re.search(r"\w", line) for line in text.splitlines()
    ):
        return True
    if any(match[1] and re.search(r"\w", match[2]) for match in MARKUP.finditer(text)):
        return True
    return bool(re.search(r"\w", unescape(MARKUP.sub("", text))))


def check_screenshots(actual):
    matches = [lines for name, lines in actual if name == "Review evidence"]
    if len(matches) != 1:
        return ["Include exactly one ## Review evidence section."]
    images = {"Before": set(), "After": set()}
    new_view = False
    for line, code in matches[0]:
        if code:
            continue
        if image := SCREENSHOT.fullmatch(line):
            images[image[1]].add(image[2].lower())
        elif NEW_VIEW.fullmatch(line):
            new_view = True
    before, after = images["Before"], images["After"]
    if after and (new_view or before) and before.isdisjoint(after):
        return []
    return [
        "Embed distinct GitHub Before and After screenshots in ## Review evidence. "
        "For a new view, replace the Before screenshot with: Before: none, new view"
    ]


def git(*args):
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def changes_ui(base):
    paths = git(
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        f"{base}...HEAD",
        "--",
        *(f":(top,icase,glob){pattern}" for pattern in UI_GLOBS),
        *(f":(top,exclude,icase,glob){pattern}" for pattern in UI_EXCLUDES),
    )
    return bool(paths)


def check_body(body, template, *, ui=False):
    errors = []
    first = next((line for line in body.splitlines() if line.strip()), "")
    if not re.fullmatch(r" {0,3}Closes #[1-9][0-9]*[ \t]*", first):
        errors.append("Start the body with Closes # followed by a positive issue number.")

    actual = sections(body)
    for heading, template_lines in sections(template):
        if not heading or heading == "Review evidence":
            continue
        matches = [lines for name, lines in actual if name == heading]
        if len(matches) != 1:
            errors.append(f"Include exactly one ## {heading} section.")
            continue
        lines = matches[0]
        if not has_content(lines):
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
                reason = re.fullmatch(
                    r"Not applicable:(.*)", found[0][2][len(label):].strip(), flags=re.I
                )
                if not reason or not has_content([(reason[1].strip(), False)]):
                    errors.append(f"Check the completed item or add Not applicable: <reason>: {label}")
    if ui:
        errors.extend(check_screenshots(actual))
    return errors


def main():
    parser = argparse.ArgumentParser(description="Check a PR body against the repository template.")
    parser.add_argument("body_file", nargs="?", default="-", help="body file, or - for stdin")
    parser.add_argument("--base", help="detect UI changes against this Git revision")
    args = parser.parse_args()
    body = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text()
    try:
        ui = bool(args.base) and changes_ui(args.base)
    except subprocess.CalledProcessError as error:
        print(error.stderr.strip() or f"git failed for base {args.base}", file=sys.stderr)
        return 2
    errors = check_body(body, TEMPLATE.read_text(), ui=ui)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("PR body matches the repository template.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
