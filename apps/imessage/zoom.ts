// The desk memory tool, an omp extension: zoom(id, n) opens a line of its memory view.
// It reads the memory directory that FM_DESK_MEMORY names; bridge.ts is the only writer. FM_DESK_SPENT is the
// bytes the call's prompt already holds; results past the ceiling are refused (memory.ts Budget).
import { statSync } from "node:fs";
import { getAgentDir } from "@oh-my-pi/pi-utils";
import { builtinCredentialSecretEntries, collectEnvSecrets, loadSecrets, SecretObfuscator } from "@oh-my-pi/pi-coding-agent/secrets";
import { mapJsonStrings } from "@oh-my-pi/pi-coding-agent/secrets/placeholder-scan";
import { InternalUrlRouter } from "@oh-my-pi/pi-coding-agent/internal-urls";
import { expandDelimitedPathEntries, expandPath, normalizePathLikeInput, parseFindPattern, resolveToCwd } from "@oh-my-pi/pi-coding-agent/tools/path-utils";
import { isReadableUrlPath } from "@oh-my-pi/pi-tui/tools/read";
import { Budget, load, zoom } from "./memory.ts";
import { canonicalWritePath } from "./desk.ts";

// The slice of omp's ExtensionAPI this file uses.
type Zod = { object(shape: Record<string, unknown>): unknown; number(): { describe(text: string): unknown } };
type DeskMessage = { role: string; content: string | { type: string; text?: string }[]; toolCallId?: string; toolName?: string; isError?: boolean };
export default function (pi: {
  zod: Zod;
  registerTool(tool: unknown): void;
  on(event: "before_provider_request", handler: (event: { payload: Record<string, unknown> }) => unknown): void;
  on(event: "tool_call", handler: (event: { toolName: string; input: Record<string, unknown> }) => unknown): void;
  on(event: "session_stop", handler: (event: { messages: DeskMessage[] }) => unknown): void;
}) {
  const z = pi.zod;
  if (process.env.FM_DESK_INCEPTION_INSTANT === "1") {
    pi.on("before_provider_request", ({ payload }) => ({ ...payload, reasoning_effort: "instant" }));
  }
  pi.on("tool_call", guardServerTools);
  if (process.env.FM_DESK_SERVER_TOOLS === "1") pi.on("session_stop", async ({ messages }) => {
    const entries = [...collectEnvSecrets(), ...await loadSecrets(process.cwd(), getAgentDir()), ...builtinCredentialSecretEntries()];
    const secrets = new SecretObfuscator(entries.map((entry) => ({ ...entry, mode: "replace", replacement: "[REDACTED]" })));
    const redact = (text: string) => {
      try {
        const value = JSON.parse(text);
        const filtered = mapJsonStrings(value, (part: string) => secrets.obfuscate(part));
        return filtered === value ? text : JSON.stringify(filtered);
      }
      catch { return secrets.obfuscate(text); }
    };
    const output = messages.filter((message) => message.role === "assistant" || message.role === "toolResult").map((message) => ({
      ...message,
      text: redact(typeof message.content === "string" ? message.content
        : message.content.filter((part) => part.type === "text").map((part) => part.text ?? "").join("\n")),
    }));
    const tools = Object.fromEntries(output.filter((message) => message.role === "toolResult" && !message.isError)
      .map((message) => [message.toolCallId, { name: message.toolName, text: message.text }]));
    const drafted = output.findLast((message) => message.role === "assistant")?.text ?? "";
    process.stdout.write(`${JSON.stringify({ type: "desk_result", drafted, tools, question: redact(process.env.FM_DESK_QUESTION ?? "") })}\n`);
  });
  // A missing FM_DESK_SPENT counts as a full call: the first zoom ends it.
  const budget = new Budget(Number(process.env.FM_DESK_SPENT || Infinity));
  pi.registerTool({
    approval: "read",
    name: "zoom",
    label: "Zoom",
    description: "Open the line id+n of the <chat> view into the two lines of n/2 under it; n = 1 gives the message whole, with its date.",
    parameters: z.object({ id: z.number().describe("the line's first message"), n: z.number().describe("how many messages the line covers") }),
    async execute(_call: string, p: { id: number; n: number }) {
      const { msgs, nodes } = load(process.env.FM_DESK_MEMORY ?? "");
      const text = budget.take(zoom(msgs, nodes, p.id, p.n));
      // Even the refusal would pass the ceiling: end the call before its next request. The desk stays quiet.
      if (text === undefined) process.exit(1);
      return { content: [{ type: "text", text }] };
    },
  });
}

const LOCAL_SCHEMES: Record<string, true> = { file: true, artifact: true, local: true, proc: true };

async function requiresExternalReadApproval(toolName: string, rawPath: string): Promise<boolean> {
  const path = expandPath(normalizePathLikeInput(rawPath));
  const target = InternalUrlRouter.instance().normalize(path);
  const scheme = /^([a-z][\w+.-]*):\/\//i.exec(target)?.[1].toLowerCase();
  if (isReadableUrlPath(target) || (scheme && !LOCAL_SCHEMES[scheme])) return true;
  const paths = await expandDelimitedPathEntries([path], process.cwd(), toolName === "glob" ? { splitter: parseFindPattern } : {});
  for (const part of paths) {
    if (part !== path && await requiresExternalReadApproval(toolName, part)) return true;
  }
  return false;
}

async function guardServerTools({ toolName, input }: { toolName: string; input: Record<string, unknown> }) {
  if (["read", "grep", "glob"].includes(toolName) && typeof input.path === "string"
    && await requiresExternalReadApproval(toolName, input.path)) {
    return { block: true, reason: "External reads require owner approval. Hand off this request." };
  }
  if (toolName === "edit") return { block: true, reason: "Use an explicitly authorized file write." };
  if (toolName !== "write") return;
  const allowed = process.env.FM_DESK_WRITE_PATH;
  if (!allowed || typeof input.path !== "string" || canonicalWritePath(input.path) !== allowed
    || canonicalWritePath(resolveToCwd(input.path, process.cwd())) !== allowed
    || typeof input.content !== "string" || !input.content.trim()) {
    return { block: true, reason: "The owner did not authorize this non-empty write to this absolute path. Hand off for approval." };
  }
  if (input.content.startsWith("#!") && !input.content.startsWith("#![")) {
    const mode = statSync(allowed, { throwIfNoEntry: false })?.mode ?? 0;
    if ((mode & 0o111) !== 0o111) return { block: true, reason: "Adding execute permissions requires owner approval. Hand off this request." };
  }
}
