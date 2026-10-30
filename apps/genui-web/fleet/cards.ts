// The owner's fleet in the planned card kinds: asks are decisions, second mates are crew cards with their
// workers, owned PRs are pipelines or merge decisions. Actions run the fleet's own scripts, and only after
// a second "confirm" decision card the owner picks.
import type { Component } from "@crewship/genui-spec";
import { briefOf } from "./brief";
import { type Ask, type Fleet, type FleetSource, green, isSlug, type Pr, run, type Task } from "./data";

type P = Record<string, unknown>;
const MAX_TEXT = 4000;
const cut = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const card = (kind: string, proj: string, base: number, props: P): Component => ({ type: "card", props: { kind, proj, base, ...props } });
const said = (r: { out: string; err: string }) => (r.err.trim() || r.out.trim()).split("\n").slice(-4).join(" ");

const MATE_HSL = [
  "hsl(262 92% 70%)",
  "hsl(188 95% 58%)",
  "hsl(320 90% 66%)",
  "hsl(152 72% 56%)",
  "hsl(38 98% 62%)",
  "hsl(210 90% 68%)",
  "hsl(0 90% 66%)",
  "hsl(48 96% 60%)",
];

/** One cluster per mate: "fm" is the first mate (the main home), then each second mate, each with its colour. */
export function fleetProjects(f: Fleet): Record<string, { name: string; hsl: string }> {
  const out: Record<string, { name: string; hsl: string }> = { fm: { name: "first mate", hsl: "hsl(48 96% 60%)" } };
  f.mates.forEach((m, i) => (out[m.id] = { name: m.id, hsl: MATE_HSL[i % MATE_HSL.length] }));
  return out;
}

/** The cluster a task's cards go in: a second mate is its own, a worker goes with its mate, anything else with the first mate. */
const clusterOf = (f: Fleet, home: string, task?: string) => {
  const t = [...f.mates, ...f.workers].find((x) => x.home === home && x.id === task);
  return t?.meta.kind === "secondmate" ? t.id : (t?.mate ?? "fm");
};

/** Why fm-pr-merge.sh may not run for this PR; undefined when it may. */
export function mergeBlock(f: Fleet, p: Pr): string | undefined {
  if (!f.login || !p.repo.startsWith(`${f.login}/`)) return `not your repo (${p.repo.split("/")[0]})`;
  if (p.draft) return "draft";
  if (!p.checks) return "checks not read yet";
  if (!green(p.checks)) return p.checks.pending ? "checks still running" : p.checks.ok ? "checks failing" : "no checks";
  if (!p.owner) return "no live task owns it";
}

const last = (t: Task) => t.lines.at(-1);
export const askId = (a: Ask) => `ask-${a.task}-${a.key}`.slice(0, 64);
export const prId = (p: Pr) => `pr-${p.repo.replace("/", "-")}-${p.number}`.slice(0, 64);
export const crewId = (mate: string) => `crew-${mate}`.slice(0, 64);

/** A short title: who, then the first sentence cut to `n` words; the full text goes in the card body. */
export function short(who: string, text: string, n = 8): string {
  const w = (text.split(/(?<=[.?!])\s/)[0] ?? "").split(/\s+/).filter(Boolean);
  return `${who ? `${who}: ` : ""}${w.slice(0, n).join(" ")}${w.length > n ? "…" : ""}`;
}

/** An action the owner asked for, shown as a confirm card until they pick Yes or Cancel; `of` is the card it acts on, `state` its run. */
export type Pending = { id: string; q: string; why: string; of?: string; state?: "running" | "sent"; run: () => Promise<{ ok: boolean; text: string }> };

/** What the owner has open: the cluster the camera is on, the cards in full view, and each cluster's page. Only these load detail. */
export type Open = { cluster?: string | null; cards: Set<string>; page?: Map<string, number> };

/** What the owner can ask the chat to draw; nothing is on the canvas until he asks. */
export const TOPICS = ["asks", "prs", "crew", "usage", "merged", "host"] as const;
export type Topic = (typeof TOPICS)[number];

type Item = { id: string; g: string; c: Component; line: string; topic: Topic };

