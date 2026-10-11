#!/usr/bin/env python3
"""Build one self-contained HTML page that recreates how GitHub shows a pull
request, an issue or a single comment, so it can be checked before posting.

  pr_preview.py pr      --repo O/R --base main --head [FORK:]BRANCH --title T --body-file F
  pr_preview.py issue   --repo O/R --title T --body-file F
  pr_preview.py comment --repo O/R --body-file F

The body comes from GitHub's own Markdown API (gh api markdown, mode gfm, the
target repository as context), so @mentions, #refs and task lists resolve as
they will on the real page. The styling is the vendored Primer Markdown CSS.
Commits and files come from local git (default) or from the compare API
(--compare, for a branch that is already pushed). Prints the HTML path.
"""

import argparse
import html
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
e = html.escape


def run(*cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"{' '.join(cmd[:3])} failed: {r.stderr.strip()}")
    return r.stdout


def gh_json(path, *flags):
    return json.loads(run("gh", "api", path, *flags))


def render_markdown(path, repo):
    return run("gh", "api", "-X", "POST", "markdown", "-f", "mode=gfm", "-f", f"context={repo}",
               "-F", f"text=@{path}")


def when(iso):
    """Relative time like GitHub: "5 days ago", or the date after a month."""
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    s = (datetime.now(timezone.utc) - t).total_seconds()
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= size:
            n = int(s // size)
            return f"on {t:%b} {t.day}, {t.year}" if unit == "day" and n >= 30 else \
                f"{n} {unit}{'s' * (n != 1)} ago"
    return "now"


PAGE_CSS = """
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:#fff;color:#1f2328;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:24px 32px 64px}
.title{font-size:32px;font-weight:400;line-height:1.25;margin:0 0 8px;overflow-wrap:anywhere}
.num{color:#59636e;font-weight:300}
.meta{display:flex;flex-wrap:wrap;align-items:center;gap:8px;color:#59636e;margin-bottom:16px}
.who{color:#59636e;text-decoration:underline;font-weight:600}
.state{display:inline-flex;align-items:center;gap:4px;background:#1f883d;color:#fff;font-weight:600;padding:5px 12px;border-radius:2em}
.ref{background:#ddf4ff;color:#0969da;border-radius:6px;padding:2px 6px;font:12px ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace}
.tabs{display:flex;align-items:flex-end;border-bottom:1px solid #d1d9e0;margin-bottom:20px}
.tabs label{display:inline-flex;align-items:center;gap:8px;padding:0 16px;height:40px;cursor:pointer;color:#1f2328;border:1px solid transparent;border-bottom:0;border-radius:6px 6px 0 0;margin-bottom:-1px}
.pill{background:#818b981f;border-radius:2em;padding:0 6px;font-size:12px;font-weight:500;line-height:18px}
.stat{margin-left:auto;padding-bottom:8px;font-size:12px;display:flex;gap:4px;align-items:center}
.ga{color:#1a7f37}.gd{color:#d1242f}
.sq{display:inline-flex;gap:1px}.sq i{width:8px;height:8px;background:#d1d9e0}.sq i.g{background:#1f883d}.sq i.r{background:#cf222e}
.panes>section{display:none}
#t-conv:checked~.panes #p-conv,#t-commits:checked~.panes #p-commits,#t-files:checked~.panes #p-files{display:block}
#t-conv:checked~.panes #p-conv{display:grid}
#t-conv:checked~.tabs label[for=t-conv],#t-commits:checked~.tabs label[for=t-commits],#t-files:checked~.tabs label[for=t-files]{border-color:#d1d9e0;background:#fff}
.grid{grid-template-columns:minmax(0,1fr) 320px;gap:24px;align-items:start}
.single{max-width:872px}
.rule{border:0;border-top:1px solid #d1d9e0;margin:16px 0 24px}
.tl{display:flex;gap:16px;align-items:flex-start}
.av{border-radius:50%;background:#d1d9e0;flex:none}
.box{flex:1;min-width:0;border:1px solid #d1d9e0;border-radius:6px;position:relative;background:#fff}
.box::before{content:"";position:absolute;top:11px;left:-8px;border:8px solid transparent;border-left:0;border-right-color:#d1d9e0}
.box::after{content:"";position:absolute;top:12px;left:-6px;border:7px solid transparent;border-left:0;border-right-color:#f6f8fa}
.bh{display:flex;align-items:center;gap:4px;padding:8px 16px;background:#f6f8fa;border-bottom:1px solid #d1d9e0;border-radius:6px 6px 0 0;color:#59636e;min-height:37px}
.bh b{color:#59636e;font-weight:600}
.label{margin-left:auto;border:1px solid #d1d9e0;border-radius:2em;padding:0 7px;font-size:12px;line-height:18px;color:#59636e}
.dots{color:#59636e;letter-spacing:1px;margin-left:8px}
.bb{padding:16px;font-size:14px;background:#fff;border-radius:0 0 6px 6px;overflow-wrap:anywhere}
.bb .user-mention{font-weight:600;color:#1f2328}
.bb .highlight{position:relative}
.bb .highlight::after{content:"";position:absolute;top:8px;right:8px;width:28px;height:28px;border:1px solid #d1d9e0;border-radius:6px;background:#f6f8fa url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='%2359636e' stroke-width='1.5'%3E%3Crect x='5.5' y='5.5' width='8' height='8' rx='1.5'/%3E%3Cpath d='M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2'/%3E%3C/svg%3E") center/16px no-repeat}
.side h3{font-size:12px;font-weight:600;color:#59636e;margin:0 0 8px}
.side p{margin:0;font-size:12px;color:#59636e}
.side>div{padding:16px 0;border-bottom:1px solid #d1d9e0}.side>div:first-child{padding-top:0}
.muted{color:#59636e}
.summary{margin:0 0 16px}
.file{border:1px solid #d1d9e0;border-radius:6px;margin-bottom:16px;overflow:hidden}
.fh{display:flex;align-items:center;gap:8px;padding:8px 12px;background:#f6f8fa;border-bottom:1px solid #d1d9e0;color:#59636e}
.fn{font:12px ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;color:#1f2328;overflow-wrap:anywhere}
.cnt{font-size:12px;font-weight:600}
.note{padding:16px;text-align:center;color:#59636e}
.diff{width:100%;border-collapse:collapse;font:12px/20px ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;tab-size:8}
.diff td{padding:0 10px;white-space:pre-wrap;word-break:break-all;vertical-align:top}
.diff td.n{width:50px;min-width:50px;text-align:right;color:#59636e;user-select:none;white-space:nowrap}
.diff td.m{width:18px;padding:0 0 0 4px;color:#59636e;user-select:none}
.diff .hunk td{background:#ddf4ff;color:#59636e}
.diff .add td{background:#dafbe1}.diff .add td.n{background:#aceebb}
.diff .del td{background:#ffebe9}.diff .del td.n{background:#ffcecb}
.diff .nonl td{color:#59636e}
.commits{border-left:2px solid #d1d9e0;margin-left:7px;padding-left:24px}
.cday{margin-left:-35px;color:#59636e;display:flex;gap:8px;align-items:center;margin-bottom:8px;background:#fff}
.crow{display:flex;justify-content:space-between;align-items:center;gap:16px;border:1px solid #d1d9e0;border-radius:6px;padding:8px 16px;margin-bottom:8px}
.ct{font-size:16px;line-height:24px}
.cm{display:flex;gap:6px;align-items:center;font-size:12px;color:#59636e}
.cm .av{border-radius:50%}
.ini{width:20px;height:20px;border-radius:50%;background:#d1d9e0;display:inline-grid;place-items:center;font-size:11px;font-weight:600}
.sha{font:12px ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;color:#59636e}
"""

# ---- commits and files ------------------------------------------------------

def split_patch(text):
    """Split a git diff into [{name, old, status, patch}]; patch starts at the first @@."""
    files = []
    for chunk in re.split(r"^diff --git ", text, flags=re.M)[1:]:
        head, _, rest = chunk.partition("\n@@")
        m = re.match(r"a/(.*) b/(.*)", head.split("\n")[0])
        status = ("added" if "\nnew file mode" in head else "removed" if "\ndeleted file mode" in head
                  else "renamed" if "\nrename from" in head else "modified")
        files.append({"name": m.group(2), "old": m.group(1), "status": status,
                      "binary": "\nBinary files" in head or "\nGIT binary patch" in head,
                      "patch": "@@" + rest if rest else ""})
    return files


def git_changes(cwd, base_ref, head_ref):
    sep = "\x1f"
    log = run("git", "log", "--reverse", f"--format=%H{sep}%an{sep}%cI{sep}%s{sep}%b\x1e",
              f"{base_ref}..{head_ref}", cwd=cwd)
    commits = []
    for rec in filter(str.strip, log.split("\x1e")):
        sha, author, date, subject, body = rec.strip("\n").split(sep, 4)
        commits.append({"sha": sha, "author": author, "login": None, "date": date,
                        "subject": subject, "body": body.strip()})
    files = split_patch(run("git", "diff", "--no-color", "-M", f"{base_ref}...{head_ref}", cwd=cwd))
    return commits, files


def api_changes(repo, base, head):
    commits, files = {}, {}
    for page in range(1, 11):  # the compare API serves 300 files at most
        d = gh_json(f"repos/{repo}/compare/{base}...{head}", "-X", "GET",
                    "-f", "per_page=100", "-f", f"page={page}")
        new = 0
        for c in d["commits"]:
            new += c["sha"] not in commits
            msg = c["commit"]["message"].partition("\n\n")
            commits[c["sha"]] = {"sha": c["sha"], "author": c["commit"]["author"]["name"],
                                 "login": (c.get("author") or {}).get("login"),
                                 "date": c["commit"]["committer"]["date"], "subject": msg[0],
                                 "body": msg[2].strip()}
        for f in d["files"]:
            new += f["filename"] not in files
            files[f["filename"]] = {"name": f["filename"], "old": f.get("previous_filename", f["filename"]),
                                    "status": f["status"], "binary": "patch" not in f,
                                    "patch": f.get("patch", "")}
        if not new or (len(d["commits"]) < 100 and len(d["files"]) < 100):
            break
    return list(commits.values()), list(files.values())


# ---- HTML -------------------------------------------------------------------

def icon(name, size=16):
    paths = {
        "pr": '<circle cx="4" cy="3.5" r="1.7"/><circle cx="4" cy="12.5" r="1.7"/><circle cx="12" cy="12.5" r="1.7"/>'
              '<path d="M4 5.2v5.6M12 10.8V6a2 2 0 0 0-2-2H8.5M10 2.2 8.3 4 10 5.8"/>',
        "commit": '<circle cx="8" cy="8" r="3"/><path d="M1 8h4M11 8h4"/>',
        "conv": '<path d="M2 3h9a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H6l-3 2.5V10H2a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/>',
        "files": '<path d="M3 1.5h7l3 3v10H3zM5.5 8.5h5M8 6v5"/>',
        "issue": '<circle cx="8" cy="8" r="6.2"/><circle cx="8" cy="8" r="1.2" fill="currentColor"/>',
        "chev": '<path d="M4 6l4 4 4-4"/>',
    }
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
            f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths[name]}</svg>')


