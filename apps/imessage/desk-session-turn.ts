// One turn of the desk's long chat: the bridge's checks, the child's start, and the prompt it gets.
// The bridge passes its effects in (SessionHost); a turn that ends with no action goes to Firstmate.
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createActions, HOST_TOOLS, sessionPrompt, turnMessage } from "./desk-actions.ts";
import { DeskSession, sessionConfig } from "./desk-session.ts";
import { mateStatusLines, modelArg, secondmates, supervisorOnly, writeDeskSecrets, type Secondmate } from "./desk.ts";
import type { Memory } from "./memory.ts";
import { deskMayAct, type RelayRequest } from "./relay.ts";

type SessionEnv = Record<string, string | undefined>;

export type TurnRequest = RelayRequest & { memoryId: number; route: string };

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
  answer(pending: R[], parts: string[], target: R): void;
  react(pending: R[], emoji: string): void;
  relay(items: R[], mate: Secondmate, current: () => boolean): Promise<void>;
  inbox(): Promise<{ status: string; statusOk: boolean }>;
};

// omp wants provider/model-id for the compaction key.
const thresholdKeyOf = (provider: string, model: string) => `${provider === "inception" ? "inception" : "anthropic"}/${model}`;

// What the session already has: its own desk replies and this burst's texts.
const seenInTurn = (m: { kind: string; requestId?: string }, ids: Set<string>) => m.kind === "desk" || (!!m.requestId && ids.has(m.requestId));

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
    argv: [env.FM_DESK_SESSION_OMP || "omp", "--mode", "rpc", "--no-ui", "--no-extensions", "-e", `${import.meta.dir}/zoom.ts`,
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
    const actions = createActions({
      requests: pending, current, muted: host.muted, mates: () => mates, safe,
      reply: (parts, target) => host.answer(pending, parts, pending[target - 1]),
      react: (emoji) => host.react(pending, emoji),
      relay: async (mate) => {
        const items = pending.filter((r) => r.route === "pending");
        await host.relay(items, mate, current);
        return items.every((r) => r.route === "done");
      },
      handoff: (reason) => { if (reason) host.log("desk handoff")(reason); host.handoff(pending); },
      status: async () => {
        const inbox = await host.inbox();
        if (!inbox.statusOk) throw new Error("fleet status is unavailable; call handoff_main");
        return safe(`${inbox.status}\n${mateStatusLines(host.fmHome, mates)}`);
      },
    });
    const result = await session().ask((seed) => message(pending, original, safe, seed), controller.signal, actions.run);
    if (!current() || actions.acted()) return;
    host.log("desk session")(new Error(`turn ended with no action (${result.status}${result.error ? `: ${result.error}` : ""})`));
    host.handoff(pending);
  };
}
