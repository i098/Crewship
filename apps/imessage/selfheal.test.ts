import { expect, test } from "bun:test";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { bridgeNatives, loadState, markHealthy, onStart, Turns } from "./selfheal.ts";

// A fake omp that prints a version but unpacks no natives, so every start fails its natives check.
const withHome = async (run: (env: Record<string, string>, dir: string) => Promise<void>) => {
  const dir = mkdtempSync(join(process.env.TMPDIR ?? "/tmp", "selfheal-"));
  writeFileSync(`${dir}/omp`, "#!/bin/sh\necho omp/0.0.1\n");
  chmodSync(`${dir}/omp`, 0o755);
  const env = { PATH: process.env.PATH ?? "", HOME: dir, TMPDIR: dir, STATE_DIRECTORY: `${dir}/state`, FM_IMESSAGE_OMP: `${dir}/omp`,
    FM_IMESSAGE_SEND: "false", FM_IMESSAGE_PORT: "1", FM_IMESSAGE_ALERT_STATUS: `${dir}/alerts.status` };
  try { await run(env, dir); } finally { rmSync(dir, { recursive: true, force: true }); }
};

test("the owner is alerted once, on the second failed heal in a row", () => withHome(async (env, dir) => {
  await expect(onStart(env)).rejects.toThrow();
  expect(existsSync(`${dir}/alerts.status`)).toBe(false);
  await expect(onStart(env)).rejects.toThrow();
  await expect(onStart(env)).rejects.toThrow();
  const lines = readFileSync(`${dir}/alerts.status`, "utf8").trim().split("\n");
  expect(lines).toHaveLength(1);
  expect(lines[0]).toMatch(/^failed \[at=\d+\]: iMessage self-heal failed 2 times/);
}));

test("the alert through the real fm-imessage falls back to the status line at once while the bridge refuses connections", () => withHome(async (env, dir) => {
  const down = { ...env, FM_IMESSAGE_SEND: `${import.meta.dir}/fm-imessage` };
  const started = Date.now();
  await expect(onStart(down)).rejects.toThrow();
  await expect(onStart(down)).rejects.toThrow();
  expect(Date.now() - started).toBeLessThan(10_000);
  expect(readFileSync(`${dir}/alerts.status`, "utf8")).toMatch(/^failed \[at=\d+\]: iMessage self-heal failed 2 times/);
}));

test("a healthy beat clears the failure count so the next failure alerts again", () => withHome(async (env, dir) => {
  await expect(onStart(env)).rejects.toThrow();
  markHealthy(env);
  expect(loadState(env)).toEqual({ pending: false, fails: 0, alerted: false });
  await expect(onStart(env)).rejects.toThrow();
  expect(existsSync(`${dir}/alerts.status`)).toBe(false);
}));

test("the oldest running turn sets the stuck age and a finished turn leaves it", () => {
  const turns = new Turns();
  expect(turns.oldestMs()).toBe(0);
  const first = turns.begin();
  const second = turns.begin();
  expect(turns.oldestMs(Date.now() + 5000)).toBeGreaterThanOrEqual(5000);
  first();
  second();
  expect(turns.oldestMs()).toBe(0);
});

test("a healthy bridge gets no alert and its failure count is cleared", () => withHome(async (env, dir) => {
  const server = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response("ok\n") });
  try {
    const live = { ...env, FM_IMESSAGE_PORT: String(server.port) };
    await expect(onStart(live)).rejects.toThrow();
    await expect(onStart(live)).rejects.toThrow();
    expect(existsSync(`${dir}/alerts.status`)).toBe(false);
    expect(loadState(live).fails).toBe(0);
  } finally { server.stop(true); }
}));

// A fake omp install whose pi-natives throws on import until native/a.node exists; the platform package holds a.node.
const withInstall = async (platformHasNode: boolean, run: (env: Record<string, string>, native: string) => Promise<void>) => {
  const dir = mkdtempSync(join(process.env.TMPDIR ?? "/tmp", "selfheal-bridge-"));
  const pkg = `${dir}/node_modules/@oh-my-pi/pi-natives`;
  const platform = `${dir}/node_modules/@oh-my-pi/pi-natives-${process.platform}-${process.arch}`;
  mkdirSync(`${pkg}/native`, { recursive: true });
  mkdirSync(platform, { recursive: true });
  writeFileSync(`${pkg}/package.json`, JSON.stringify({ name: "@oh-my-pi/pi-natives", type: "module", main: "./native/index.js" }));
  writeFileSync(`${pkg}/native/index.js`, `import { accessSync } from "node:fs";\naccessSync(new URL("./a.node", import.meta.url));\n`);
  if (platformHasNode) writeFileSync(`${platform}/a.node`, "x");
  writeFileSync(`${dir}/omp`, "#!/bin/sh\n");
  chmodSync(`${dir}/omp`, 0o755);
  try { await run({ PATH: process.env.PATH ?? "", FM_IMESSAGE_OMP: `${dir}/omp` }, `${pkg}/native`); } finally { rmSync(dir, { recursive: true, force: true }); }
};

test("a pi-natives install with its .node missing is repaired from the platform package and then loads", () => withInstall(true, async (env, native) => {
  expect(existsSync(`${native}/a.node`)).toBe(false);
  expect(await bridgeNatives(env)).toBe("repaired");
  expect(existsSync(`${native}/a.node`)).toBe(true);
  expect(await bridgeNatives(env)).toBe("ok");
}));

test("a pi-natives install that cannot be repaired fails, so the start exits non-zero", () => withInstall(false, async (env) => {
  await expect(bridgeNatives(env)).rejects.toThrow(/no \.node to copy/);
}));
