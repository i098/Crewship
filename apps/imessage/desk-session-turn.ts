// One turn of the desk's long chat: the bridge's checks, the child's start, and the prompt it gets.
// The bridge passes its effects in (SessionHost); a turn that ends with no action gets one reminder, then its words go out as the reply or the text goes to Firstmate.
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { ACK_GUID_PREFIX, createActions, HOST_TOOLS, sessionPrompt, TASK_GUID_PREFIX, turnMessage } from "./desk-actions.ts";
import { createDelegator, WAIT_MS } from "./desk-delegate.ts";
import { DeskSession, sessionConfig, type PromptResult, type ToolRunner } from "./desk-session.ts";
import { mateStatusLines, modelArg, secondmates, supervisorOnly, writeDeskSecrets, type Secondmate } from "./desk.ts";
import type { Memory } from "./memory.ts";
import { deskMayAct, type RelayRequest } from "./relay.ts";

export { ACK_GUID_PREFIX, TASK_GUID_PREFIX };

type SessionEnv = Record<string, string | undefined>;

// The text goes to Firstmate first; the ack, when given, is a plain desk text with no task behind it.
function handoffWithAck<R extends TurnRequest>(host: SessionHost<R>, pending: R[], reason: string, ack?: { parts: string[]; target: number }) {
  if (reason) host.log("desk handoff")(reason);
  host.handoff(pending);
  if (ack) host.report(ack.parts, `${ACK_GUID_PREFIX}${crypto.randomUUID()}`, pending[ack.target - 1]!);
}

// A thread reply to a mate's bubble goes back to that mate, with the same relay checks.
function threadReplyMate(pending: TurnRequest[], mates: Secondmate[]) {
  const replied = mates.find((m) => m.id === pending[0]!.threadMate);
  return replied && pending.every((r) => r.threadMate === replied.id) ? replied : undefined;
}

export type TurnRequest = RelayRequest & { memoryId: number; route: string; threadMate?: string };

type TurnParts<R extends TurnRequest> = { pending: R[]; current: () => boolean; actions: { run: ToolRunner; acted(): boolean } };

export type SessionHost<R extends TurnRequest> = {
  env: SessionEnv;
  provider: string;
  model: string;
  reasoning: string;
  supervisorModel: string;
  vetted: boolean;
  stateDir: string;
  memoryDir: string;
  fmHome: string;
  memory: Pick<Memory, "msgs" | "render">;
  memoryIndex(request: R): number;
  safe: ((text: string) => string) | undefined; // the redacting text filter; none means the desk may not act
  muted(): boolean;
  track<T extends Bun.Subprocess>(proc: T): T;
  log(what: string): (error: unknown) => void;
  handoff(pending: R[]): void;
  answer(pending: R[], parts: string[], target: R, delegated?: true): void; // delegated: a background task already holds the text, so a lost ack must not hand it off again
  react(pending: R[], emoji: string): void;
  relay(items: R[], mate: Secondmate, current: () => boolean): Promise<void>;
  inbox(): Promise<{ status: string; statusOk: boolean }>;
  stopping(): boolean;
  listed(mate: Secondmate): boolean; // the mate is still in the routing table
  send(target: Secondmate | "firstmate", id: string, text: string): Promise<boolean>; // true when the target's inbox took a background task
  message(mate: Secondmate, text: string): Promise<boolean>; // the desk's own text to a mate; true when the mate's inbox took it
  claim(key: string | undefined, text: string): boolean; // sender log of texts to the owner (sender-log.ts)
  report(parts: string[], guid: string, origin: R): void; // a text queued on the chat of the request: a background task's answer, or the ack of a handoff
};

// The newest status lines of a mate: where a marked reply returns to the desk's home.
function readStatusTail(home: string, id: string) {
  try { return readFileSync(`${home}/state/${id}.status`, "utf8").trimEnd().split("\n").slice(-5).map((l) => l.slice(0, 300)).join("\n"); } catch { return ""; }
}