def avatar(login, size=40):
    src = f"https://github.com/{login}.png?size={size * 2}"
    return f'<img class="av" width="{size}" height="{size}" src="{e(src)}" alt="">'


def squares(add, dele):
    """Five squares like GitHub: one per change up to five, else proportional (floor)."""
    total = add + dele
    g, r = (add, dele) if total <= 5 else (5 * add // total, 5 * dele // total)
    return "".join(f'<i class="{c}"></i>' for c in ["g"] * g + ["r"] * r + ["n"] * (5 - g - r))


def comment_box(login, body_html, label="Author", verb="commented", at="now"):
    return (f'<div class="tl">{avatar(login)}<div class="box"><div class="bh"><b>{e(login)}</b> '
            f'<span class="muted">{verb} {e(at)}</span><span class="label">{label}</span>'
            f'<span class="dots">···</span></div>'
            f'<div class="markdown-body bb">{body_html}</div></div></div>')


SIDEBAR = {
    "pr": [("Reviewers", "No reviews"), ("Assignees", "No one assigned"), ("Labels", "None yet"),
           ("Projects", "None yet"), ("Milestone", "No milestone"),
           ("Development", "Successfully merging this pull request may close these issues.<br>None yet")],
    "issue": [("Assignees", "No one assigned"), ("Labels", "None yet"), ("Projects", "None yet"),
              ("Milestone", "No milestone"), ("Development", "No branches or pull requests")],
}


def sidebar(kind):
    return '<aside class="side">' + "".join(
        f"<div><h3>{k}</h3><p>{v}</p></div>" for k, v in SIDEBAR[kind]) + "</aside>"


def diff_table(f, limit):
    if f["binary"]:
        return '<div class="note">Binary file not shown.</div>'
    if not f["patch"]:
        return '<div class="note">File renamed without changes.</div>' if f["status"] == "renamed" \
            else '<div class="note">No textual changes.</div>'
    rows, old, new, lines = [], 0, 0, f["patch"].split("\n")
    for n, line in enumerate(lines):
        if n >= limit:
            rows.append(f'<tr class="hunk"><td colspan="4">{len(lines) - n} more lines not shown '
                        "(raise --max-diff-lines)</td></tr>")
            break
        if line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line)
            old, new = int(m.group(1)), int(m.group(2))
            rows.append(f'<tr class="hunk"><td class="n"></td><td class="n"></td><td colspan="2">{e(line)}</td></tr>')
        elif line.startswith("\\"):
            rows.append(f'<tr class="nonl"><td class="n"></td><td class="n"></td><td></td><td>{e(line)}</td></tr>')
        elif line.startswith("+"):
            rows.append(f'<tr class="add"><td class="n"></td><td class="n">{new}</td><td class="m">+</td><td>{e(line[1:])}</td></tr>')
            new += 1
        elif line.startswith("-"):
            rows.append(f'<tr class="del"><td class="n">{old}</td><td class="n"></td><td class="m">-</td><td>{e(line[1:])}</td></tr>')
            old += 1
        elif line:
            rows.append(f'<tr><td class="n">{old}</td><td class="n">{new}</td><td class="m"></td><td>{e(line[1:])}</td></tr>')
            old += 1
            new += 1
    return f'<table class="diff">{"".join(rows)}</table>'


