// Installed by Crewship from config/herdr-sidebar.ts; `./ship.sh launch`
// overwrites it. Feeds the Herdr Agents sidebar layout described in
// docs/herdr.md:
//   - terminal title: the bare session topic, without omp's "π" and spinner;
//     a spawned worker (FM_TASK_ID set) gets "└ " in front, and the Agents
//     layout shows that title as the worker's only name line.
//   - pane token `who`: the short name of the pane's own workspace (shortName
//     below); none for a worker, whose title names it.
//   - pane tokens `pr`, `issue`, `add`, `del`, `files`: the open pull request
//     for the current branch, the issue it works on, and the size of the work
//     in the checkout against the default branch, as "⎇ <pr>", "○ <issue>",
//     "+<added>", "−<deleted>", "✎ <files>". A worker shows its size as soon
//     as its diff is non-empty, before any commit or pull request.
//     The first part present carries the indent.
// Lookups run in the background on session start and turn end, the size also
// every 10 seconds, and never fail or slow a turn.
// @ts-nocheck

import { execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { lstat, open } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const BLANK = "\u2800";
const SOURCE = "crewship:sidebar";
const PR_REFRESH_MS = 5 * 60 * 1000;
const SIZE_REFRESH_MS = 10 * 1000;
const PARTS = ["pr", "issue", "add", "del", "files"];
const taskId = process.env.FM_TASK_ID || "";
const paneId = process.env.HERDR_PANE_ID;
const workspaceId = process.env.HERDR_WORKSPACE_ID;
const herdr = process.env.HERDR_BIN_PATH || "herdr";

const run = async (cmd: string, args: string[], cwd?: string): Promise<string> =>
  (await promisify(execFile)(cmd, args, { cwd, timeout: 15_000, encoding: "utf8", maxBuffer: 64 << 20 })).stdout;

export function titleFor(topic: string): string {
  return (taskId ? "└ " : "") + topic;
}

// Same mapping as maintenance/herdr-spaces.py short_name; "" means none.
export function shortName(label = ""): string {
  if (label.includes("-afk-daemon-")) return "☾ afk";
  if (label.startsWith("└")) return label.split(" · ")[0];
  if (label.startsWith("2ndmate-")) return label.slice(8).replace(/-mate-[^-]+$/, "");
  return label === "firstmate" ? label : "";
}

// Same-repository closing keywords GitHub recognises in a PR body.
const CLOSING = /\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b/i;
// How a task record names its issue: an issues/<n> link or "issue #<n>".
const RECORD_ISSUE = /issues\/(\d+)|\bissue\s+#?(\d+)/i;

export function closingIssue(body?: string | null): string {
  return (body || "").match(CLOSING)?.[1] || "";
}

export function recordIssue(texts: string[]): string {
  for (const text of texts) {
    const m = text.match(RECORD_ISSUE);
    if (m) return m[1] || m[2];
  }
  return "";
}

export function shortstat(out: string) {
  const n = (re: RegExp) => Number(out.match(re)?.[1] || 0);
  return { files: n(/(\d+) files? changed/), add: n(/(\d+) insertions?/), del: n(/(\d+) deletions?/) };
}

// Lines git counts in a new file: one for a symlink, none for a binary file (a
// NUL in its first 8000 bytes, so a binary file is never read past that).
async function newFileLines(file: string): Promise<number> {
  const st = await lstat(file);
  if (st.isSymbolicLink()) return 1;
  if (!st.isFile()) return 0;
  const fh = await open(file, "r");
  try {
    const buf = Buffer.alloc(8192);
    let lines = 0;
    let last = 10;
    for (let first = true; ; first = false) {
      const { bytesRead } = await fh.read(buf, 0, buf.length, null);
      if (!bytesRead) return lines + (last === 10 ? 0 : 1);
      const chunk = buf.subarray(0, bytesRead);
      if (first && chunk.subarray(0, 8000).includes(0)) return 0;
      for (let i = chunk.indexOf(10); i >= 0; i = chunk.indexOf(10, i + 1)) lines++;
      last = chunk[bytesRead - 1];
    }
  } finally {
    await fh.close();
  }
}

// Size of the work in the checkout: committed, staged and unstaged tracked
// changes since the merge base of `base` and HEAD, plus untracked files that
// are not ignored. `base` falls back to origin/main, then origin/master; with
// none of them there is no size ({}), and an empty diff is no size either.
async function diffStat(cwd: string, base: string) {
  const git = (...args: string[]) => run("git", ["-C", cwd, ...args]);
  let ref;
  for (const r of [base, "origin/main", "origin/master"]) {
    if (await git("rev-parse", "--verify", "--quiet", `${r}^{commit}`).then(() => true, () => false)) {
      ref = r;
      break;
    }
  }
  if (!ref) return {};
  const stat = shortstat(await git("-c", "diff.autorefreshindex=false", "diff", "--shortstat", "--merge-base", ref));
  // Counted the way git counts a new file: lines, one for a symlink, none for a binary file.
  // ponytail: reads every untracked text file each refresh; cap the size read if huge untracked files show up.
  for (const f of (await git("ls-files", "-z", "--others", "--exclude-standard", ":/")).split("\0")) {
    if (!f || f.endsWith("/")) continue; // "" ends the list; "dir/" is a nested repository
    stat.files++;
    stat.add += await newFileLines(path.resolve(cwd, f)).catch(() => 0);
  }
  return stat.files ? stat : {};
}

// Token values for the pull request line; "" clears a part.
export function prParts(v: { pr?; issue?; add?; del?; files? }, indent: number): Record<string, string> {
  const text = {
    pr: v.pr ? `⎇ ${v.pr}` : "",
    issue: v.issue ? `○ ${v.issue}` : "",
    add: v.add != null ? `+${v.add}` : "",
    del: v.del != null ? `−${v.del}` : "",
    files: v.files != null ? `✎ ${v.files}` : "",
  };
  let pad = BLANK.repeat(indent);
  return Object.fromEntries(
    PARTS.map((k) => {
      const value = text[k] ? pad + text[k] : "";
      if (value) pad = "";
      return [k, value];
    }),
  );
}

// "{owner}" (gh fills in the checkout's repository owner), then the owner of
// every GitHub remote: a fork's pull request has its head under the fork owner.
export function prOwners(remotes: string): string[] {
  return [...new Set(["{owner}", ...[...remotes.matchAll(/github\.com[:/]([^/\s]+)\//g)].map((m) => m[1])])];
}

async function lookupPr(cwd: string) {
  const branch = (await run("git", ["-C", cwd, "branch", "--show-current"])).trim();
  if (!branch) return undefined;
  for (const owner of prOwners(await run("git", ["-C", cwd, "remote", "-v"]))) {
    // REST, not GraphQL: gh fills {owner}/{repo} from the checkout's remote.
    const endpoint = `repos/{owner}/{repo}/pulls?state=open&head=${owner}:${encodeURIComponent(branch)}`;
    const pr = JSON.parse(await run("gh", ["api", "-X", "GET", endpoint], cwd))[0];
    if (pr) return pr;
  }
  return undefined;
}

// A worker's issue from its orchestrator home: the backlog entry, then the
// brief. The home is the ancestor of the pane's launch directory that holds
// state/<task>.meta.
async function lookupTaskIssue(): Promise<string> {
  let dir = JSON.parse(await run(herdr, ["pane", "get", paneId])).result?.pane?.cwd;
  for (; dir && dir !== path.dirname(dir); dir = path.dirname(dir)) {
    if (!existsSync(path.join(dir, "state", `${taskId}.meta`))) continue;
    const read = (f: string) => (existsSync(f) ? readFileSync(f, "utf8") : "");
    const entry = read(path.join(dir, "data", "backlog.md"))
      .split("\n")
      .filter((line) => line.startsWith("- [") && line.includes(` ${taskId} - `));
    return recordIssue([...entry, read(path.join(dir, "data", taskId, "brief.md"))]);
  }
  return "";
}

export default function (pi) {
  // Same guard as Herdr's own omp integration: only inside a Herdr pane, and
  // never from a nested omp started by a parent session's shell (OMPCODE=1).
  if (process.env.HERDR_ENV !== "1" || !paneId || process.env.OMPCODE === "1") return;

  let current; // latest interactive ctx
  let trailing;
  let titleTimer;
  let pr; // open pull request for the current branch, from the REST API
  let taskIssue = "";
  let stat = {};
  let reported; // the size last reported successfully
  let lookedUpAt = 0;
  let refreshing = false;
  let sizeTimer;

  // Runs from a raw timer too, where a throw would take the session down.
  function applyTitle() {
    try {
      const name = current.sessionManager?.getSessionName?.() || path.basename(current.cwd || process.cwd());
      current.ui.setTitle(titleFor(name.trim()));
    } catch {}
  }

  // omp resets the title (and drops an extension override) on rename, /new,
  // /resume and cwd changes, often after its own async work, so keep
  // re-applying; the terminal sink skips unchanged titles.
  function track(ctx) {
    if (ctx?.hasUI !== true) return;
    current = ctx;
    applyTitle();
    if (!titleTimer) {
      titleTimer = setInterval(applyTitle, 1000);
      titleTimer.unref?.();
    }
  }

  async function report() {
    const sent = JSON.stringify(stat);
    let who = "";
    if (!taskId) {
      const label = JSON.parse(await run(herdr, ["workspace", "get", workspaceId])).result?.workspace?.label;
      who = shortName(label) || label;
    }
    // Herdr already indents continuation rows two columns, so this lines the
    // PR line up under the name: after the "└ " for a worker.
    const parts = prParts(
      { pr: pr?.number, issue: taskIssue || closingIssue(pr?.body), ...(pr || taskId ? stat : {}) },
      taskId ? 2 : 0,
    );
    const args = ["pane", "report-metadata", paneId, "--source", SOURCE];
    for (const [k, v] of Object.entries({ who, ...parts })) args.push(...(v ? ["--token", `${k}=${v}`] : ["--clear-token", k]));
    await run(herdr, args);
    reported = sent;
  }

  // Display-only: a failed lookup keeps the previous value. Re-reporting on
  // every call also restores tokens a Herdr restart dropped. A lookup asked
  // for while one runs or inside the throttle window is put off to the
  // window's end, not dropped. `lookup` false (the size timer) skips the pull
  // request lookup and reports only a size not yet reported successfully.
  async function refresh(cwd?: string, lookup = true) {
    const wait = lookedUpAt + PR_REFRESH_MS - Date.now();
    if (lookup && cwd && (refreshing || wait > 0) && !trailing) {
      trailing = setTimeout(() => {
        trailing = undefined;
        void refresh(current.cwd);
      }, Math.max(wait, 1000));
      trailing.unref?.();
    }
    if (refreshing) return;
    refreshing = true;
    try {
      if (lookup && cwd && wait <= 0) {
        if (!lookedUpAt) await report().catch(() => {});
        lookedUpAt = Date.now();
        pr = await lookupPr(cwd).catch(() => pr);
        if (taskId) taskIssue = await lookupTaskIssue().catch(() => taskIssue);
      }
      // A worker's size shows as soon as its diff is non-empty, before any
      // commit or PR: against the PR base, else the remote's default branch.
      if (cwd && (pr || taskId)) {
        const base = pr ? `origin/${pr.base?.repo?.default_branch || pr.base?.ref}` : "origin/HEAD";
        stat = await diffStat(cwd, base).catch(() => stat);
      }
      if (lookup || JSON.stringify(stat) !== reported) await report();
    } catch {
    } finally {
      refreshing = false;
    }
  }

  pi.on("session_start", (_event, ctx) => {
    track(ctx);
    if (!current) return;
    void refresh(current.cwd);
    // A worker stays in one turn for most of its task: keep the size live.
    // refresh() skips a tick while the previous refresh still runs.
    if (!sizeTimer) {
      sizeTimer = setInterval(() => void refresh(current.cwd, false), SIZE_REFRESH_MS);
      sizeTimer.unref?.();
    }
  });
  pi.on("session_switch", (_event, ctx) => track(ctx));
  pi.on("agent_start", (_event, ctx) => track(ctx));
  // Subagent turns end here too; only the interactive session's cwd counts.
  pi.on("agent_end", () => {
    if (!current) return;
    applyTitle();
    void refresh(current.cwd);
  });
  // Tokens have no TTL, so a pane reused by another program must not keep them.
  pi.on("session_shutdown", () => {
    clearInterval(titleTimer);
    titleTimer = undefined;
    clearInterval(sizeTimer);
    sizeTimer = undefined;
    clearTimeout(trailing);
    const clear = ["who", ...PARTS].flatMap((k) => ["--clear-token", k]);
    if (current) void run(herdr, ["pane", "report-metadata", paneId, "--source", SOURCE, ...clear]).catch(() => {});
  });
}
