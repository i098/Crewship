// What the front desk was told, where it sent it and what it answered, from the bridge's routing.jsonl (bridge.ts recordRoute).
// This is the one place the view shows message text; it is a local, read-only view and nothing here is stored or sent.

export type Turn = { at: number; text: string; route: string; reply: string }

type Out = { bubbles?: string[]; react?: string }
type Ev = {
  at?: number; ids?: string[]; route?: string; handoffNote?: string; out?: Out; acknowledgement?: Out
  received?: { requestId?: string; text?: string; at?: number }
  v2?: { mate?: { id?: string }; intents?: { kind?: string; target?: string; model?: string }[] }
}

const TAIL_BYTES = 1 << 20 // the log grows without bound; the newest turns are at the end

// One JSON object per line. `received` opens a turn by requestId; later events name it in `ids`:
//   v2 (the front desk's plan): a mate, or an intent (relay target, dispatch model); route handoff: main Firstmate;
//   route desk or done with `out`, and `acknowledgement`: the desk's own bubbles or tapback.
// A work reply from a mate or main does not pass through this log, so such a turn shows no reply.
function nextRoute(e: Ev, t: Turn & { planned?: true }): string {
  if (e.v2) {
    const i = e.v2.intents?.[0]
    return e.v2.mate?.id ? `mate ${e.v2.mate.id}` : i?.kind === "dispatch" ? `dispatch ${i.model ?? ""}`.trim() : i?.target === "firstmate" ? "main" : i?.target ?? "main"
  }
  if (t.planned) return t.route
  const mate = e.route === "done" ? /^routed to (\S+)/.exec(e.handoffNote ?? "")?.[1] : undefined
  if (mate) return `mate ${mate}`
  if (e.route === "handoff") return "main"
  return (e.route === "desk" || e.route === "done") && t.route === "pending" ? "desk" : t.route
}

export function parseTurns(jsonl: string): Turn[] {
  const turns = new Map<string, Turn & { planned?: true }>()
  const lines = jsonl.length > TAIL_BYTES ? jsonl.slice(jsonl.indexOf("\n", jsonl.length - TAIL_BYTES) + 1) : jsonl
  for (const l of lines.split("\n")) {
    let e: Ev
    try { e = JSON.parse(l) } catch { continue }
    const r = e?.received
    if (r?.requestId) {
      if (!turns.has(r.requestId)) turns.set(r.requestId, { at: r.at ?? e.at ?? 0, text: String(r.text ?? ""), route: "pending", reply: "" })
      continue
    }
    const out = e?.out ?? e?.acknowledgement
    const reply = out?.bubbles?.length ? out.bubbles.join(" ") : out?.react ? `${out.react} (tapback)` : ""
    for (const t of (Array.isArray(e?.ids) ? e.ids : []).map(id => turns.get(id))) {
      if (!t) continue
      if (e.v2) t.planned = true
      t.route = nextRoute(e, t)
      if (reply) t.reply = reply
    }
  }
  return [...turns.values()].sort((a, b) => a.at - b.at).map(({ at, text, route, reply }) => ({ at, text, route, reply }))
}