def count(patch):
    lines = patch.split("\n") if patch else []
    return (sum(x.startswith("+") for x in lines), sum(x.startswith("-") for x in lines))


def files_pane(files, limit):
    stats = [count(f["patch"]) for f in files]
    a, d = sum(s[0] for s in stats), sum(s[1] for s in stats)
    out = [f'<p class="muted summary">Showing {len(files)} changed file{"s" * (len(files) != 1)} with '
           f'<b class="ga">{a} addition{"s" * (a != 1)}</b> and <b class="gd">{d} deletion{"s" * (d != 1)}</b>.</p>']
    for f, (fa, fd) in zip(files, stats):
        name = e(f["name"]) if f["status"] != "renamed" else f'{e(f["old"])} → {e(f["name"])}'
        out.append(f'<div class="file"><div class="fh">{icon("chev")}<span class="cnt">{fa + fd}</span>'
                   f'<span class="sq">{squares(fa, fd)}</span><span class="fn">{name}</span></div>'
                   f'{diff_table(f, limit)}</div>')
    return "".join(out), a, d


def commits_pane(commits):
    out, day = [], None
    for c in commits:
        t = datetime.fromisoformat(c["date"].replace("Z", "+00:00"))
        if (t.year, t.month, t.day) != day:
            day = (t.year, t.month, t.day)
            out.append(f'<div class="cday">{icon("commit")} Commits on {t:%b} {t.day}, {t.year}</div>')
        who = avatar(c["login"], 20) if c["login"] else f'<span class="ini">{e(c["author"][:1].upper())}</span>'
        out.append(f'<div class="crow"><div><div class="ct">{e(c["subject"])}</div>'
                   f'<div class="cm">{who}<span>{e(c["login"] or c["author"])} committed {e(when(c["date"]))}</span></div></div>'
                   f'<code class="sha">{c["sha"][:7]}</code></div>')
    return f'<div class="commits">{"".join(out)}</div>'


