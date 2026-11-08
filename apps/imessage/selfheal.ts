// Self-healing for the iMessage line (docs/imessage.md#self-healing). Event driven: systemd restarts the bridge when it
// stops sending WATCHDOG=1, and the bridge sends it only while the line is healthy (port answers, no desk turn stuck
// past the deadline, the pi-natives .node loads). A failed start that never became healthy counts as a failed heal;
// the second one in a row alerts the owner once. Run as `bun selfheal.ts start` from ExecStartPre, and as
// `bun selfheal.ts failed` from the OnFailure unit.
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, renameSync, rmSync, writeFileSync, copyFileSync, appendFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

type Env = Record<string, string | undefined>;
type State = { pending: boolean; fails: number; alerted: boolean };

const home = (env: Env) => env.HOME || homedir();
export const stateDir = (env: Env = process.env) => env.STATE_DIRECTORY || `${home(env)}/.local/state/fm-imessage`;
const stateFile = (env: Env) => `${stateDir(env)}/selfheal.json`;

export function loadState(env: Env = process.env): State {
  try {
    return { pending: false, fails: 0, alerted: false, ...JSON.parse(readFileSync(stateFile(env), "utf8")) };
  } catch {
    return { pending: false, fails: 0, alerted: false };
  }
}
function saveState(env: Env, state: State) {
  mkdirSync(stateDir(env), { recursive: true, mode: 0o700 });
  writeFileSync(`${stateFile(env)}.tmp`, JSON.stringify(state), { mode: 0o600 });
  renameSync(`${stateFile(env)}.tmp`, stateFile(env));
}

// The bridge reached a healthy beat: the last start worked.
export function markHealthy(env: Env = process.env) {
  const state = loadState(env);
  if (state.pending || state.fails || state.alerted) saveState(env, { pending: false, fails: 0, alerted: false });
}

const run = async (cmd: string[], env: Env, timeout = 30_000) => {
  const proc = Bun.spawn(cmd, { env: env as Record<string, string>, stdout: "pipe", stderr: "pipe", timeout });
  const [out, code] = await Promise.all([new Response(proc.stdout).text(), proc.exited]);
  return { out, code };
};

// Does every pi-natives .node under ~/.omp/natives/<omp version> load? Run in a child so a bad file cannot crash the bridge.
async function loads(dir: string, env: Env): Promise<boolean> {
  const want = `pi_natives.linux-x64-${/\bavx2\b/.test(readFileSync("/proc/cpuinfo", "utf8")) ? "modern" : "baseline"}.node`;
  const files = existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith(".node")) : [];
  if (!files.includes(want)) return false;
  for (const file of files) {
    const code = `process.dlopen({ exports: {} }, ${JSON.stringify(join(dir, file))})`;
    if ((await run([process.execPath, "-e", code], env, 20_000)).code !== 0) return false;
  }
  return true;
}

