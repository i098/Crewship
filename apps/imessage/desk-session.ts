// The front desk's one long chat: a persistent `omp --mode rpc` child that keeps the whole thread.
// The bridge owns delivery; this file owns the child: start, prompt, host-tool calls, restart with backoff.
// A restart resumes the same session (--continue), so the thread survives a crash or a service restart.
// omp compacts the session itself at the fixed trigger the bridge puts in its config (compaction.modelThresholds).
import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { logTokens, usageTokens } from "./tokenlog.ts";

export type HostTool = { name: string; description: string; parameters: Record<string, unknown> };
export type ToolRunner = (name: string, args: Record<string, unknown>) => Promise<string>;
export type PromptResult = { status: "completed" | "aborted" | "error"; error?: string; text?: string }; // text: the last words the model wrote in this prompt
type Frame = {
  type?: string; id?: string; success?: boolean; error?: unknown; status?: PromptResult["status"];
  result?: unknown; aborted?: boolean; message?: { role?: string; usage?: unknown; model?: string; content?: { type?: string; text?: string }[] };
  toolName?: string; arguments?: Record<string, unknown>;
};
type Waiter = { resolve: (frame: Frame) => void; reject: (error: Error) => void };

export const BACKOFF_MAX_MS = 60_000;
export const COMPACT_AT = 80_000; // tokens: the fixed trigger for the desk's session

export type SessionOptions = {
  argv: string[];
  cwd: string;
  sessionDir: string;
  env: Record<string, string | undefined>;
  tools: HostTool[];
  model: string;
  track?: <T extends Bun.Subprocess>(proc: T) => T;
  log?: (error: unknown) => void;
  now?: () => number;
  startMs?: number;
  turnMs?: number;
};

// The omp config overlay: it makes omp compact this session at COMPACT_AT tokens, whatever the catalog window says.
// The host tools need no human approval in omp: the bridge checks each call itself (desk-actions.ts).
export function sessionConfig(thresholdKey: string, tools: readonly HostTool[] = []): string {
  return JSON.stringify({
    compaction: { enabled: true, modelThresholds: { [thresholdKey]: `f${COMPACT_AT}` } },
    tools: { approval: Object.fromEntries(tools.map((tool) => [tool.name, "allow"])) },
  });
}

export class DeskSession {
  private proc?: Bun.Subprocess<"pipe", "pipe", "ignore">;
  private ready?: Promise<void>;
  private waiters = new Map<string, Waiter>();
  private run?: ToolRunner;
  private tail: Promise<unknown> = Promise.resolve();
  private sequence = 0;
  private failures = 0;
  private retryAt = 0;
  private seed = false;
  private words = "";
  private closing = false;

  constructor(private readonly o: SessionOptions) {}

  // Starts the child on the first ask. Throws while a crashed child is still in its backoff.
  private start(): Promise<void> {
    if (this.ready) return this.ready;
    const now = (this.o.now ?? Date.now)();
    if (now < this.retryAt) return Promise.reject(new Error(`desk session restarting in ${this.retryAt - now} ms`));
    // A directory with no session file is a new thread: the next prompt carries the memory view as its seed.
    this.seed = !existsSync(this.o.sessionDir) || readdirSync(this.o.sessionDir).length === 0;
    mkdirSync(this.o.sessionDir, { recursive: true, mode: 0o700 });
    const spawned = Bun.spawn(this.o.argv, { cwd: this.o.cwd, env: this.o.env, stdin: "pipe", stdout: "pipe", stderr: "ignore" });
    const proc = this.o.track ? this.o.track(spawned) : spawned;
    this.proc = proc;
    const ready = this.expect("ready", this.o.startMs ?? 30_000);
    void this.read(proc);
    void proc.exited.then(() => this.exited(proc));
    this.ready = (async () => {
      await ready;
      const set = await this.command({ type: "set_host_tools", tools: this.o.tools.map((tool) => ({ ...tool, loadMode: "essential" })) }); // essential: the model sees the tool without a search step
      if (!set.success) throw new Error(`set_host_tools refused: ${String(set.error ?? "unknown")}`);
    })().catch((error) => {
      proc.kill();
      throw error;
    });
    return this.ready;
  }

  private async read(proc: Bun.Subprocess<"pipe", "pipe", "ignore">) {
    let buffer = "";
    const decoder = new TextDecoder();
    try {
      for await (const chunk of proc.stdout as unknown as AsyncIterable<Uint8Array>) {
        buffer += decoder.decode(chunk, { stream: true });
        let at: number;
        while ((at = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, at);
          buffer = buffer.slice(at + 1);
          if (line.trim()) this.frame(line);
        }
      }
    } catch (error) { this.o.log?.(error); }
  }

