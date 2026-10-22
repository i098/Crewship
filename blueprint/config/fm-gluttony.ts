/**
 * Per-home opt-in for Firstmate crewmates and scouts; see docs/omp.md#gluttony-mode.
 * omp 18.12.1 reconciles the recorded mode after session_start, unlike a slash command in a brief.
 * Settings and VibeSpawnTool are private omp APIs; re-check them after an omp update.
 */
import * as fs from "node:fs";
import * as path from "node:path";

interface Ctx {
	agent: { kind: "main" | "sub" };
	hasUI: boolean;
	sessionManager: unknown;
	model?: { provider?: string };
}
interface GluttonyApi {
	pi?: HostModule;
	on(event: "session_start", handler: (event: unknown, ctx: Ctx) => unknown): void;
	on(
		event: "before_agent_start",
		handler: (event: { systemPrompt: string[] }, ctx: Ctx) => { systemPrompt: string[] } | undefined,
	): void;
	on(
		event: "tool_call",
		handler: (event: {
			toolName: string;
			toolCallId: string;
			input: { cli?: string; prompt?: string };
		}) => { block?: boolean; reason?: string; input?: Record<string, unknown> } | undefined,
	): void;
}
interface ModeSessionManager {
	buildSessionContext(): { mode?: string };
	appendModeChange(mode: string): void;
}
interface HostSettings {
	getModelRole(role: string): string | undefined;
	overrideModelRoles(roles: Record<string, string>): void;
}
interface SpawnToolProto {
	execute(toolCallId: string, params: { cli: Cli }, ...rest: unknown[]): Promise<unknown>;
}
interface HostModule {
	Settings?: { instance?: HostSettings };
	VibeSpawnTool?: { prototype: SpawnToolProto };
}

type Cli = "fast" | "good";
interface Tier {
	models: string[];
	levels: string[];
	model: string;
	level: string;
}
type Tiers = Record<Cli, Tier>;

const ABOVE_MEDIUM = ["medium", "high", "xhigh", "max"];
const ROLE: Record<Cli, string> = { fast: "smol", good: "task" };
const DIRECTIVE = /^@model[ \t]+(\S+)(?:[ \t]+(\S+))?[ \t]*(?:\r?\n|$)/;

function anthropicTiers(): Tiers {
	return {
		fast: {
			models: ["inception/mercury-3", "anthropic/claude-haiku-5-5"],
			levels: ABOVE_MEDIUM,
			model: "inception/mercury-3",
			level: "high",
		},
		good: {
			models: ["anthropic/claude-sonnet-5-5"],
			levels: ABOVE_MEDIUM,
			model: "anthropic/claude-sonnet-5-5",
			level: "medium",
		},
	};
}

function codexTiers(provider: string): Tiers {
	return {
		fast: {
			models: [`${provider}/gpt-6-luna`],
			levels: ["low", "medium", "high", "xhigh"],
			model: `${provider}/gpt-6-luna`,
			level: "high",
		},
		good: {
			models: [`${provider}/gpt-6.1-sol`],
			levels: ["low", "medium"],
			model: `${provider}/gpt-6.1-sol`,
			level: "medium",
		},
	};
}

function choices(tiers: Tiers): string {
	const one = (cli: Cli) => `${cli} = ${tiers[cli].models.join(" | ")} at ${tiers[cli].levels.join("|")}`;
	return `${one("fast")}; ${one("good")}`;
}

function gluttonLine(tiers: Tiers): string {
	return (
		"Gluttony mode: you are this task's read-only vibe director. You only plan and read with read, todo and vibe_* tools. Split independent work across concurrent vibe workers. Assign a good worker to append status, acknowledge the steering inbox, edit files and commit; the director cannot do these steps. Workers have every tool and may use in-process task subagents. " +
		`Choose each worker's model with an optional first prompt line \`@model <provider/id> <level>\` in vibe_spawn; allowed: ${choices(tiers)}. ` +
		`Default when omitted: fast = ${tiers.fast.model} ${tiers.fast.level}; good = ${tiers.good.model} ${tiers.good.level}. Anything outside these sets is rejected.`
	);
}