// The omp binary embeds its natives and unpacks them into $HOME/.omp/natives/<version> when a command like --help needs them, so a
// scratch HOME gives a fresh copy that is never half-written. Returns "ok", "repaired", or throws.
async function ompNatives(env: Env): Promise<"ok" | "repaired"> {
  const omp = env.FM_IMESSAGE_OMP || "omp";
  const version = (await run([omp, "--version"], env, 30_000)).out.trim().split("/").pop();
  if (!version) throw new Error("omp --version printed nothing");
  const dir = `${home(env)}/.omp/natives/${version}`;
  if (await loads(dir, env)) return "ok";
  const scratch = mkdtempSync(join(env.TMPDIR || "/tmp", "fm-natives-"));
  try {
    await run([omp, "--help"], { ...env, HOME: scratch }, 60_000);
    const fresh = `${scratch}/.omp/natives/${version}`;
    if (!(await loads(fresh, env))) throw new Error(`omp ${version} did not unpack natives that load`);
    mkdirSync(dir, { recursive: true });
    for (const file of readdirSync(fresh)) {
      copyFileSync(join(fresh, file), join(dir, `${file}.tmp`));
      renameSync(join(dir, `${file}.tmp`), join(dir, file));
    }
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
  if (!(await loads(dir, env))) throw new Error(`natives in ${dir} still do not load`);
  return "repaired";
}

// The bridge and the desk load @oh-my-pi/pi-natives from the install that omp's own packages resolve to (often the bun install
// cache), and that copy can lack its .node: the platform package holds the file and nothing copies it in. Probe the import in a
// child (runtime-selected path); on failure copy the missing .node files from the sibling platform package, atomically, and probe again.
export async function bridgeNatives(env: Env = process.env): Promise<"ok" | "repaired"> {
  const omp = Bun.which(env.FM_IMESSAGE_OMP || "omp", { PATH: env.PATH });
  if (!omp) throw new Error("omp is not on PATH");
  const entry = Bun.resolveSync("@oh-my-pi/pi-natives", dirname(realpathSync(omp)));
  const probe = async () => (await run([process.execPath, "-e", `await import(${JSON.stringify(pathToFileURL(entry).href)})`], env, 60_000)).code === 0;
  if (await probe()) return "ok";
  const pkg = dirname(dirname(entry));
  const platform = join(dirname(pkg), basename(pkg).replace(/^pi-natives/, `pi-natives-${process.platform}-${process.arch}`));
  const files = existsSync(platform) ? readdirSync(platform).filter((f) => f.endsWith(".node")) : [];
  if (!files.length) throw new Error(`pi-natives at ${pkg} does not load and ${platform} has no .node to copy`);
  for (const file of files) {
    copyFileSync(join(platform, file), join(dirname(entry), `${file}.tmp`));
    renameSync(join(dirname(entry), `${file}.tmp`), join(dirname(entry), file));
  }
  if (!(await probe())) throw new Error(`pi-natives at ${pkg} still does not load after copying ${files.join(", ")}`);
  return "repaired";
}

// Checks both places pi-natives is loaded from. Returns "ok", "repaired", or throws.
export async function natives(env: Env = process.env): Promise<"ok" | "repaired"> {
  const results = [await ompNatives(env), await bridgeNatives(env)];
  return results.includes("repaired") ? "repaired" : "ok";
}

// Tracks running desk turns so the heartbeat can see one stuck past the deadline.
export class Turns {
  private started = new Map<symbol, number>();
  begin(): () => void {
    const id = Symbol();
    this.started.set(id, Date.now());
    return () => void this.started.delete(id);
  }
  oldestMs(now = Date.now()): number {
    return this.started.size ? now - Math.min(...this.started.values()) : 0;
  }
}

// One alert per failure run: a text through the line when it answers, else one status line for Firstmate.
export async function alert(env: Env, message: string) {
  const sent = await run([env.FM_IMESSAGE_SEND || "fm-imessage", "--key", "selfheal-failed", "--", message], { ...env, FM_IMESSAGE_WAIT_S: "0" }, 30_000).catch(() => undefined);
  if (sent?.code === 0) return "text";
  const file = env.FM_IMESSAGE_ALERT_STATUS || `${env.FM_HOME || home(env)}/state/imessage-selfheal.status`;
  mkdirSync(join(file, ".."), { recursive: true });
  appendFileSync(file, `failed [at=${Math.floor(Date.now() / 1000)}]: ${message}\n`);
  return "status";
}

async function alertIfNeeded(env: Env, state: State) {
  if (state.fails < 2 || state.alerted) return;
  // A bridge that answers is healed: send nothing and forget the failures.
  const port = Number(env.FM_IMESSAGE_PORT || 8765);
  const up = await fetch(`http://127.0.0.1:${port}/health`, { headers: { "X-Firstmate": "1" }, signal: AbortSignal.timeout(5000) }).then((r) => r.ok, () => false);
  if (up) return saveState(env, { pending: false, fails: 0, alerted: false });
  state.alerted = true;
  saveState(env, state);
  await alert(env, `iMessage self-heal failed ${state.fails} times in a row; the bridge needs a human`);
}

// ExecStartPre: count a previous start that never became healthy, then check and repair the natives.
export async function onStart(env: Env = process.env) {
  const state = loadState(env);
  if (state.pending) state.fails++;
  try {
    const result = await natives(env);
    if (result === "repaired") console.log("fm-imessage: pi-natives repaired from the omp binary");
    state.pending = true;
    saveState(env, state);
    await alertIfNeeded(env, state);
  } catch (e) {
    console.error(`fm-imessage: natives check failed: ${e instanceof Error ? e.message : e}`);
    state.fails++;
    state.pending = false;
    saveState(env, state);
    await alertIfNeeded(env, state);
    throw e;
  }
}

// OnFailure: systemd gave up on the unit (start limit). Count it, alert if due, and start the unit again.
export async function onFailed(env: Env = process.env) {
  const state = loadState(env);
  state.fails++;
  state.pending = false;
  saveState(env, state);
  await alertIfNeeded(env, state);
  const unit = env.FM_IMESSAGE_UNIT || "fm-imessage.service";
  await run(["systemctl", "--user", "reset-failed", unit], env);
  await run(["systemctl", "--user", "start", "--no-block", unit], env);
}

// The watchdog heartbeat. Does nothing without WatchdogSec= (systemd sets WATCHDOG_USEC), so a hand run is unaffected.
export function heartbeat(o: { env: Env; port: number; turns: Turns; stopping: () => boolean }) {
  const usec = Number(o.env.WATCHDOG_USEC);
  if (!usec) return;
  const deadlineMs = Number(o.env.FM_IMESSAGE_TURN_DEADLINE_MS || 900_000);
  let busy = false;
  const beat = async () => {
    if (busy || o.stopping()) return;
    busy = true;
    try {
      if (o.turns.oldestMs() > deadlineMs) return console.error("fm-imessage: a desk turn is stuck; watchdog heartbeat withheld");
      const answer = await fetch(`http://127.0.0.1:${o.port}/health`, { headers: { "X-Firstmate": "1" }, signal: AbortSignal.timeout(10_000) });
      if (!answer.ok) return console.error(`fm-imessage: /health answered ${answer.status}; watchdog heartbeat withheld`);
      if ((await natives(o.env)) === "repaired") console.log("fm-imessage: pi-natives repaired from the omp binary");
      markHealthy(o.env);
      Bun.spawn(["systemd-notify", "WATCHDOG=1"], { stdout: "ignore", stderr: "ignore" });
    } catch (e) {
      console.error(`fm-imessage: health check failed: ${e instanceof Error ? e.message : e}; watchdog heartbeat withheld`);
    } finally {
      busy = false;
    }
  };
  void beat();
  setInterval(beat, Math.min(60_000, usec / 4000)).unref();
}

if (import.meta.main) {
  const mode = process.argv[2];
  if (mode !== "start" && mode !== "failed") throw new Error("usage: selfheal.ts start|failed");
  await (mode === "start" ? onStart() : onFailed()).catch(() => process.exit(1));
}