def page_head(title, number, state_html, text):
    num = f' <span class="num">#{e(str(number))}</span>' if number else ""
    return f'<h1 class="title">{e(title)}{num}</h1><div class="meta">{state_html}<span>{text}</span></div>'


def build_pr(a):
    base_ref = a.base_ref or f"origin/{a.base}"
    head_ref = a.head_ref or "HEAD"
    commits, files = (api_changes(a.repo, a.base, a.head) if a.compare
                      else git_changes(a.git, base_ref, head_ref))
    fork = ":" in a.head
    owner = a.repo.split("/")[0]
    base_label = f"{owner}:{a.base}" if fork else a.base
    n = len(commits)
    badge = f'<span class="state open">{icon("pr")} Open</span>'
    text = (f' <b class="who">{e(a.author)}</b> wants to merge {n} commit{"s" * (n != 1)} into '
            f'<code class="ref">{e(base_label)}</code> from <code class="ref">{e(a.head)}</code>')
    body = comment_box(a.author, render_markdown(a.body_file, a.repo), at=a.when)
    fpane, add, dele = files_pane(files, a.max_diff_lines)
    tabs = [("conv", "conv", "Conversation", ""), ("commits", "commit", "Commits", n),
            ("files", "files", "Files changed", len(files))]
    inputs = "".join(f'<input type="radio" name="tab" id="t-{k}" hidden{" checked" if k == a.tab else ""}>'
                     for k, *_ in tabs)
    nav = "".join(f'<label for="t-{k}">{icon(i)} {t}' + (f' <span class="pill">{c}</span>' if c != "" else "")
                  + "</label>" for k, i, t, c in tabs)
    stat = f'<span class="stat"><b class="ga">+{add}</b> <b class="gd">−{dele}</b> <span class="sq">{squares(add, dele)}</span></span>'
    panes = (f'<section id="p-conv" class="grid"><div>{body}</div>{sidebar("pr")}</section>'
             f'<section id="p-commits">{commits_pane(commits)}</section>'
             f'<section id="p-files">{fpane}</section>')
    return (page_head(a.title, a.number, badge, text) + inputs
            + f'<nav class="tabs">{nav}{stat}</nav><div class="panes">{panes}</div>'), a.title


