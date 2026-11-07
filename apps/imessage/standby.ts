// The standby side of a rolling deploy (docs/imessage.md#rolling-deploys): the gate server, the takeover, the probe.
import { holdLock, portFree, readActive } from "./ownership.ts";
import { natives } from "./selfheal.ts";

// The standby gate's checks: the natives load, and one real desk call with a stub prompt gives a reply (no text is sent).
export function standbyChecks(env: Record<string, string | undefined>, stub: () => Promise<{ ok: boolean; drafted: string }>): Checks {
  return {
    natives: async () => {
      const probe = env.FM_IMESSAGE_TEST === "1" ? env.FM_IMESSAGE_TEST_NATIVES : undefined; // the suite cannot load a real pi_natives .node
      if (probe && await Bun.spawn(["sh", "-c", probe]).exited) throw new Error("natives do not load");
      if (!probe) await natives(env);
    },
    desk: async () => {
      const read = await stub();
      if (!read.ok || !read.drafted.trim()) throw new Error("the desk model gave no stub reply");
    },
  };
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

// The standby control server and its watchdog beat; stop() closes both.
function serveStandby(o: { slot: string; standbyPort: number; checks: Checks; connected: () => boolean }): { stop(): void } {
  const server = Bun.serve({ hostname: "127.0.0.1", port: o.standbyPort, async fetch(req) {
    if (req.headers.get("x-firstmate") !== "1") return new Response("forbidden\n", { status: 403 });
    const path = new URL(req.url).pathname;
    if (path === "/health") return new Response("ok\n");
    if (path !== "/ready") return new Response("not found\n", { status: 404 });
    const result = o.connected() ? await runChecks(o.checks) : { ok: false, failed: { line: "transports not connected yet" } };
    return Response.json({ slot: o.slot, ...result }, { status: result.ok ? 200 : 503 });
  } });
  const usec = Number(process.env.WATCHDOG_USEC);
  const beat = usec ? setInterval(() => Bun.spawn(["systemd-notify", "WATCHDOG=1"], { stdout: "ignore", stderr: "ignore" }), Math.min(30_000, usec / 4000)) : undefined;
  return { stop: () => { clearInterval(beat); server.stop(true); } };
}

// Takes the lock and the main port once this slot is active. A bridge from before slots has no lock; it frees the port only when it exits.
async function takeOver(o: { state: string; port: number }) {
  const lock = await holdLock(`${o.state}/owner.lock`);
  while (!(await portFree(o.port))) await Bun.sleep(250);
  if (!lock) throw new Error("owner lock not acquired");
}

// Returns once this slot owns the line. `line` settles when the transports are connected; the standby gate reports it.
export async function ownership(o: {
  state: string; slot: string; port: number; standbyPort: number; line: Promise<unknown>; checks: Checks; say: (line: string) => void;
}) {
  const standby = () => { const a = readActive(o.state); return a !== undefined && a !== o.slot; };
  let connected = false;
  const connect = o.line.then(() => { connected = true; });
  const server = standby() ? serveStandby({ ...o, connected: () => connected }) : undefined;
  if (server) o.say(`standby slot ${o.slot} on 127.0.0.1:${o.standbyPort}, waiting for ownership`);
  try {
    await connect;
    while (standby()) await Bun.sleep(250);
    await takeOver(o);
    o.say(`slot ${o.slot} owns the line`);
  } finally {
    server?.stop();
  }
}

// A rolling deploy's confirm step: `start` queues one probe item through the real outbox and answers when its delivery
// ran; `confirm` is that delivery (a transport read, no text). `add` queues the item, `read` is the transport read.
export function probeKit<R, I extends { requestId?: string }>(add: (ref: R, id: string) => void, read: (item: I) => Promise<unknown>) {
  const waiting = new Map<string, () => void>();
  return {
    start(ref: R) {
      const id = `probe-${crypto.randomUUID()}`;
      const { promise, resolve } = Promise.withResolvers<void>();
      waiting.set(id, resolve);
      add(ref, id);
      return Promise.race([promise.then(() => new Response("probe ok\n")), Bun.sleep(30_000).then(() => new Response("probe timed out\n", { status: 503 }))]).finally(() => waiting.delete(id));
    },
    async confirm(item: I) {
      await read(item);
      waiting.get(item.requestId!)?.();
    },
  };
}