// The overview is each mate's crew card, its newest ask and a count; an open cluster shows up to DETAIL cards.
const OVERVIEW = 2,
  DETAIL = 8;

const URL_RE = /https?:\/\/[^\s)>\]]+?(?=[.,;:]?(?:[\s)>\]]|$))/g;
// links and correlation ids are for the fleet, not for the owner's one line
const clean = (s: string) =>
  s
    .replace(URL_RE, "")
    .replace(/\bcorr=\S+\s*/g, "")
    .trim();
export type Opt = { k: string; b: string; say: string; rec: boolean };

/** Button text: the first words of a choice, without its "(recommended)" note. */
const label = (s: string) => {
  const w = s
    .replace(/\(?recommended\)?:?/gi, "")
    .replace(/^[\s:,-]+/, "")
    .split(/\s+/)
    .filter(Boolean);
  const t = w
    .slice(0, 5)
    .join(" ")
    .replace(/[;:,.]+$/, "");
  return t.charAt(0).toUpperCase() + t.slice(1) + (w.length > 5 ? "…" : "");
};
const opt = (i: number, seg: string): Opt => ({ k: `o${i + 1}`, b: label(seg.split(/;|\.\s/)[0]), say: cut(seg.trim(), 300), rec: /recommend/i.test(seg) });

/** Numbered or lettered choices: "(1) x; (2) y", "A) x; B) y", "Option 1: x. Option 2: y". */
function markedOpts(t: string): Opt[] {
  const ms = [...t.matchAll(/(?<![\w(])(?:\(([1-9a-eA-E])\)|([1-9A-E])\)|Option ([1-9])\b)/g)];
  const first = ms.findIndex((m) => /^[1aA]$/.test(m[1] ?? m[2] ?? m[3]));
  if (first < 0 || ms.length - first < 2) return [];
  const run = ms.slice(first, first + 6);
  return run.map((m, i) => opt(i, t.slice(m.index + m[0].length, run[i + 1]?.index ?? t.length).replace(/^[\s:)]+/, "")));
}

/** The choices an ask names; the one it recommends alone; none for an open question (free text answers it). */
export function askOpts(note: string): Opt[] {
  const t = note.replace(URL_RE, "");
  const marked = markedOpts(t);
  if (marked.length) return marked;
  const list = /\bOptions?:\s*([^.]+)\./i
    .exec(t)?.[1]
    .split(/,\s*(?:or\s+)?|\s+or\s+/)
    .filter((s) => s.trim());
  if (list && list.length > 1) return list.slice(0, 6).map((s, i) => opt(i, s));
  const rec = /\bRecommend(?:ed|ation)?:?\s+([^.;]+)/i.exec(t)?.[1];
  return rec ? [{ ...opt(0, rec), rec: true }] : [];
}

/** The real facts behind one card, shown at once when the owner asks about it: an ask's full note, its task's latest lines, a PR's checks, else the card's own text. */
export function contextOf(f: Fleet, c: P): string[] {
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : "");
  const flat = (s: string) => s.replace(/\s+/g, " ");
  const task = str(c.task) || str(c.agent);
  const a = c.key ? f.asks.find((x) => x.key === c.key && x.task === task) : undefined;
  const t = [...f.mates, ...f.workers].find((x) => x.id === task && (!c.home || x.home === c.home));
  const facts = [
    str(c.ref),
    str(c.why),
    a ? `The full note: ${flat(a.note)}` : "",
    ...(t?.lines.slice(-3).map((l) => `${t.id} ${l.state}: ${flat(l.text)}`) ?? []),
    ...prFacts(f, c.prUrl ?? c.url),
  ].filter(Boolean);
  // a card with no fleet facts behind it shows its own text
  const own = [str(c.title) || str(c.q), str(c.body), ...(Array.isArray(c.items) ? c.items : []).map(str)].filter(Boolean);
  return [...new Set(facts.length ? facts : own)].slice(0, 8).map((s) => cut(s, 1200));
}

