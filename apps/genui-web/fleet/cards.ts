// The owner's fleet in the planned card kinds: asks are decisions, second mates are crew cards with their
// workers, owned PRs are pipelines or merge decisions. Actions run the fleet's own scripts, and only after
// a second "confirm" decision card the owner picks.
import type { Component } from "@crewship/genui-spec";
import { green, isSlug, run, type Ask, type Fleet, type FleetSource, type Pr, type Task } from "./data";

type P = Record<string, unknown>;
const MAX_TEXT = 4000;
const cut = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const card = (kind: string, proj: string, base: number, props: P): Component => ({ type: "card", props: { kind, proj, base, ...props } });
const said = (r: { out: string; err: string }) => (r.err.trim() || r.out.trim()).split("\n").slice(-4).join(" ");

const MATE_HSL = ["hsl(262 92% 70%)", "hsl(188 95% 58%)", "hsl(320 90% 66%)", "hsl(152 72% 56%)", "hsl(38 98% 62%)", "hsl(210 90% 68%)", "hsl(0 90% 66%)", "hsl(48 96% 60%)"];

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
const askId = (a: Ask) => `ask-${a.task}-${a.key}`.slice(0, 64);
const prId = (p: Pr) => `pr-${p.repo.replace("/", "-")}-${p.number}`.slice(0, 64);

/** An action the owner asked for, shown as a confirm card until they pick Yes or Cancel. */
export type Pending = { id: string; q: string; why: string; run: () => Promise<{ ok: boolean; text: string }> };

// The plan shows a few readable cards per cluster; the rest of a cluster is one list card, so the camera never zooms out to a wall.
const SHOWN = 4;

export function fleetCards(f: Fleet, pending: Map<string, Pending>): Record<string, Component> {
  const out: Record<string, Component> = {};
  const groups = new Map<string, { id: string; c: Component; line: string }[]>();
  const add = (g: string, id: string, c: Component, line: string) => (groups.get(g) ?? groups.set(g, []).get(g)!).push({ id, c, line });
  for (const a of f.asks)
    add(clusterOf(f, a.home, a.task), askId(a), card("decision", "", 90, {
      need: true, q: `${a.task}: ${cut(a.note, 120)}`, why: a.key, task: a.task, home: a.home, key: a.key,
      opts: [{ k: "answer", b: "Answer", rec: true }, { k: "open", b: "Show worker" }],
    }), `ask ${a.task}: ${cut(a.note, 80)}`);
  for (const m of [{ id: "fm", lines: [] as Task["lines"], home: f.main }, ...f.mates]) {
    const crew = f.workers.filter((w) => (w.mate ?? "fm") === m.id);
    if (m.id === "fm" && !crew.length) continue;
    const busy = crew.filter((w) => w.busy === "busy").length;
    add(m.id, `crew-${m.id}`.slice(0, 64), card("crew", "", busy ? 45 : 25, {
      title: m.id === "fm" ? `First mate · ${busy} of ${crew.length} busy` : `${m.id} · ${last(m as Task)?.state ?? "no status"}`, task: m.id === "fm" ? undefined : m.id, home: m.home,
      members: crew.map((w) => ({ name: w.id, hsl: w.busy === "busy" ? "hsl(152 72% 56%)" : "hsl(232 10% 44%)", doing: `${last(w)?.state ?? ""} · ${cut(last(w)?.text ?? "", 110)}` })),
    }), "");
  }
  const own = f.prs.filter((p) => p.repo.startsWith(`${f.login}/`) && !p.draft);
  // ready to merge first, then failing, then the rest
  const rank = (p: Pr) => (!mergeBlock(f, p) ? 0 : p.checks?.bad ? 1 : 2);
  for (const p of [...own].sort((a, b) => rank(a) - rank(b))) {
    const why = mergeBlock(f, p), c = p.checks, g = p.owner ? clusterOf(f, p.owner.home, p.owner.task) : "fm";
    add(g, prId(p), !why
      ? card("decision", "", 70, { need: true, q: `Merge ${p.repo}#${p.number} ${cut(p.title, 80)}?`, why: `${c?.ok} checks green · ${p.owner?.task}`, url: p.url, prUrl: p.url, opts: [{ k: "merge", b: "Merge", rec: true }, { k: "later", b: "Not now" }] })
      : c?.bad
        ? card("note", "", 60, { title: `${p.repo}#${p.number}: ${c.bad} check${c.bad > 1 ? "s" : ""} failing`, flag: "failing", url: p.url, items: [cut(p.title, 90)] })
        : card("pipeline", "", 40, { title: `${p.repo}#${p.number} ${cut(p.title, 60)}`, url: p.url, stages: ["Open", "Checks", "Review", "Merge"], at: !c ? 0 : c.pending ? 1 : 2, kpi: { value: c ? `${c.ok}/${c.ok + c.bad + c.pending}` : "…", unit: "checks" } }),
      `PR ${p.repo}#${p.number} ${c ? `${c.ok}✓ ${c.bad}✗ ${c.pending}…` : "…"} ${cut(p.title, 50)}`);
  }
  for (const [g, list] of groups) {
    list.sort((a, b) => Number(b.id.startsWith("crew-")) - Number(a.id.startsWith("crew-")));
    for (const x of list.slice(0, SHOWN - 1)) out[x.id] = { ...x.c, props: { ...x.c.props, proj: g } };
    if (list.length >= SHOWN) out[`more-${g}`.slice(0, 64)] = card("note", g, 15, { title: `${list.length - SHOWN + 1} more`, items: list.slice(SHOWN - 1, SHOWN + 13).map((x) => x.line).filter(Boolean) });
  }
  for (const p of pending.values())
    out[p.id] = card("decision", "fm", 300, { need: true, q: p.q, why: p.why, opts: [{ k: "yes", b: "Yes, do it", rec: true }, { k: "cancel", b: "Cancel" }] });
  return out;
}

/** Header crew pills: second mates, then busy workers. */
export const fleetTuis = (f: Fleet) => [...f.mates, ...f.workers.filter((w) => w.busy === "busy")].map((t) => ({ name: t.id, proj: t.meta.kind === "secondmate" ? t.id : (t.mate ?? "fm") }));

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
    id: `confirm-answer`, q: `Send this answer to ${a.task} and close ${a.key}?`, why: cut(t, 300),
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
    id: `confirm-steer`, q: `Send this message to ${t.id}?`, why: cut(m, 300),
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
    id: `confirm-merge`, q: `Merge ${p.repo}#${p.number}? It lands on its base branch.`, why: `fm-pr-merge.sh ${o.task}`,
    run: async () => {
      const r = await run([`${o.home}/bin/fm-pr-merge.sh`, o.task, p.url], o.home, 600_000);
      return { ok: r.code === 0, text: r.code === 0 ? `Merged ${p.repo}#${p.number}` : `Merge of ${p.repo}#${p.number} refused: ${said(r)}` };
    },
  };
}