def build_issue(a):
    badge = f'<span class="state open">{icon("issue")} Open</span>'
    text = f' <b class="who">{e(a.author)}</b> opened this issue {e(a.when)}'
    body = comment_box(a.author, render_markdown(a.body_file, a.repo), at=a.when)
    return (page_head(a.title, a.number, badge, text) + '<hr class="rule">'
            f'<section class="grid"><div>{body}</div>{sidebar("issue")}</section>'), a.title


def build_comment(a):
    body = comment_box(a.author, render_markdown(a.body_file, a.repo), label="Member", at=a.when)
    return f'<section class="single">{body}</section>', "Comment preview"


def document(inner, title):
    css = (HERE / "github-markdown-light.css").read_text()
    return (f'<!doctype html><html lang="en" data-theme="light"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title><style>{css}</style><style>{PAGE_CSS}</style></head>'
            f'<body><div class="wrap">{inner}</div></body></html>')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", required=True, help="target repository, OWNER/REPO")
    common.add_argument("--body-file", required=True, help="Markdown file with the body or comment text")
    common.add_argument("--author", help="login shown as author (default: the gh login)")
    common.add_argument("--when", default="now", help='age text, for example "3 days ago"')
    common.add_argument("--out", default=".lavish/pr-preview.html")
    sub = p.add_subparsers(dest="kind", required=True)
    for kind in ("pr", "issue"):
        s = sub.add_parser(kind, parents=[common])
        s.add_argument("--title", required=True)
        s.add_argument("--number", help="show #N after the title")
    s = sub.choices["pr"]
    s.add_argument("--base", required=True, help="base branch")
    s.add_argument("--head", required=True, help="BRANCH, or FORK:BRANCH for a fork")
    s.add_argument("--base-ref", help="git ref for the base (default origin/<base>)")
    s.add_argument("--head-ref", help="git ref for the head (default HEAD)")
    s.add_argument("--git", default=".", help="local clone to read commits and diff from")
    s.add_argument("--compare", action="store_true", help="read commits and diff from the compare API")
    s.add_argument("--tab", default="conv", choices=["conv", "commits", "files"], help="tab shown first")
    s.add_argument("--max-diff-lines", type=int, default=600, help="diff lines shown per file")
    sub.add_parser("comment", parents=[common])
    a = p.parse_args()
    a.author = a.author or run("gh", "api", "user", "--jq", ".login").strip()
    inner, title = {"pr": build_pr, "issue": build_issue, "comment": build_comment}[a.kind](a)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document(inner, title))
    print(out)


if __name__ == "__main__":
    main()
