#!/usr/bin/env bun
// Runs `gws` unchanged and, after a successful Gmail message read, texts the owner which agent read which mail and why.
// Usage: read.ts <gws args...>   Env: MAIL_READ_AGENT, MAIL_READ_PURPOSE, MAIL_READ_SEND (default `fm-imessage`, text on stdin).

const MAX = 80

// Mail text is untrusted: drop links and every word holding a digit, so a sign-in code cannot reach the text.
export function clean(s: string): string {
  const t = s.replace(/\s+/g, " ").replace(/\S*:\/\/\S*|\S*\d\S*/g, "[removed]").trim()
  return t.length > MAX ? `${t.slice(0, MAX)}...` : t
}

export function isMessageRead(args: string[]): boolean {
  const i = args.indexOf("gmail")
  return i >= 0 && args[i + 1] === "users" && args[i + 2] === "messages" && args[i + 3] === "get"
}

export function notice(out: string, agent: string, purpose: string): string {
  let h: Record<string, string> = {}
  try {
    const headers: { name: string; value: string }[] = JSON.parse(out)?.payload?.headers ?? []
    h = Object.fromEntries(headers.map(x => [String(x.name).toLowerCase(), String(x.value)]))
  } catch {}
  const from = h.from ? clean(h.from) : "unknown sender"
  const subject = h.subject ? clean(h.subject) : "no subject"
  return `Mail read: ${agent.trim() || "an agent"} read mail from ${from}, subject "${subject}". Purpose: ${purpose.trim() || "not given"}.`
}

if (import.meta.main) {
  const args = process.argv.slice(2)
  const p = Bun.spawn(["gws", ...args], { stdin: "inherit", stdout: "pipe", stderr: "inherit" })
  const out = await new Response(p.stdout).text()
  const code = await p.exited
  process.stdout.write(out)
  if (code === 0 && isMessageRead(args)) {
    try {
      const text = notice(out, process.env.MAIL_READ_AGENT ?? "", process.env.MAIL_READ_PURPOSE ?? "")
      const cmd = (process.env.MAIL_READ_SEND ?? "fm-imessage").split(" ")
      const s = Bun.spawn(["timeout", "15", ...cmd], { stdin: new Blob([text]), stdout: "ignore", stderr: "ignore" })
      await s.exited
    } catch {} // a failed notice never fails the read
  }
  process.exit(code)
}
