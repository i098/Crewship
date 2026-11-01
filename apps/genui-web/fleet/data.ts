// Read-only view of the owner's fleet: second mates, workers, open asks, backlog and open PRs.
// Every source is a file or script the fleet already uses; nothing here writes.
import { closeSync, fstatSync, openSync, readdirSync, readFileSync, readSync, statSync } from "node:fs";
import { parseStatusLine, type StatusLine } from "@crewship/genui-agent-kit";

export type Task = { id: string; home: string; mate?: string; meta: Record<string, string>; lines: StatusLine[]; busy: string };
/** `at` is the epoch second on the status line that raised the ask, so the newest ask sorts first across files. */
export type Ask = { home: string; task: string; key: string; verb: string; note: string; at: number };
export type BacklogRow = { id: string; state: string; kind: string; title: string; held: boolean };
export type Checks = { ok: number; bad: number; pending: number };
export type Pr = {
  url: string; repo: string; number: number; title: string; draft: boolean; updated: string;
  ref?: string; checks?: Checks; owner?: { home: string; task: string };
};
export type Fleet = {
  main: string; login: string; mates: Task[]; workers: Task[]; asks: Ask[];
  backlog: Record<string, BacklogRow[]>; prs: Pr[]; prsAt: number; asksAt: number; error?: { at: number; msg: string };
};

const TAIL = 48 * 1024; // status files reach megabytes; the last lines are enough
const SLUG = /^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$/;
export const isSlug = (s: unknown): s is string => typeof s === "string" && SLUG.test(s);

/** The fleet scripts read FM_* overrides first; a child gets only FM_HOME, so it addresses that home. */
export function homeEnv(home: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) if (v !== undefined && !k.startsWith("FM_")) env[k] = v;
  return { ...env, FM_HOME: home };
}

export async function run(cmd: string[], home: string, timeout = 120_000) {
  const p = Bun.spawn(cmd, { cwd: home, env: homeEnv(home), stdout: "pipe", stderr: "pipe", stdin: "ignore", timeout });
  const [out, err, code] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text(), p.exited]);
  return { out, err, code };
}

export function readMeta(file: string): Record<string, string> {
  const meta: Record<string, string> = {};
  for (const l of readFileSync(file, "utf8").split("\n")) {
    const i = l.indexOf("=");
    if (i > 0) meta[l.slice(0, i)] = l.slice(i + 1);
  }
  return meta;
}

