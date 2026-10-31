// Topic summaries from `crewboard topics --summary --json`. A board without summaries (or none running) gives an empty map.
export type Summaries = Map<string, string>

export async function fetchSummaries(bin = "crewboard"): Promise<Summaries> {
  const out = new Map<string, string>()
  try {
    const p = Bun.spawn([bin, "topics", "--summary", "--json"], { stdout: "pipe", stderr: "ignore" })
    const text = await new Response(p.stdout).text()
    if ((await p.exited) !== 0) return out
    for (const t of JSON.parse(text)) if (typeof t.topic === "string" && typeof t.summary === "string" && t.summary) out.set(t.topic, t.summary)
  } catch {}
  return out
}

// Per topic, the highest seq an agent has read, from `crewboard topics --json`. Empty when the board is off.
export type ReadSeqs = Map<string, number>

export async function fetchReadSeqs(bin = "crewboard"): Promise<ReadSeqs> {
  const out: ReadSeqs = new Map()
  try {
    const p = Bun.spawn([bin, "topics", "--json"], { stdout: "pipe", stderr: "ignore" })
    const text = await new Response(p.stdout).text()
    if ((await p.exited) !== 0) return out
    for (const t of JSON.parse(text)) if (typeof t.topic === "string" && typeof t.read_seq === "number") out.set(t.topic, t.read_seq)
  } catch {}
  return out
}

// Messages above the topic's read_seq. Until the board has reported it (undefined), nothing counts, so a slow first poll shows no false unread.
export const unreadCount = (msgs: { seq: number }[], readSeq: number | undefined) => (readSeq === undefined ? 0 : msgs.filter(m => m.seq > readSeq).length)
