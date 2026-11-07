// Who owns the line (docs/imessage.md#rolling-deploys). A slot bridge (FM_IMESSAGE_SLOT) owns the inbound loop and the
// outbox only while its slot is named in $STATE/active, it holds the exclusive flock $STATE/owner.lock, and the main
// port is free. Until then it is standby: it serves GET /ready and /health on the second port and nothing else.
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";

const activeFile = (state: string) => `${state}/active`;

export function readActive(state: string): string | undefined {
  try { return readFileSync(activeFile(state), "utf8").trim() || undefined; } catch { return undefined; }
}

export function setActive(state: string, slot: string) {
  mkdirSync(state, { recursive: true, mode: 0o700 });
  writeFileSync(`${activeFile(state)}.tmp`, `${slot}\n`, { mode: 0o600 });
  renameSync(`${activeFile(state)}.tmp`, activeFile(state));
}

// Holds `file` exclusively until release() or the holder dies: flock runs a cat that ignores SIGTERM and ends when its
// stdin closes, so a crashed or stopping bridge keeps the lock until the process is really gone. Resolves null on timeout;
// waitMs 0 tries once.
export async function holdLock(file: string, waitMs = Infinity): Promise<{ release(): void } | null> {
  const proc = Bun.spawn(["flock", "-x", ...(waitMs === 0 ? ["-n"] : []), file, "sh", "-c", 'trap "" TERM; echo held; exec cat'], { stdin: "pipe", stdout: "pipe", stderr: "inherit" });
  const reader = proc.stdout.getReader();
  const got = await Promise.race([reader.read().then((r) => !!r.value), ...(waitMs === 0 || waitMs === Infinity ? [] : [Bun.sleep(waitMs).then(() => false)])]);
  if (!got) {
    proc.kill("SIGKILL");
    return null;
  }
  return { release: () => { proc.stdin.end(); } };
}

export async function portFree(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const probe = createServer().once("error", () => resolve(false)).listen(port, "127.0.0.1", () => probe.close(() => resolve(true)));
  });
}

export type Checks = Record<string, () => Promise<void>>;

// Runs every check; the result names each one that failed. A check that throws fails with its message.
export async function runChecks(checks: Checks): Promise<{ ok: boolean; failed: Record<string, string> }> {
  const failed: Record<string, string> = {};
  for (const [name, check] of Object.entries(checks)) {
    try { await check(); } catch (e) { failed[name] = e instanceof Error ? e.message : String(e); }
  }
  return { ok: !Object.keys(failed).length, failed };
}

// Returns once this slot owns the line. `line` settles when the transports are connected; the standby gate reports it.
export async function ownership(o: {
  state: string; slot: string; port: number; standbyPort: number; line: Promise<unknown>; checks: Checks; say: (line: string) => void;
}) {
  const standby = () => { const a = readActive(o.state); return a !== undefined && a !== o.slot; };
  let connected = false;
  const connect = o.line.then((v) => { connected = true; return v; });
  let server: { stop(force?: boolean): unknown } | undefined;
  if (standby()) {
    const checks = o.checks;
    server = Bun.serve({ hostname: "127.0.0.1", port: o.standbyPort, async fetch(req) {
      if (req.headers.get("x-firstmate") !== "1") return new Response("forbidden\n", { status: 403 });
      const path = new URL(req.url).pathname;
      if (path === "/health") return new Response("ok\n");
      if (path !== "/ready") return new Response("not found\n", { status: 404 });
      const result = connected ? await runChecks(checks) : { ok: false, failed: { line: "transports not connected yet" } };
      return Response.json({ slot: o.slot, ...result }, { status: result.ok ? 200 : 503 });
    } });
    o.say(`standby slot ${o.slot} on 127.0.0.1:${o.standbyPort}, waiting for ownership`);
  }
  const usec = Number(process.env.WATCHDOG_USEC);
  const beat = usec && server ? setInterval(() => Bun.spawn(["systemd-notify", "WATCHDOG=1"], { stdout: "ignore", stderr: "ignore" }), Math.min(30_000, usec / 4000)) : undefined;
  try {
    await connect;
    while (standby()) await Bun.sleep(250);
    const lock = await holdLock(`${o.state}/owner.lock`);
    // A bridge from before slots has no lock; it frees the port only when it exits.
    while (!(await portFree(o.port))) await Bun.sleep(250);
    if (!lock) throw new Error("owner lock not acquired");
    o.say(`slot ${o.slot} owns the line`);
  } finally {
    clearInterval(beat);
    server?.stop(true);
  }
}
