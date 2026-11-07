#!/usr/bin/env bun
// The only install path for the iMessage bridge (docs/imessage.md#rolling-deploys). Starts the staged build as a
// standby slot beside the running one, gates the cutover on its health check, hands the line over, confirms one
// outbox pass, and rolls back to the old slot on any failure.
//   imessage-deploy            roll the build in <dir>/stage out
//   imessage-deploy needed     exit 3 when the staged build and units differ from the last deployed ones, or no slot serves
//   imessage-deploy boot       start the active slot if it is down
//   imessage-deploy follow     the front unit's process: boot, then exit while the active slot is gone, so is-active tells the truth
//   imessage-deploy stop-all   stop every slot unless a deploy is running (the front unit's ExecStop)
// Env: FM_IMESSAGE_DIR (required), STATE_DIRECTORY, FM_IMESSAGE_PORT (8765), FM_IMESSAGE_NEXT_PORT (8766),
// FM_DEPLOY_SYSTEMCTL (systemctl).
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { holdLock, readActive, setActive } from "./ownership.ts";

const env = process.env;
const DIR = env.FM_IMESSAGE_DIR || (() => { throw new Error("imessage-deploy: FM_IMESSAGE_DIR is not set"); })();
const STATE = env.STATE_DIRECTORY || `${env.HOME}/.local/state/fm-imessage`;
const PORT = Number(env.FM_IMESSAGE_PORT || 8765);
const NEXT = Number(env.FM_IMESSAGE_NEXT_PORT || 8766);
const SYSTEMCTL = env.FM_DEPLOY_SYSTEMCTL || "systemctl";
const FRONT = "fm-imessage.service";
const GATE_MS = Number(env.FM_DEPLOY_GATE_MS || 420_000);
const OWN_MS = Number(env.FM_DEPLOY_OWN_MS || 120_000);
const BACK_MS = Number(env.FM_DEPLOY_BACK_MS || 420_000);

const say = (line: string) => console.log(`imessage-deploy: ${line}`);
const unit = (slot: string) => `fm-imessage@${slot}.service`;
async function sc(...args: string[]) {
  const proc = Bun.spawn([SYSTEMCTL, "--user", ...args], { stdout: "pipe", stderr: "pipe" });
  const [out, code] = await Promise.all([new Response(proc.stdout).text(), proc.exited]);
  return { out: out.trim(), code };
}
const active = async (name: string) => (await sc("is-active", "--quiet", name)).code === 0;
// The bridge from before slots is the front unit's own process, so it is told apart from the front unit's follow process
// by answering /health on the main port while no slot is recorded. After a rollback it runs as the slot "legacy".
const legacyRunning = async () => (await active(unit("legacy"))) || (readActive(STATE) === undefined && (await get(PORT, "/health")).ok);
const get = (port: number, path: string, method = "GET") =>
  fetch(`http://127.0.0.1:${port}${path}`, { method, headers: { "X-Firstmate": "1" }, signal: AbortSignal.timeout(40_000) }).then(async (r) => ({ ok: r.ok, body: (await r.text()).trim() }), () => ({ ok: false, body: "no answer" }));

// A unit that is still starting is not gone; one that failed, stopped, or waits to restart is.
const gone = async (name: string) => /^(failed|inactive)$|auto-restart/m.test((await sc("show", name, "-p", "ActiveState", "-p", "SubState", "--value")).out);

// Polls `check` until it passes, the unit is gone, or the time is up. Returns the last answer.
async function until(ms: number, check: () => Promise<{ ok: boolean; body: string }>, slot: string): Promise<{ ok: boolean; body: string }> {
  const end = Date.now() + ms;
  let last = { ok: false, body: "timed out" };
  while (Date.now() < end) {
    last = await check();
    if (last.ok) return last;
    if (await gone(unit(slot))) return { ok: false, body: `${unit(slot)} stopped: ${last.body}` };
    await Bun.sleep(Number(env.FM_DEPLOY_POLL_MS || 3000));
  }
  return last;
}

function install(slot: string) {
  const stage = `${DIR}/stage`;
  if (!existsSync(`${stage}/bridge.ts`)) throw new Error(`no staged build in ${stage}`);
  rmSync(`${DIR}/${slot}`, { recursive: true, force: true });
  cpSync(stage, `${DIR}/${slot}`, { recursive: true });
  symlinkSync("../node_modules", `${DIR}/${slot}/node_modules`);
}

// The files from before slots live in <dir> itself; keep a copy as the rollback target of the first rolling install.
function snapshotLegacy() {
  if (existsSync(`${DIR}/legacy/bridge.ts`)) return;
  mkdirSync(`${DIR}/legacy`, { recursive: true });
  for (const e of readdirSync(DIR, { withFileTypes: true })) {
    if (e.isFile() && /\.(ts|yml)$/.test(e.name)) cpSync(`${DIR}/${e.name}`, `${DIR}/legacy/${e.name}`);
    if (e.isDirectory() && e.name === "ste-vale") cpSync(`${DIR}/${e.name}`, `${DIR}/legacy/${e.name}`, { recursive: true });
  }
  symlinkSync("../node_modules", `${DIR}/legacy/node_modules`);
}

// Probe items a failed deploy left in the outbox would only confuse the next bridge.
function dropProbes() {
  const dir = `${STATE}/outbox`;
  if (!existsSync(dir)) return;
  for (const f of readdirSync(dir).filter((n) => n.endsWith(".json"))) {
    try { if (JSON.parse(readFileSync(`${dir}/${f}`, "utf8")).probe) unlinkSync(`${dir}/${f}`); } catch {}
  }
}