function choose(tiers: Tiers, cli: Cli, prompt: string): { prompt: string; pattern: string } | { error: string } {
	const tier = tiers[cli];
	const match = DIRECTIVE.exec(prompt);
	const model = match?.[1] ?? tier.model;
	const level = match?.[2] ?? tier.level;
	if (!tier.models.includes(model) || !tier.levels.includes(level)) {
		return { error: `vibe_spawn ${cli} worker: "${model} ${level}" is not allowed. Allowed: ${choices(tiers)}.` };
	}
	return { prompt: match ? prompt.slice(match[0].length) : prompt, pattern: `${model}:${level}` };
}

export default function (pi: GluttonyApi) {
	const env = process.env;
	if (env.FM_OMP_HARNESS !== "omp" || env.OMP_SKIP_SETUP !== "1" || !env.FM_TASK_ID || !env.FM_TASK_INBOX) return;
	const home = path.dirname(path.dirname(env.FM_TASK_INBOX));
	let tiers: Tiers | undefined;
	const picked = new Map<string, string>();
	pi.on("session_start", (_event, ctx) => {
		if (ctx.agent.kind !== "main" || !ctx.hasUI || !fs.existsSync(path.join(home, "config", "gluttony"))) return;
		const sm = ctx.sessionManager as ModeSessionManager;
		if (sm.buildSessionContext().mode !== "vibe") sm.appendModeChange("vibe");
		const provider = ctx.model?.provider ?? "";
		const codex = provider === "openai-codex" || provider === "openai";
		tiers = codex ? codexTiers(provider) : anthropicTiers();
		const settings = pi.pi?.Settings?.instance;
		if (codex && settings) {
			const { fast, good } = tiers;
			settings.overrideModelRoles({
				smol: `${fast.model}:${fast.level}`,
				task: `${good.model}:${good.level}`,
				subagent: `${good.model}:${good.level}`,
			});
		}
		patchSpawn(pi.pi, picked);
	});
	pi.on("before_agent_start", (event, ctx) =>
		tiers && ctx.agent.kind === "main" ? { systemPrompt: [...event.systemPrompt, gluttonLine(tiers)] } : undefined,
	);
	pi.on("tool_call", event => {
		if (!tiers || event.toolName !== "vibe_spawn") return undefined;
		const cli: Cli = event.input.cli === "good" ? "good" : "fast";
		const result = choose(tiers, cli, event.input.prompt ?? "");
		if ("error" in result) return { block: true, reason: result.error };
		picked.set(event.toolCallId, result.pattern);
		return { input: { ...event.input, prompt: result.prompt } };
	});
}

const PATCHED = Symbol.for("fm-gluttony.spawn-patched");
let spawnQueue: Promise<unknown> = Promise.resolve();

/** Serialize role changes so concurrent spawns cannot read another worker's model choice. */
function patchSpawn(host: HostModule | undefined, picked: Map<string, string>) {
	const proto = host?.VibeSpawnTool?.prototype as (SpawnToolProto & { [PATCHED]?: true }) | undefined;
	const settings = host?.Settings?.instance;
	if (!proto || !settings || proto[PATCHED]) return;
	proto[PATCHED] = true;
	const original = proto.execute;
	proto.execute = function (this: SpawnToolProto, toolCallId, params, ...rest) {
		const pattern = picked.get(toolCallId);
		picked.delete(toolCallId);
		const run = async () => {
			if (!pattern) return original.call(this, toolCallId, params, ...rest);
			const role = ROLE[params.cli];
			const previous = settings.getModelRole(role);
			settings.overrideModelRoles({ [role]: pattern });
			try {
				return await original.call(this, toolCallId, params, ...rest);
			} finally {
				if (previous) settings.overrideModelRoles({ [role]: previous });
			}
		};
		const result = spawnQueue.then(run, run);
		spawnQueue = result.catch(() => undefined);
		return result;
	};
}
