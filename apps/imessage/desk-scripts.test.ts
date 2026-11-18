import { afterAll, expect, test } from "bun:test";
import { chmodSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { listScripts, runScript, SCRIPT_OUTPUT_MAX } from "./desk-scripts.ts";

const dir = mkdtempSync(`${tmpdir()}/desk-scripts-`);
const outside = mkdtempSync(`${tmpdir()}/desk-outside-`);
afterAll(() => { rmSync(dir, { recursive: true }); rmSync(outside, { recursive: true }); });

function script(name: string, body: string, where = dir, mode = 0o755) {
  writeFileSync(`${where}/${name}`, `#!/bin/sh\n${body}\n`);
  chmodSync(`${where}/${name}`, mode);
}
const env = { PATH: process.env.PATH, HOME: "/nonexistent", FM_HOME: "/fleet" };

script("disk-report", "# Show the disk use.\necho \"home=$FM_HOME secret=$SECRET_TOKEN\"; echo oops >&2; exit 3");
script("rotate-login", "# Rotate things.\necho hi");
script("sync-notes", "# Log in to the account, then sync.\necho hi");
script("tweet-status", "echo hi");
script("not-executable", "echo hi", dir, 0o644);
script("secret-thing", "echo hi", outside);
symlinkSync(`${outside}/secret-thing`, `${dir}/linked`);

test("lists only scripts the desk may run, with their first header line", () => {
  expect(listScripts(dir)).toEqual(["disk-report: Show the disk use."]);
  expect(listScripts(`${dir}/missing`)).toEqual([]);
});

test("runs a script with a clean environment and captures stdout, stderr and the exit code", async () => {
  const run = await runScript(dir, "disk-report", { ...env, SECRET_TOKEN: "x" } as Record<string, string>);
  expect(run).toEqual({ code: 3, timedOut: false, output: "home=/fleet secret=\noops\n" });
});

test("refuses a script about credentials, payments or public posts, a symlink, a non-executable file and a path", async () => {
  for (const [name, why] of [
    ["rotate-login", "credentials or logins"], ["sync-notes", "credentials or logins"], ["tweet-status", "public posts"],
    ["linked", "not an executable file"], ["not-executable", "not an executable file"], ["../x", "not a script name"], ["ghost", "no such script"],
  ]) await expect(runScript(dir, name!, env)).rejects.toThrow(`refused: ${name}: ${name === "../x" || name === "ghost" || name === "linked" || name === "not-executable" ? why : `it concerns ${why}`}`);
});

test("kills a script that outlives the timeout, children included", async () => {
  script("slow-job", "# Wait.\nsleep 30 &\nsleep 30");
  const start = Date.now();
  const run = await runScript(dir, "slow-job", env, 300);
  expect(run.timedOut).toBe(true);
  expect(run.code).toBeNull();
  expect(Date.now() - start).toBeLessThan(5000);
});

test("returns only the head of a long output and stops the script", async () => {
  script("chatty", "# Print a lot.\nyes aaaaaaaaaaaaaaaa");
  const run = await runScript(dir, "chatty", env);
  expect(run.output.length).toBe(SCRIPT_OUTPUT_MAX);
  expect(run.timedOut).toBe(false);
});
