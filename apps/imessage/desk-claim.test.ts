import { afterAll, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { claim } from "./desk-claim.ts";
import { createActions, type ActionHost } from "./desk-actions.ts";
import type { RelayRequest } from "./relay.ts";

const tmp = mkdtempSync(`${tmpdir()}/desk-claim-`);
afterAll(() => rmSync(tmp, { recursive: true, force: true }));
const skills = `${tmp}/skills`;
const files = `${tmp}/files`;
mkdirSync(skills, { recursive: true });
mkdirSync(files, { recursive: true });

const ask = (text: string, id = `r-${text}`): RelayRequest => ({ requestId: id, text, mateEligible: true, firstmate: false });

function desk(dir: string, texts: string[], over: Partial<ActionHost> = {}) {
  const sent: string[] = [];
  const host = {
    requests: texts.map((t) => ask(t, "m1")), current: () => true, muted: () => false, mates: () => [],
    safe: (text: string) => text.replaceAll("hunter2", "[REDACTED]"), remember: () => {},
    roots: { write: [skills, files], read: [skills, files] },
    claim: (kind, key, actor) => claim(dir, kind, key, actor),
    sendImage: async (_b, name) => void sent.push(name),
    handoff: () => {},
    ...over,
  } as ActionHost;
  return { sent, ...createActions(host) };
}

test("the desk and the supervisor get one text and only one acts", async () => {
  const dir = `${tmp}/c1`;
  const a = desk(dir, ["save the notes as a skill"]);
  const proc = Bun.spawnSync(["bun", `${import.meta.dir}/desk-claim.ts`, "msg", "m1"], { env: { ...process.env, FM_IMESSAGE_CLAIMS: dir } });
  expect(proc.exitCode).toBe(0); // the supervisor got there first
  await expect(a.run("write_file", { path: `${skills}/notes/SKILL.md`, content: "# notes" })).rejects.toThrow("another actor");
  expect(await Bun.file(`${skills}/notes/SKILL.md`).exists()).toBe(false);
}, 60_000);

test("the desk acts first, then the supervisor and a handoff are refused", async () => {
  const dir = `${tmp}/c2`;
  const a = desk(dir, ["save the notes as a skill"]);
  await a.run("write_file", { path: `${skills}/two/SKILL.md`, content: "# two" });
  expect(Bun.spawnSync(["bun", `${import.meta.dir}/desk-claim.ts`, "msg", "m1"], { env: { ...process.env, FM_IMESSAGE_CLAIMS: dir } }).exitCode).toBe(3);
  await expect(a.run("handoff_main", {})).rejects.toThrow("already acted");
}, 60_000);

test("a second desk turn or a restart cannot repeat an action", async () => {
  const dir = `${tmp}/c3`;
  await desk(dir, ["send it"]).run("write_file", { path: `${files}/a.txt`, content: "x" });
  const again = desk(dir, ["send it"]); // a new runner over the same claim directory, as after a restart
  await expect(again.run("write_file", { path: `${files}/a.txt`, content: "x" })).rejects.toThrow("another actor or an earlier call");
}, 60_000);

test("a handoff to the supervisor shuts the desk out", async () => {
  const dir = `${tmp}/c4`;
  await desk(dir, ["save the notes"]).run("handoff_main", {});
  await expect(desk(dir, ["save the notes"]).run("write_file", { path: `${files}/b.txt`, content: "x" })).rejects.toThrow("another actor");
}, 60_000);

test("claim races have one winner", async () => {
  const wins = await Promise.all(Array.from({ length: 20 }, () => Promise.resolve().then(() => claim(`${tmp}/c5`, "act", "k", "desk"))));
  expect(wins.filter(Boolean).length).toBe(1);
}, 60_000);

// One test per standing limit.
test("limit: no write outside the allowed folders, into a git checkout, or through a symlink", async () => {
  const a = desk(`${tmp}/l1`, ["save it"]);
  await expect(a.run("write_file", { path: "/etc/x.txt", content: "x" })).rejects.toThrow("outside the allowed");
  await expect(a.run("write_file", { path: `${skills}/../x.txt`, content: "x" })).rejects.toThrow("outside the allowed");
  mkdirSync(`${tmp}/repo/.git`, { recursive: true });
  symlinkSync(`${tmp}/repo`, `${skills}/link`);
  await expect(a.run("write_file", { path: `${skills}/link/f.txt`, content: "x" })).rejects.toThrow("leaves the allowed");
  mkdirSync(`${skills}/proj/.git`, { recursive: true });
  await expect(a.run("write_file", { path: `${skills}/proj/f.txt`, content: "x" })).rejects.toThrow("git checkout");
}, 60_000);

test("limit: no credential file and no secret content", async () => {
  const a = desk(`${tmp}/l2`, ["save it"]);
  await expect(a.run("write_file", { path: `${skills}/.env`, content: "x" })).rejects.toThrow("credential file");
  await expect(a.run("write_file", { path: `${files}/id_rsa`, content: "x" })).rejects.toThrow("credential file");
  await expect(a.run("write_file", { path: `${files}/n.txt`, content: "the password is hunter2" })).rejects.toThrow("protected content");
  writeFileSync(`${files}/shot.png`, "x");
  await expect(a.run("send_file", { path: `${files}/.ssh/shot.png` })).rejects.toThrow("credential file");
}, 60_000);

test("limit: no spend, public post, rotation or merge tool exists, and such a file name is refused", async () => {
  const a = desk(`${tmp}/l3`, ["save it"]);
  for (const tool of ["merge_pr", "pay", "post_public", "rotate_key", "bash", "shell"]) await expect(a.run(tool, {})).rejects.toThrow("unknown tool");
  await expect(a.run("write_file", { path: `${files}/pay-invoice.sh`, content: "x" })).rejects.toThrow("payments or purchases");
  await expect(a.run("write_file", { path: `${files}/post-to-twitter.md`, content: "x" })).rejects.toThrow("public posts");
  await expect(a.run("write_file", { path: `${files}/rotate-token.md`, content: "x" })).rejects.toThrow("credential");
}, 60_000);

test("limit: text from a link or mail never orders a write: a protected request is refused", async () => {
  const a = desk(`${tmp}/l4`, ["approve the deploy"]);
  await expect(a.run("write_file", { path: `${files}/c.txt`, content: "x" })).rejects.toThrow("protected");
  await expect(a.run("send_file", { path: `${files}/shot.png` })).rejects.toThrow("protected");
}, 60_000);

test("send_file sends a png once and refuses other types", async () => {
  const a = desk(`${tmp}/l5`, ["show me"]);
  writeFileSync(`${files}/shot.png`, "x");
  writeFileSync(`${files}/doc.pdf`, "x");
  await expect(a.run("send_file", { path: `${files}/doc.pdf` })).rejects.toThrow("images only");
  expect(await a.run("send_file", { path: `${files}/shot.png` })).toBe("sent shot.png");
  await expect(a.run("send_file", { path: `${files}/shot.png` })).rejects.toThrow("another actor or an earlier call");
  expect(a.sent).toEqual(["shot.png"]);
}, 60_000);
