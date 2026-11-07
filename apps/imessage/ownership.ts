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
