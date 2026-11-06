import { expect, test } from "bun:test";
import { rmSync } from "node:fs";
import type { DeskProc } from "./desk.ts";
import { createHelper, helperEnv, helperKind, helperMayAct, HELPER_TOOLS, spawnHelper } from "./desk-helper.ts";

const proc = (out: string, code = 0) => ({ stdout: new Blob([out]), exited: Promise.resolve(code) }) as unknown as DeskProc;
const answer = (text: string) => `${JSON.stringify({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text }] } })}\n`;

test("the helper is busy while it runs, answers with its last message, and frees itself", async () => {
  const gate = Promise.withResolvers<void>();
  const helper = createHelper(() => ({ stdout: new Blob([answer("Done.")]), exited: gate.promise.then(() => 0) }) as unknown as DeskProc);
  const running = helper.run("install it", "install");
  expect(helper.busy()).toBe(true);
  gate.resolve();
  expect(await running).toBe("Done.");
  expect(helper.busy()).toBe(false);
});

test("a failed run gives no answer and frees the helper", async () => {
  const failed = createHelper(() => proc(answer("half"), 1));
  expect(await failed.run("x", "lookup")).toBeUndefined();
  expect(failed.busy()).toBe(false);
  const broken = createHelper(() => { throw new Error("no omp"); });
  await expect(broken.run("x", "lookup")).rejects.toThrow("no omp");
  expect(broken.busy()).toBe(false);
});

test("only an install, lookup or read-link ask may go to a helper", () => {
  const ask = (text: string) => [{ requestId: "r", text, mateEligible: true, firstmate: false }];
  expect(helperMayAct(ask("install the ripgrep skill"), "install")).toBe(true);
  expect(helperMayAct(ask("what is the latest bun version?"), "lookup")).toBe(true);
  expect(helperMayAct(ask("read https://example.com/a"), "read-link")).toBe(true);
  expect(helperMayAct(ask("install the ripgrep skill"), undefined)).toBe(false);
  for (const text of ["deploy it", "which option should we take", "buy a domain", "pay the invoice", "tweet the launch", "delete the old skill",
    "posting the update", "share the launch on LinkedIn", "email the vendor", "reply on the GitHub issue", "send her the file"]) expect(helperMayAct(ask(text), "install")).toBe(false);
});

test("a target names a helper kind only when the kind is listed", () => {
  expect(helperKind("helper:install")).toBe("install");
  expect(helperKind("helper:read-link")).toBe("read-link");
  for (const target of ["helper", "helper:", "helper:other", "helper:constructor", "firstmate", "mate1"]) expect(helperKind(target)).toBeUndefined();
});

test("only an install helper gets bash and write is never given", () => {
  expect(HELPER_TOOLS.install.split(",")).toContain("bash");
  for (const kind of ["lookup", "read-link"] as const) expect(HELPER_TOOLS[kind].split(",")).not.toContain("bash");
  for (const tools of Object.values(HELPER_TOOLS)) expect(tools.split(",")).not.toContain("write");
});

test("the helper environment is PATH, HOME and the model's own key only", () => {
  const env = helperEnv({ HOME: "/h", PATH: "/bin", FM_HOME: "/fm", INCEPTION_API_KEY: "k", OPENAI_API_KEY: "o", ANTHROPIC_API_KEY: "a", FM_IMESSAGE_OWNER: "+1", SUPER_ENV: "x", LANG: "C" });
  expect(Object.keys(env).sort()).toEqual(["ANTHROPIC_API_KEY", "HOME", "INCEPTION_API_KEY", "PATH"]);
});

test("a spawned helper gets the kind's tools and the narrow environment", () => {
  const spawned: { argv: string[]; env: Record<string, string> }[] = [];
  const real = Bun.spawn;
  const dir = `${process.env.TMPDIR ?? "/tmp"}/helper-spawn-${crypto.randomUUID()}`;
  (Bun as { spawn: unknown }).spawn = (argv: string[], o: { env: Record<string, string> }) => (spawned.push({ argv, env: o.env }), { exited: Promise.resolve(0), stdout: new Blob([]) });
  try {
    for (const kind of ["install", "lookup"] as const) {
      spawnHelper({ model: "m", reasoning: "low", thresholdKey: "anthropic/m", owner: "o", dir, kind, track: (p) => p,
        env: { HOME: "/h", PATH: "/bin", FM_HOME: "/fm", OPENAI_API_KEY: "o", ANTHROPIC_API_KEY: "a" } }, "task");
    }
  } finally { (Bun as { spawn: unknown }).spawn = real; rmSync(dir, { recursive: true, force: true }); }
  expect(spawned.map((s) => s.argv.find((a) => a.startsWith("--tools=")))).toEqual([`--tools=${HELPER_TOOLS.install}`, `--tools=${HELPER_TOOLS.lookup}`]);
  for (const { env } of spawned) expect(Object.keys(env).sort()).toEqual(["ANTHROPIC_API_KEY", "HOME", "OMP_SKIP_SETUP", "PATH"]);
});
