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
  if (i < 0 || args[i + 1] !== "users") return false
  const [res, a, b] = args.slice(i + 2)
  return ((res === "messages" || res === "threads") && (a === "get" || a === "list")) || (res === "messages" && a === "attachments" && b === "get")
}

export function notice(out: string, agent: string, purpose: string): string {
  let h: Record<string, string> = {}
  try {
    const j = JSON.parse(out)
    const headers: { name: string; value: string }[] = (j?.payload ?? j?.messages?.[0]?.payload)?.headers ?? []
    h = Object.fromEntries(headers.map(x => [String(x.name).toLowerCase(), String(x.value)]))
  } catch {}
  const from = h.from ? clean(h.from) : "unknown sender"
  return `Mail read: ${agent.trim() || "an agent"} read mail from ${from}. Purpose: ${purpose.trim() || "not given"}.`
}

if (import.meta.main) {
  const args = process.argv.slice(2)
  const read = isMessageRead(args)
  const p = Bun.spawn(["gws", ...args], { stdin: "inherit", stdout: read ? "pipe" : "inherit", stderr: "inherit" })
  const bytes = read ? new Uint8Array(await new Response(p.stdout).arrayBuffer()) : new Uint8Array()
  const code = await p.exited
  if (read) process.stdout.write(bytes)
  if (code === 0 && read) {
    try {
      const text = notice(new TextDecoder().decode(bytes), process.env.MAIL_READ_AGENT ?? "", process.env.MAIL_READ_PURPOSE ?? "")
      const cmd = (process.env.MAIL_READ_SEND ?? "fm-imessage").split(" ")
      const s = Bun.spawn(["timeout", "15", ...cmd], {
        stdin: new Blob([text]),
        stdout: "ignore",
        stderr: "ignore",
        env: { ...process.env, FM_IMESSAGE_WAIT_S: "0" },
      })
      await s.exited
    } catch {} // a failed notice never fails the read
  }
  process.exit(code)
}