// omp wants provider/model-id for the compaction key.
const thresholdKeyOf = (provider: string, model: string) => `${provider === "inception" ? "inception" : "anthropic"}/${model}`;

const RETRY_MESSAGE = "You ended your turn without an action tool. Send your answer to the owner with the reply tool now (or use another action tool).";

// What the session already has: its own desk replies and this burst's texts. A background task's answer is news to it.
const seenInTurn = (m: { kind: string; requestId?: string }, ids: Set<string>) =>
  (m.kind === "desk" && !m.requestId?.startsWith(`outbox-text-${TASK_GUID_PREFIX}`)) || (!!m.requestId && ids.has(m.requestId));

const mask = (text: string, safe: (text: string) => string) => (supervisorOnly(text) || safe(text) !== text ? "Protected context requires Firstmate." : text);

function childEnv(env: SessionEnv, inception: boolean): SessionEnv {
  const keys = inception ? ["INCEPTION_API_KEY"] : ["ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_BASE_URL"];
  return Object.fromEntries(["HOME", "USER", "LANG", "TMPDIR", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "PI_CODING_AGENT_DIR", "OMP_PROFILE", "FM_HOME", "FAKE_DIR", "PATH", ...keys]
    .map((key) => [key, env[key]]));
}

function startSession<R extends TurnRequest>(host: SessionHost<R>): DeskSession {
  const { env } = host;
  const dir = `${host.stateDir}/desk-session`;
  const inception = host.provider === "inception";
  const model = modelArg(host.provider, host.model); // as the one-shot desk: omp resolves a bare id's provider
  const instant = inception && host.reasoning === "instant"; // an env hook sends instant; omp's --thinking has no such level
  const cwd = `${dir}/cwd`; // empty cwd: no project context files load
  rmSync(cwd, { recursive: true, force: true });
  mkdirSync(cwd, { recursive: true, mode: 0o700 });
  writeDeskSecrets(cwd, env);
  const config = `${cwd}/session-config.json`;
  writeFileSync(config, sessionConfig(thresholdKeyOf(host.provider, host.model), HOST_TOOLS), { mode: 0o600 });
  return new DeskSession({
    argv: ["omp", "--mode", "rpc", "--no-ui", "--no-extensions", "-e", `${import.meta.dir}/zoom.ts`,
      "--tools=read,grep,glob,bash,zoom", "--config", `${import.meta.dir}/desk-tools.yml`, "--config", config, "--approval-mode=write",
      "--no-skills", "--no-rules", "--no-context-files", "--no-title", `--thinking=${instant ? "off" : host.reasoning}`, "--model", model,
      "--session-dir", `${dir}/sessions`, "--continue", "--system-prompt", sessionPrompt(env.FM_IMESSAGE_OWNER_NAME || "the owner", host.model, host.supervisorModel)],
    cwd, sessionDir: `${dir}/sessions`, model, tools: HOST_TOOLS, track: host.track, log: host.log("desk session"),
    env: { ...childEnv(env, inception), FM_DESK_MEMORY: host.memoryDir, FM_DESK_SESSION: "1", FM_DESK_INCEPTION_INSTANT: instant ? "1" : undefined, OMP_SKIP_SETUP: "1" },
  });
}