/** The last lines of a file; a line cut by the window is dropped. */
function tail(file: string): string[] {
  let fd: number | undefined;
  try {
    fd = openSync(file, "r");
    const size = fstatSync(fd).size, n = Math.min(size, TAIL), buf = Buffer.alloc(n);
    readSync(fd, buf, 0, n, size - n);
    const lines = buf.toString("utf8").split("\n");
    return size > TAIL ? lines.slice(1) : lines;
  } catch {
    return [];
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}

function tasksIn(home: string, mate?: string): Task[] {
  const dir = `${home}/state`;
  let names: string[] = [];
  try {
    names = readdirSync(dir).filter((n) => n.endsWith(".meta")).map((n) => n.slice(0, -5));
  } catch {
    return [];
  }
  return names.filter(isSlug).map((id) => ({
    id, home, mate, meta: readMeta(`${dir}/${id}.meta`),
    lines: tail(`${dir}/${id}.status`).flatMap((l) => parseStatusLine(l) ?? []).slice(-30),
    busy: / state=(\w+)/.exec(tail(`${dir}/${id}.busy-state`).join("\n"))?.[1] ?? "",
  }));
}

/** Second mates live in the main home; each one's workers live in its own home. */
export function readCrew(main: string): { mates: Task[]; workers: Task[] } {
  const top = tasksIn(main);
  const mates = top.filter((t) => t.meta.kind === "secondmate");
  const workers = top.filter((t) => t.meta.kind !== "secondmate");
  for (const m of mates) if (m.meta.home && m.meta.home !== main) workers.push(...tasksIn(m.meta.home, m.id));
  return { mates, workers };
}

/** Open keyed decisions in one status file, by the fleet's own fold (fm-classify-lib.sh). */
export async function openAsks(home: string, task: string): Promise<Ask[]> {
  const { out, code } = await run(["bash", "-c", '. "$1/bin/fm-classify-lib.sh" && status_own_open_decisions "$2"', "fold", home, `${home}/state/${task}.status`], home);
  if (code !== 0) return [];
  const text = await Bun.file(`${home}/state/${task}.status`)
    .text()
    .catch(() => "");
  return out.split("\n").flatMap((l) => {
    const [key, verb, ...note] = l.split("\t");
    return key && verb ? [{ home, task, key, verb, note: note.join("\t"), at: raisedAt(text, key) }] : [];
  });
}

const MAX_AGE_S = Number(process.env.GENUI_ASK_MAX_AGE_H ?? 48) * 3600;
/** An ask raised within the last two days (GENUI_ASK_MAX_AGE_H); one with no stamp is never live. */
export const isLive = (a: Pick<Ask, "at">, now = Date.now() / 1000) => a.at > 0 && now - a.at <= MAX_AGE_S;

/** The at= stamp of the last status line carrying `[key=<key>]`. */
export function raisedAt(text: string, key: string): number {
  let at = 0;
  for (const l of text.split("\n")) if (l.includes(`[key=${key}]`)) at = Number(/\[at=(\d+)\]/.exec(l)?.[1] ?? at);
  return at;
}

/** One TOON row: comma separated, double-quoted cells may hold commas. */
export function toonRow(row: string): string[] {
  const out: string[] = [];
  let cell = "", quoted = false;
  for (let i = 0; i < row.length; i++) {
    const ch = row[i];
    if (quoted) {
      if (ch === "\\" && i + 1 < row.length) cell += row[++i] === "n" ? "\n" : row[i];
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") (out.push(cell), (cell = ""));
    else cell += ch;
  }
  out.push(cell);
  return out;
}

/** `fm-tasks-axi.sh list` output: a `tasks[N]{fields}:` header, then one indented row per task. */
export function parseBacklog(text: string): BacklogRow[] {
  const lines = text.split("\n");
  const h = lines.findIndex((l) => /^tasks\[\d+\]\{/.test(l));
  if (h < 0) return [];
  const fields = lines[h].slice(lines[h].indexOf("{") + 1, lines[h].indexOf("}")).split(",");
  const rows: BacklogRow[] = [];
  for (const l of lines.slice(h + 1)) {
    if (!l.startsWith("  ")) break;
    const c = Object.fromEntries(toonRow(l.trim()).map((v, i) => [fields[i], v]));
    rows.push({ id: c.id ?? "", state: c.state ?? "", kind: c.kind ?? "", title: (c.title ?? "").split("\n")[0], held: c.held === "yes" });
  }
  return rows;
}

export async function readBacklog(home: string): Promise<BacklogRow[]> {
  const { out } = await run([`${home}/bin/fm-tasks-axi.sh`, "list", "--fields", "held"], home);
  return parseBacklog(out);
}

/** Counts a head commit's check runs (latest run per name) and commit statuses. */
export function countChecks(runs: { name: string; id: number; status: string; conclusion: string | null }[], statuses: { state: string }[]): Checks {
  const latest = new Map<string, (typeof runs)[number]>();
  for (const r of runs) if ((latest.get(r.name)?.id ?? -1) < r.id) latest.set(r.name, r);
  const c: Checks = { ok: 0, bad: 0, pending: 0 };
  for (const r of latest.values()) {
    if (r.status !== "completed") c.pending++;
    else if (["success", "neutral", "skipped"].includes(r.conclusion ?? "")) c.ok++;
    else c.bad++;
  }
  for (const s of statuses) s.state === "success" ? c.ok++ : s.state === "pending" ? c.pending++ : c.bad++;
  return c;
}

export const green = (c?: Checks) => !!c && c.ok > 0 && c.bad === 0 && c.pending === 0;

/** Keeps a live Fleet: local files every few seconds, folds on change, backlog and PRs slow-paced. */
export class FleetSource {
  fleet: Fleet;
  private folds = new Map<string, { sig: string; asks: Ask[] }>();
  private listeners = new Set<() => void>();

  constructor(main: string, private opts = { localMs: 5_000, backlogMs: 120_000, prMs: 600_000, ghPaceMs: 800 }) {
    this.fleet = { main, login: "", mates: [], workers: [], asks: [], backlog: {}, prs: [], prsAt: 0, asksAt: 0 };
  }

  onChange(f: () => void) {
    this.listeners.add(f);
  }

  private changed() {
    for (const f of this.listeners) f();
  }

  task(home: string, id: string): Task | undefined {
    return [...this.fleet.mates, ...this.fleet.workers].find((t) => t.home === home && t.id === id);
  }

  homes(): string[] {
    return [this.fleet.main, ...new Set(this.fleet.mates.map((m) => m.meta.home).filter((h) => h && h !== this.fleet.main))];
  }

  start() {
    void this.loop(this.opts.localMs, () => this.refreshLocal());
    void this.loop(this.opts.backlogMs, () => this.refreshBacklog());
    void this.loop(this.opts.prMs, () => this.refreshPrs());
  }

  private async loop(ms: number, f: () => Promise<void>) {
    for (;;) {
      try {
        await f();
      } catch (e) {
        this.fleet.error = { at: Math.floor(Date.now() / 1000), msg: String(e) };
        this.changed();
      }
      await Bun.sleep(ms);
    }
  }

  async refreshLocal() {
    const { mates, workers } = readCrew(this.fleet.main);
    const crew = JSON.stringify([mates, workers]);
    if (crew !== JSON.stringify([this.fleet.mates, this.fleet.workers])) {
      Object.assign(this.fleet, { mates, workers });
      this.indexOwners();
      this.changed();
    }
    // The fold reads whole status files (seconds each), so it runs only for a file that changed.
    const found: Ask[][] = [];
    for (const t of [...mates, ...workers]) {
      const file = `${t.home}/state/${t.id}.status`;
      let sig = "";
      try {
        const s = statSync(file);
        sig = `${s.size}:${s.mtimeMs}`;
      } catch {
        continue;
      }
      const k = `${t.home}\0${t.id}`;
      let f = this.folds.get(k);
      if (f?.sig !== sig) this.folds.set(k, (f = { sig, asks: await openAsks(t.home, t.id) }));
      found.push(f.asks);
    }
    // newest ask first, so a cluster's few visible ask cards are the asks raised last.
    // Only live asks: the fold keeps an ask open until a resolved line lands, so a days-old one (a pool freeze since lifted) is stale.
    const asks = found
      .flat()
      .filter((a) => isLive(a))
      .sort((a, b) => b.at - a.at);
    const first = !this.fleet.asksAt;
    this.fleet.asksAt = Date.now();
    if (first || JSON.stringify(asks) !== JSON.stringify(this.fleet.asks)) {
      this.fleet.asks = asks;
      this.changed();
    }
  }

  async refreshBacklog() {
    const backlog: Record<string, BacklogRow[]> = {};
    for (const h of this.homes()) backlog[h] = await readBacklog(h);
    this.fleet.backlog = backlog;
    this.changed();
  }

  private async gh<T>(path: string): Promise<T> {
    await Bun.sleep(this.opts.ghPaceMs);
    const { out, err, code } = await run(["gh", "api", path], this.fleet.main);
    if (code !== 0) throw new Error(`gh api ${path.split("?")[0]}: ${err.trim().slice(0, 200)}`);
    return JSON.parse(out) as T;
  }

  /** A PR's owning task: a live task record whose pr= or branch= names it. fm-pr-merge.sh needs one. */
  private indexOwners() {
    const tasks = [...this.fleet.mates, ...this.fleet.workers];
    for (const p of this.fleet.prs) {
      const t = tasks.find((t) => t.meta.pr === p.url) ?? (p.ref ? tasks.find((t) => t.meta.branch === p.ref && t.meta.kind !== "secondmate") : undefined);
      p.owner = t && { home: t.home, task: t.id };
    }
  }

  async refreshPrs() {
    if (!this.fleet.login) this.fleet.login = (await this.gh<{ login: string }>("user")).login;
    type Item = { html_url: string; repository_url: string; number: number; title: string; draft?: boolean; updated_at: string };
    const items: Item[] = [];
    for (let page = 1; page <= 3; page++) {
      const r = await this.gh<{ items: Item[]; total_count: number }>(`search/issues?q=${encodeURIComponent(`is:pr is:open author:${this.fleet.login}`)}&sort=updated&per_page=100&page=${page}`);
      items.push(...r.items);
      if (items.length >= r.total_count || !r.items.length) break;
    }
    const old = new Map(this.fleet.prs.map((p) => [p.url, p]));
    const prs: Pr[] = items.map((i) => {
      const o = old.get(i.html_url);
      const repo = i.repository_url.split("/").slice(-2).join("/");
      return { ...o, url: i.html_url, repo, number: i.number, title: i.title, draft: !!i.draft, updated: i.updated_at, ...(o?.updated === i.updated_at ? {} : { checks: undefined }) };
    });
    // The owner's own repos first: only those can merge here.
    const own = (p: Pr) => p.repo.startsWith(`${this.fleet.login}/`);
    prs.sort((a, b) => Number(own(b)) - Number(own(a)) || b.updated.localeCompare(a.updated));
    this.fleet.prs = prs;
    this.fleet.prsAt = Date.now();
    this.indexOwners();
    this.changed();
    for (const p of prs) {
      if (green(p.checks)) continue; // green at an unchanged head; anything else may be re-run
      const pull = await this.gh<{ head: { sha: string; ref: string }; draft: boolean }>(`repos/${p.repo}/pulls/${p.number}`);
      const runs = await this.gh<{ check_runs: { name: string; id: number; status: string; conclusion: string | null }[] }>(`repos/${p.repo}/commits/${pull.head.sha}/check-runs?per_page=100`);
      const st = await this.gh<{ statuses: { state: string }[] }>(`repos/${p.repo}/commits/${pull.head.sha}/status`);
      Object.assign(p, { ref: pull.head.ref, draft: pull.draft, checks: countChecks(runs.check_runs, st.statuses) });
      this.indexOwners();
      this.changed();
    }
  }
}
