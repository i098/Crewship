import { afterAll, expect, test } from "bun:test";
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// cron runs with PATH=/usr/bin:/bin, where `command -v bun` finds nothing. The filter must still run.
const seen: string[] = [];
const server = Bun.serve({ port: 0, hostname: "127.0.0.1", async fetch(req) {
  seen.push(await req.text());
  return new Response("queued 1 bubble(s)\n");
} });
const tmp = mkdtempSync(join(tmpdir(), "fm-imessage-bun-"));
afterAll(() => { server.stop(true); rmSync(tmp, { recursive: true, force: true }); });

// A fake bun that marks its input proves the filter ran without needing the real bun.
function fakeBun(dir: string) {
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "bun"), '#!/bin/bash\nprintf "filtered:"; cat\n');
  chmodSync(join(dir, "bun"), 0o755);
}

async function send(script: string, home: string) {
  const run = Bun.spawn([script, "hello"], {
    env: { PATH: "/usr/bin:/bin", HOME: home, FM_IMESSAGE_PORT: String(server.port), FM_IMESSAGE_WAIT_S: "0" }, stdout: "pipe", stderr: "pipe" });
  expect(await run.exited).toBe(0);
  return await new Response(run.stderr).text();
}

function installScript(dir: string) {
  mkdirSync(dir, { recursive: true });
  for (const f of ["fm-imessage", "clean.ts"]) copyFileSync(join(import.meta.dir, f), join(dir, f));
  return join(dir, "fm-imessage");
}

test("fm-imessage finds bun beside the script when PATH has none", async () => {
  const dir = join(tmp, "beside");
  const script = installScript(dir);
  fakeBun(dir);
  seen.length = 0;
  expect(await send(script, join(tmp, "nohome"))).not.toContain("unfiltered");
  expect(seen).toEqual(["filtered:hello"]);
});

test("fm-imessage finds bun in ~/.local/bin when PATH has none", async () => {
  const script = installScript(join(tmp, "plain"));
  const home = join(tmp, "home");
  fakeBun(join(home, ".local", "bin"));
  seen.length = 0;
  expect(await send(script, home)).not.toContain("unfiltered");
  expect(seen).toEqual(["filtered:hello"]);
});

test("fm-imessage still sends unfiltered with a warning when no bun exists", async () => {
  const script = installScript(join(tmp, "none"));
  seen.length = 0;
  expect(await send(script, join(tmp, "nohome"))).toContain("unfiltered");
  expect(seen).toEqual(["hello"]);
});