/** An open PR's title and checks, for a card that carries its link (a green PR as `prUrl`, any other as `url`). */
function prFacts(f: Fleet, url: unknown): string[] {
  const pr = f.prs.find((p) => p.url === url);
  if (!pr) return [];
  const c = pr.checks;
  return [`${pr.repo}#${pr.number}: ${pr.title}${pr.draft ? " (draft)" : ""}`, ...(c ? [`Checks: ${c.ok} passed, ${c.bad} failed, ${c.pending} running`] : [])];
}

const PR_LINK = /github\.com\/([\w.-]+\/[\w.-]+)\/pull\/(\d+)/;

/** The exact thing an ask is about: the open PR it links or names, else the brief's own ref, else the task and its project. */
export function askRef(f: Fleet, a: Ask, said = ""): string {
  const m = PR_LINK.exec(a.note),
    n = m ? Number(m[2]) : Number(/\bPR ?#?(\d{1,6})\b/.exec(a.note)?.[1] ?? 0);
  const same = f.prs.filter((p) => p.number === n && (!m || p.repo === m[1]));
  // a bare number is the task's own PR, or the one open PR with that number
  const p = same.find((p) => m || p.owner?.task === a.task) ?? (same.length === 1 ? same[0] : undefined);
  if (p) return `PR ${p.repo}#${p.number} · ${cut(p.title, 70)}`;
  if (m) return `PR ${m[1]}#${m[2]}`;
  if (said) return said;
  const t = [...f.mates, ...f.workers].find((t) => t.id === a.task && t.home === a.home);
  const proj = t?.meta.projects ?? t?.meta.project?.split("/").pop();
  return proj ? `${a.task} · ${proj}` : a.task;
}

function askItem(f: Fleet, a: Ask, open: Open): Item {
  const id = askId(a),
    full = open.cards.has(id),
    g = clusterOf(f, a.home, a.task),
    brief = briefOf(a),
    parsed = askOpts(a.note);
  // a mate's own ask sits in its own cluster, whose label already names it
  const who = g === a.task ? "" : a.task;
  return {
    id,
    g,
    topic: "asks",
    line: `ask ${a.task}: ${brief?.what ?? cut(a.note, 80)}`,
    c: card("decision", "", 90, {
      need: true,
      // the brief is written to fit; until it lands, the note's first words stand in
      q: brief ? `${who ? `${who}: ` : ""}${brief.what}` : short(who, clean(a.note)),
      ...(brief?.why ? { why: brief.why } : {}),
      // the raw note only in the full view, one tap away
      ...(full ? { body: cut(a.note, MAX_TEXT) } : {}),
      ...(a.note.match(URL_RE) ? { url: a.note.match(URL_RE)![0] } : {}),
      task: a.task,
      ref: askRef(f, a, brief?.ref),
      home: a.home,
      key: a.key,
      free: true,
      // the label is the whole answer: the brief can reorder the note's choices, so no pairing with the parsed ones
      opts: brief ? brief.opts.map((o, i) => ({ k: `o${i + 1}`, b: o.b, say: "", rec: o.rec })) : parsed,
    }),
  };
}

function crewItem(f: Fleet, m: Pick<Task, "id" | "home" | "lines">, open: Open): Item | undefined {
  const crew = f.workers.filter((w) => (w.mate ?? "fm") === m.id);
  if (m.id === "fm" && !crew.length) return;
  const id = crewId(m.id),
    full = open.cards.has(id) || open.cluster === m.id;
  const busy = crew.filter((w) => w.busy === "busy").length,
    now = last(m as Task);
  return {
    id,
    g: m.id,
    topic: "crew",
    line: "",
    c: card("crew", "", busy ? 45 : 25, {
      title: m.id === "fm" ? `First mate · ${busy} of ${crew.length} busy` : `${m.id} · ${now?.state ?? "no status"}`,
      body: full
        ? m.lines
            .slice(-6)
            .map((l) => `${l.state}: ${l.text}`)
            .join("\n")
        : cut(now?.text ?? "", 160),
      task: m.id === "fm" ? undefined : m.id,
      home: m.home,
      members: crew.map((w) => ({
        name: w.id,
        hsl: w.busy === "busy" ? "hsl(152 72% 56%)" : "hsl(232 10% 44%)",
        doing: `${last(w)?.state ?? ""} · ${cut(last(w)?.text ?? "", full ? 110 : 40)}`,
      })),
    }),
  };
}

function prItem(f: Fleet, p: Pr): Item {
  const why = mergeBlock(f, p),
    c = p.checks,
    g = p.owner ? clusterOf(f, p.owner.home, p.owner.task) : "fm";
  const line = `PR ${p.repo}#${p.number} ${c ? `${c.ok}✓ ${c.bad}✗ ${c.pending}…` : "…"} ${cut(p.title, 50)}`;
  if (!why)
    return {
      id: prId(p),
      g,
      topic: "prs",
      line,
      c: card("decision", "", 70, {
        need: true,
        q: `Merge ${p.repo}#${p.number}: ${cut(p.title, 48)}`,
        url: p.url,
        prUrl: p.url,
        opts: [
          { k: "merge", b: "Merge", rec: true },
          { k: "later", b: "Not now" },
        ],
      }),
    };
  if (c?.bad)
    return {
      id: prId(p),
      g,
      topic: "prs",
      line,
      c: card("note", "", 60, { title: `${p.repo}#${p.number}: ${c.bad} failing`, flag: "failing", url: p.url, items: [cut(p.title, 90)] }),
    };
  return {
    id: prId(p),
    g,
    topic: "prs",
    line,
    c: card("pipeline", "", 40, {
      title: `${p.repo}#${p.number}`,
      url: p.url,
      stages: ["Open", "Checks", "Review", "Merge"],
      at: !c ? 0 : c.pending ? 1 : 2,
      kpi: { value: c ? `${c.ok}/${c.ok + c.bad + c.pending}` : "…", unit: "checks" },
    }),
  };
}

function items(f: Fleet, open: Open, shown: Set<Topic>): Item[] {
  const own = f.prs.filter((p) => p.repo.startsWith(`${f.login}/`) && !p.draft);
  // ready to merge first, then failing, then the rest
  const rank = (p: Pr) => (!mergeBlock(f, p) ? 0 : p.checks?.bad ? 1 : 2);
  const crews = shown.has("crew") ? [{ id: "fm", lines: [] as Task["lines"], home: f.main }, ...f.mates].map((m) => crewItem(f, m, open)) : [];
  return [
    ...crews.filter((x): x is Item => !!x),
    ...(shown.has("asks") ? f.asks.map((a) => askItem(f, a, open)) : []),
    ...(shown.has("prs") ? own.sort((a, b) => rank(a) - rank(b)).map((p) => prItem(f, p)) : []),
  ];
}

/** A cluster's cards, one page at a time: the overview shows a few, the open cluster more; an open card always shows; the rest is one count card that pages. */
function place(out: Record<string, Component>, g: string, list: Item[], open: Open) {
  const n = open.cluster === g ? DETAIL : OVERVIEW,
    pages = Math.ceil(list.length / n),
    page = (open.page?.get(g) ?? 0) % pages;
  const shown = list.filter((x, i) => Math.floor(i / n) === page || open.cards.has(x.id)),
    rest = list.filter((x) => !shown.includes(x));
  for (const x of shown) out[x.id] = { ...x.c, props: { ...x.c.props, proj: g } };
  if (!rest.length) return;
  out[`more-${g}`.slice(0, 64)] = card("note", g, 15, {
    title: `${rest.length} more · page ${page + 1} of ${pages}`,
    // the cards off this page still need him: the cluster and header counts include them
    unseen: rest.filter((x) => x.c.props.need === true).length,
    acts: [{ k: "page", b: page + 1 < pages ? "Next page" : "First page", pri: true }],
  });
}

export function fleetCards(f: Fleet, pending: Map<string, Pending>, open: Open = { cards: new Set() }, shown = new Set<Topic>()): Record<string, Component> {
  const out: Record<string, Component> = {},
    groups = new Map<string, Item[]>();
  for (const x of items(f, open, shown)) (groups.get(x.g) ?? groups.set(x.g, []).get(x.g)!).push(x);
  for (const [g, list] of groups) place(out, g, list, open);
  for (const p of pending.values())
    out[p.id] = card("decision", "fm", 300, {
      need: !p.state,
      q: p.q,
      why: p.state === "running" ? "Sending…" : p.why,
      ...(p.state ? { done: true, pick: "yes", sent: p.state === "sent" } : {}),
      opts: [
        { k: "yes", b: "Yes, do it", rec: true },
        { k: "cancel", b: "Cancel" },
      ],
    });
  return out;
}

/** Header crew pills: second mates, then busy workers. */
export const fleetTuis = (f: Fleet) =>
  [...f.mates, ...f.workers.filter((w) => w.busy === "busy")].map((t) => ({ name: t.id, proj: t.meta.kind === "secondmate" ? t.id : (t.mate ?? "fm") }));

/** A live status tail for a task pill. */
export function tuiLines(f: Fleet, name: string): string[] | undefined {
  const t = [...f.mates, ...f.workers].find((t) => t.id === name);
  return t?.lines.slice(-14).map((l) => `${l.state}: ${l.text}`);
}

function text(v: unknown): string {
  const t = typeof v === "string" ? v.trim() : "";
  if (!t) throw new Error("empty message");
  if (t.length > MAX_TEXT) throw new Error(`keep it under ${MAX_TEXT} characters`);
  return t;
}

/** Answer an ask: fm-send.sh --resolve-key closes it in the asking task's status file. */
export function answer(src: FleetSource, props: P, msg: unknown): Pending {
  const a = src.fleet.asks.find((a) => a.home === props.home && a.task === props.task && a.key === props.key);
  if (!a || !isSlug(a.task) || !isSlug(a.key)) throw new Error("that ask is already closed");
  const t = text(msg);
  return {
    id: `confirm-answer`,
    q: `Send this answer to ${a.task} and close ${a.key}?`,
    why: cut(t, 300),
    run: async () => {
      const r = await run([`${a.home}/bin/fm-send.sh`, a.task, "--resolve-key", a.key, `Captain answer (genui app) to ${a.key}: ${t}`], a.home);
      return { ok: r.code === 0, text: r.code === 0 ? `Answered ${a.task} · ${a.key}` : `Answer to ${a.task} failed: ${said(r)}` };
    },
  };
}

/** Steer a worker or mate: a durable inbox record through its home's fm-send.sh. */
export function steer(src: FleetSource, name: string, msg: unknown): Pending {
  const t = [...src.fleet.mates, ...src.fleet.workers].find((t) => t.id === name);
  if (!t || !isSlug(t.id)) throw new Error(`${name} is not in the fleet`);
  const m = text(msg);
  return {
    id: `confirm-steer`,
    q: `Send this message to ${t.id}?`,
    why: cut(m, 300),
    run: async () => {
      const r = await run([`${t.home}/bin/fm-send.sh`, t.id, `Captain (genui app): ${m}`], t.home);
      return { ok: r.code === 0, text: r.code === 0 ? `Sent to ${t.id}` : `Message to ${t.id} failed: ${said(r)}` };
    },
  };
}

/** Merge: own repo, green, live owner task; fm-pr-merge.sh re-checks it all live. */
export function merge(src: FleetSource, url: unknown): Pending {
  const p = src.fleet.prs.find((p) => p.url === url);
  if (!p) throw new Error("that PR is not open any more");
  const why = mergeBlock(src.fleet, p);
  if (why || !p.owner) throw new Error(`not merged: ${why}`);
  const o = p.owner;
  return {
    id: `confirm-merge`,
    q: `Merge ${p.repo}#${p.number}? It lands on its base branch.`,
    why: `fm-pr-merge.sh ${o.task}`,
    run: async () => {
      const r = await run([`${o.home}/bin/fm-pr-merge.sh`, o.task, p.url], o.home, 600_000);
      return { ok: r.code === 0, text: r.code === 0 ? `Merged ${p.repo}#${p.number}` : `Merge of ${p.repo}#${p.number} refused: ${said(r)}` };
    },
  };
}