  private frame(line: string) {
    let frame: Frame;
    try { frame = JSON.parse(line); } catch { return; }
    switch (frame.type) {
      case "ready": return this.settle("ready", frame);
      case "response": return frame.id ? this.settle(`r:${frame.id}`, frame) : undefined;
      case "prompt_result": return frame.id ? this.settle(`p:${frame.id}`, frame) : undefined;
      case "host_tool_call": return void this.tool(frame);
      case "message_end": {
        if (frame.message?.role !== "assistant") return;
        const written = (frame.message.content ?? []).filter((part) => part.type === "text").map((part) => part.text ?? "").join("\n").trim();
        if (written) this.words = written; // narration before a tool call is overwritten by the next message
        const used = usageTokens(frame.message.usage);
        if (used) logTokens({ kind: "desk-session", model: String(frame.message.model ?? this.o.model), ...used });
        return;
      }
      case "auto_compaction_end":
        // The summary replaced the old turns: the next prompt re-seeds the memory view next to it.
        if (frame.result && !frame.aborted) this.seed = true;
    }
  }

  private async tool(frame: Frame) {
    let text: string;
    let isError = false;
    try {
      if (!this.run) throw new Error("no turn is running");
      text = await this.run(String(frame.toolName), frame.arguments ?? {});
    } catch (error) {
      text = error instanceof Error ? error.message : String(error);
      isError = true;
    }
    this.send({ type: "host_tool_result", id: frame.id, result: { content: [{ type: "text", text }] }, isError });
  }

  private send(message: object) {
    const sink = this.proc?.stdin;
    if (!sink) throw new Error("desk session is not running");
    sink.write(`${JSON.stringify(message)}\n`);
    sink.flush();
  }

  private expect(key: string, timeoutMs?: number): Promise<Frame> {
    const { promise, resolve, reject } = Promise.withResolvers<Frame>();
    const timer = timeoutMs ? setTimeout(() => {
      this.waiters.delete(key);
      reject(new Error(`desk session: no ${key} in ${timeoutMs} ms`));
    }, timeoutMs) : undefined;
    this.waiters.set(key, { resolve: (f) => { clearTimeout(timer); resolve(f); }, reject: (e) => { clearTimeout(timer); reject(e); } });
    return promise;
  }

  private settle(key: string, frame: Frame) {
    const waiter = this.waiters.get(key);
    if (!waiter) return;
    this.waiters.delete(key);
    waiter.resolve(frame);
  }

  private command(message: { type: string; [key: string]: unknown }): Promise<Frame> {
    const id = `c${++this.sequence}`;
    const response = this.expect(`r:${id}`, this.o.startMs ?? 30_000);
    this.send({ id, ...message });
    return response;
  }

  private exited(proc: Bun.Subprocess) {
    if (this.proc !== proc) return;
    this.proc = undefined;
    this.ready = undefined;
    for (const waiter of this.waiters.values()) waiter.reject(new Error("desk session exited"));
    this.waiters.clear();
    if (this.closing) return;
    // Exponential backoff: 1 s, 2 s, 4 s ... capped; a completed prompt resets it.
    this.failures++;
    this.retryAt = (this.o.now ?? Date.now)() + Math.min(BACKOFF_MAX_MS, 1000 * 2 ** (this.failures - 1));
  }

  // One prompt, one result: asks queue, so only a turn's own signal aborts it and a late tool call of an
  // old turn never reaches the next turn's runner. `build` gets whether this prompt must carry the seed.
  async ask(build: (seed: boolean) => string, signal: AbortSignal, run: ToolRunner): Promise<PromptResult> {
    const previous = this.tail;
    const { promise: ended, resolve: release } = Promise.withResolvers<void>();
    this.tail = ended;
    try {
      await previous.catch(() => {});
      if (signal.aborted) return { status: "aborted" };
      await this.start();
      if (signal.aborted) return { status: "aborted" };
      const seed = this.seed;
      this.seed = false;
      const id = `p${++this.sequence}`;
      this.run = run;
      this.words = "";
      const done = this.expect(`p:${id}`);
      this.send({ id, type: "prompt", message: build(seed) });
      const abort = () => { try { this.send({ type: "abort" }); } catch { /* exited */ } };
      signal.addEventListener("abort", abort, { once: true });
      const proc = this.proc;
      const timer = setTimeout(() => proc?.kill(), this.o.turnMs ?? 120_000);
      try {
        const result = await done;
        if (result.status === "completed") this.failures = 0;
        const error = result.error as { message?: string } | undefined;
        return { status: result.status ?? "error", ...(error ? { error: String(error.message ?? error) } : {}), ...(this.words ? { text: this.words } : {}) };
      } finally {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
      }
    } finally {
      release();
    }
  }

  close() {
    this.closing = true;
    this.proc?.kill();
  }
}