async function rollback(cur: string, target: string, why: string): Promise<never> {
  say(`FAILED: ${why}; rolling back to ${cur}`);
  await sc("stop", unit(target));
  setActive(STATE, cur);
  dropProbes();
  await sc("start", unit(cur));
  const back = await until(BACK_MS, () => get(PORT, "/health"), cur);
  await sc("start", FRONT);
  say(back.ok ? `${cur} serves again; the failed build is ${target}` : `${cur} did not answer /health after the rollback: ${back.body}`);
  process.exit(1);
}

async function deploy() {
  mkdirSync(STATE, { recursive: true, mode: 0o700 });
  const lock = await holdLock(`${STATE}/deploy.lock`, 900_000);
  if (!lock) throw new Error("another imessage-deploy holds the lock");
  const cur = readActive(STATE) ?? ((await legacyRunning()) ? "legacy" : undefined);
  const live = cur === "legacy" ? await legacyRunning() : cur ? await active(unit(cur)) : false;
  const target = cur === "blue" ? "green" : "blue";
  if (cur === "legacy") snapshotLegacy();
  await sc("stop", unit(target));
  install(target);
  say(`staged ${target}; serving slot: ${live ? cur : "none"}`);

  if (!live) { // nothing to protect: start the new slot as the owner
    if (cur) await sc("stop", unit(cur));
    setActive(STATE, target);
    await sc("start", unit(target));
    const up = await until(BACK_MS, () => get(PORT, "/health"), target);
    if (!up.ok) { await sc("stop", unit(target)); throw new Error(`${target} did not answer /health: ${up.body}`); }
    return finish(target);
  }

  setActive(STATE, cur!); // the new slot starts as standby
  await sc("start", unit(target));
  const gate = await until(GATE_MS, () => get(NEXT, "/ready"), target);
  if (!gate.ok) {
    await sc("stop", unit(target));
    say(`FAILED: health gate of ${target}: ${gate.body}; ${cur} was not touched`);
    process.exit(1);
  }
  say(`${target} passed the gate: ${gate.body}`);

  setActive(STATE, target); // the handover: the old slot stops, the new one takes the lock, the port and the outbox
  await sc("stop", unit(cur!));
  if (cur === "legacy") await sc("stop", FRONT);
  const own = await until(OWN_MS, () => get(PORT, "/health"), target);
  if (!own.ok) return rollback(cur!, target, `${target} did not take the line: ${own.body}`);
  const probe = await get(PORT, "/probe", "POST");
  if (!probe.ok) return rollback(cur!, target, `${target} probe: ${probe.body}`);
  say(`${target} confirmed one outbox pass`);
  await finish(target);
}

async function finish(target: string) {
  writeFileSync(`${STATE}/deployed.tmp`, await buildHash());
  renameSync(`${STATE}/deployed.tmp`, `${STATE}/deployed`);
  await sc("start", FRONT);
  say(`${target} serves the line`);
}

// What a deploy rolls out: the staged files and the rendered units. A failed deploy leaves the record unchanged,
// so the next apply sees the difference and tries again.
async function buildHash() {
  const hash = new Bun.CryptoHasher("sha256");
  const add = (dir: string, prefix = "") => {
    for (const e of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (e.isDirectory()) add(`${dir}/${e.name}`, `${prefix}${e.name}/`);
      else if (e.isFile()) hash.update(`${prefix}${e.name}\0`).update(readFileSync(`${dir}/${e.name}`));
    }
  };
  add(`${DIR}/stage`);
  const units = env.FM_DEPLOY_UNIT_DIR || `${env.HOME}/.config/systemd/user`;
  for (const f of ["fm-imessage.service", "fm-imessage@.service"]) if (existsSync(`${units}/${f}`)) hash.update(readFileSync(`${units}/${f}`));
  return hash.digest("hex");
}

async function needed() {
  const slot = readActive(STATE);
  const recorded = existsSync(`${STATE}/deployed`) ? readFileSync(`${STATE}/deployed`, "utf8").trim() : "";
  const same = slot && recorded === (await buildHash());
  say(same ? `${slot} runs the staged build` : "the staged build is not deployed yet");
  process.exit(same ? 0 : 3);
}

async function follow() {
  await boot();
  for (;;) {
    await Bun.sleep(Number(env.FM_DEPLOY_FOLLOW_MS || 5000));
    const lock = await holdLock(`${STATE}/deploy.lock`, 0);
    if (!lock) continue; // a deploy is moving the line
    lock.release();
    const slot = readActive(STATE);
    if (!slot || (await gone(unit(slot)))) throw new Error(`no slot serves the line (active: ${slot ?? "none"})`);
  }
}

async function boot() {
  const slot = readActive(STATE);
  if (!slot) return;
  const state = (await sc("show", unit(slot), "-p", "ActiveState", "--value")).out.split("\n")[0];
  if (state !== "failed" && state !== "inactive") return;
  if (state === "failed") await sc("reset-failed", unit(slot));
  await sc("start", unit(slot));
}

async function stopAll() {
  const lock = await holdLock(`${STATE}/deploy.lock`, 0);
  if (!lock) return; // a deploy is running and owns the units
  for (const slot of ["blue", "green", "legacy"]) await sc("stop", unit(slot));
  lock.release();
}

const mode = process.argv[2];
if (mode === "boot") await boot();
else if (mode === "follow") await follow().catch((e) => { say(e.message); process.exit(1); });
else if (mode === "needed") await needed();
else if (mode === "stop-all") await stopAll();
else if (mode === undefined) await deploy().then(() => process.exit(0), (e) => { say(`FAILED: ${e instanceof Error ? e.message : e}`); process.exit(1); });
else throw new Error("usage: imessage-deploy [needed|boot|follow|stop-all]");
