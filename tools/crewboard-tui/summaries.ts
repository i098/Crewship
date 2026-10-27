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
