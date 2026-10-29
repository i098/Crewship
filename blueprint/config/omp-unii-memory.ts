// UniiChat memory for a second mate's primary session, kept outside the omp session file so compaction
// (snapcompact included) cannot lose it. Reuses code-factory's apps/imessage/memory.ts for the log and the
// summary tree. Each user and assistant turn is appended to <home>/state/unii/<session id>/; after a compaction the next turn
// gets the view (summaries over the whole chat) as a hidden message, and unii_zoom opens any line.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";

// Crewship installs apps/imessage/memory.ts next to this file; UNII_MEMORY_TS overrides the location.
const MEMORY_TS = process.env.UNII_MEMORY_TS || new URL("./fm-unii-memory/memory.ts", import.meta.url).pathname;
const { Memory, zoom } = await import(MEMORY_TS);

const home = process.env.FM_HOME || homedir();
const ROOT_DIR = process.env.UNII_DIR || `${home}/state/unii`;
const MODEL = process.env.UNII_MODEL || "anthropic/claude-haiku-5-5";
const VIEW_TAG = "unii-view";

// One summary conversation: a child omp with no extensions or tools, so it cannot recurse into this file.
function haikuChat(system: string) {
  const dir = mkdtempSync(`${tmpdir()}/unii-compact-`);
  writeFileSync(`${dir}/config.yml`, "memory:\n  backend: off\n", { mode: 0o600 });
  let turns = 0;
  return {
    say: (text: string) => new Promise<string>((ok, fail) => {
      const p = spawn("omp", ["-p", "--no-extensions", "--no-tools", "--no-skills", "--no-rules", "--config", `${dir}/config.yml`,
        "--session-dir", dir, ...(turns++ ? ["--continue"] : []), "--thinking=off", "--model", MODEL, "--system-prompt", system],
        { cwd: dir, stdio: ["pipe", "pipe", "ignore"], timeout: 60_000 });
      let out = "";
      p.stdout.on("data", (d) => (out += d));
      p.on("error", fail);
      p.on("close", (code) => {
        const line = out.replace(/^Working\.\.\.\s*/m, "").trim();
        code === 0 && line ? ok(line) : fail(new Error(`compaction call failed (exit ${code})`));
      });
      p.stdin.end(text);
    }),
    end: () => rmSync(dir, { recursive: true, force: true }),
  };
}

const textOf = (c: unknown): string =>
  typeof c === "string" ? c : Array.isArray(c) ? c.filter((b) => b?.type === "text").map((b) => b.text).join("\n") : "";

export default function (pi: any) {
  let mem: any;
  let dir = `${ROOT_DIR}/main`; // memory.ts is the one writer of a directory, so each session gets its own
  let pending = false; // a compaction happened and the view is not in the session yet
  const get = () => (mem ??= new Memory(dir, haikuChat, (e: unknown) => console.error("[unii]", e)));

  pi.on("session_start", (_e: any, ctx: any) => {
    if (ctx.agent?.kind === "sub") return;
    dir = `${ROOT_DIR}/${ctx.sessionManager.getSessionId()}`;
    get();
    // After a relaunch: a compaction with no view message after it still owes the view.
    for (const en of ctx.sessionManager.getBranch()) {
      if (en.type === "compaction") pending = true;
      else if (en.type === "custom_message" && en.customType === VIEW_TAG) pending = false;
    }
  });

  pi.on("message_end", (e: any, ctx: any) => {
    if (ctx.agent?.kind === "sub" || !mem) return;
    const m = e.message;
    const text = (m?.role === "user" || m?.role === "assistant") ? textOf(m.content).trim() : "";
    if (text) mem.append(m.role === "user" ? "owner" : "desk", text);
  });

  pi.on("session_compact", () => { pending = true; });

  pi.on("before_agent_start", (_e: any, ctx: any) => {
    if (!pending || ctx.agent?.kind === "sub" || !mem?.msgs.length) return;
    pending = false;
    return {
      message: {
        customType: VIEW_TAG,
        display: false,
        content: `Conversation memory (survives compaction), one line per span as "id+n|summary", old spans coarse, recent fine. Open a line with unii_zoom(id, n).\n${mem.render()}`,
      },
    };
  });

  pi.registerTool({
    name: "unii_zoom",
    label: "Unii zoom",
    description: "Open a line id+n of the conversation memory into the two lines under it, or for n=1 the message whole.",
    parameters: pi.zod.object({ id: pi.zod.number().int(), n: pi.zod.number().int() }),
    async execute(_id: string, p: { id: number; n: number }) {
      const m = get();
      return { content: [{ type: "text", text: zoom(m.msgs, m.nodes, p.id, p.n) }], details: {} };
    },
  });
}