export function createSessionTurn<R extends TurnRequest>(host: SessionHost<R>) {
  const seenPath = `${host.stateDir}/desk-session.seen`; // memory messages the session has been shown, as a count
  let child: DeskSession | undefined;
  const delegate = createDelegator<R>({
    answerDir: `${host.stateDir}/desk-tasks`, waitMs: WAIT_MS, pollMs: 500,
    stopping: host.stopping, muted: host.muted, log: host.log("desk task"), safe: (text) => host.safe!(text), // a turn runs only with the filter
    listed: host.listed, send: host.send, report: host.report,
  });
  const session = () => (child ??= startSession(host));

  const seen = (): number => {
    try { return Number(readFileSync(seenPath, "utf8")) || 0; } catch { return 0; }
  };

  const refused = (pending: R[], original: string[]) => !host.vetted || host.muted() || !host.safe || pending.some((r) => r.mutationPath)
    || !deskMayAct(pending) || original.some((text) => host.safe!(text) !== text);

  function missedLines(ids: Set<string>, last: number, safe: (text: string) => string) {
    return host.memory.msgs.slice(Math.min(seen(), last + 1), last + 1)
      .filter((m) => !seenInTurn(m, ids))
      .map(({ kind, text }) => ({ kind, text: mask(text, safe) }));
  }

  // The prompt of one turn: the memory view for a new or compacted session, else what the session missed, then the burst.
  function message(pending: R[], original: string[], safe: (text: string) => string, seed: boolean) {
    const indexes = pending.map((r) => host.memoryIndex(r));
    const last = Math.max(...indexes);
    const missed = seed ? [] : missedLines(new Set(pending.map((r) => r.requestId)), last, safe);
    writeFileSync(seenPath, String(last + 1));
    return turnMessage({ view: seed ? host.memory.render(Math.min(...indexes)) : undefined, missed, burst: original });
  }

  // The session reads, then ends in one bridge-checked action. No action hands the burst to Firstmate.
  return async function runSessionTurn(pending: R[], controller: AbortController, current: () => boolean) {
    if (!current()) return;
    const original = pending.map((r) => r.authored ?? r.text);
    if (refused(pending, original)) return host.handoff(pending);
    const safe = host.safe!;
    const mates = secondmates(host.fmHome);
    const replied = threadReplyMate(pending, mates);
    if (replied) return host.relay(pending.filter((r) => r.route === "pending"), replied, current); // a failed delivery stays in routing for retry
    const actions = createActions({
      requests: pending, current, muted: host.muted, mates: () => mates, safe, message: host.message, claim: host.claim,
      replies: (mate) => safe(readStatusTail(host.fmHome, mate.id)),
      reply: (parts, target) => host.answer(pending, parts, pending[target - 1]),
      react: (emoji) => host.react(pending, emoji),
      relay: async (mate) => {
        const items = pending.filter((r) => r.route === "pending");
        await host.relay(items, mate, current);
        return items.every((r) => r.route === "done");
      },
      handoff: (reason, ack) => handoffWithAck(host, pending, reason, ack),
      delegate: (mate, parts, target) => {
        host.answer(pending, parts, pending[target - 1], true);
        delegate(mate, original.join("\n"), pending.at(-1)!);
      },
      status: async () => {
        const inbox = await host.inbox();
        if (!inbox.statusOk) throw new Error("fleet status is unavailable; call handoff_main");
        const roster = mates.map(({ id, scope }) => `mate ${id}: ${scope}`).join("\n"); // the only place the session learns the mate ids
        return safe(`${inbox.status}\n${roster}\n${mateStatusLines(host.fmHome, mates)}`);
      },
    });
    const first = await session().ask((seed) => message(pending, original, safe, seed), controller.signal, actions.run);
    if (!current() || actions.acted()) return;
    const remind = () => session().ask((seed) => seed ? `${message(pending, original, safe, true)}\n\n${RETRY_MESSAGE}` : RETRY_MESSAGE, controller.signal, actions.run);
    await noAction(host, { pending, current, actions }, first, remind);
  };
}

// omp RPC cannot force a tool call, so a model that answered in words gets one reminder, then the words of the last prompt go out as the reply.
async function noAction<R extends TurnRequest>(host: SessionHost<R>, t: TurnParts<R>, first: PromptResult, remind: () => Promise<PromptResult>) {
  const log = host.log("desk session");
  log(new Error(`turn ended with no action (${[first.status, first.error].filter(Boolean).join(": ")}); asking once more`));
  const result = first.status === "completed" ? await remind() : first;
  if (!t.current() || t.actions.acted()) return;
  if (result.status === "completed" && result.text) {
    try {
      await t.actions.run("reply", { text: result.text }); // the same checks as the reply tool
      return;
    } catch (error) { log(error); }
  }
  host.handoff(t.pending);
}
