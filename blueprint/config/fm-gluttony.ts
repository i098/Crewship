/**
 * Per-home opt-in for Firstmate crewmates and scouts; see docs/omp.md#gluttony-mode.
 * omp 18.12.1 reconciles the recorded mode after session_start, unlike a slash command in a brief.
 * Settings and VibeSpawnTool are private omp APIs; re-check them after an omp update.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { findScopedSettings } from "@oh-my-pi/pi-coding-agent/config/settings";
import { cfgRetryFallbackChains } from "@oh-my-pi/pi-coding-agent/session/settings";

interface Ctx {
	agent: { kind: "main" | "sub" };
	hasUI: boolean;
	sessionManager: ModeSessionManager;
	model?: { provider?: string; id?: string };
	modelRegistry: ModelRegistry;
}
interface GluttonyApi {
	pi?: HostModule;
	getThinkingLevel(): string | undefined;
	setThinkingLevel(level: string): void;
	on(event: "session_start", handler: (event: unknown, ctx: Ctx) => unknown): void;
	on(
		event: "before_subagent_spawn",
		handler: (event: { agent: string; modelRole?: string; patterns: string[] }, ctx: Ctx) =>
			Promise<{ model?: string; block?: boolean; reason?: string } | undefined>,
	): void;
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
		}, ctx: Ctx) => Promise<{ block?: boolean; reason?: string; input?: Record<string, unknown> } | undefined>,
	): void;
}
interface ModeSessionManager {
	buildSessionContext(): { mode?: string };
	appendModeChange(mode: string): void;
	getSessionId(): string;
}
interface HostSettings {
	overlay(overrides: Record<string, unknown>): HostSettings;
}
interface SpawnToolProto {
	session: { settings: HostSettings; sessionManager?: { getSessionId?(): string } };
	execute(toolCallId: string, params: { cli: Cli }, ...rest: unknown[]): Promise<unknown>;
}
interface HostModule {
	Settings?: { prototype: HostSettings };
	VibeSpawnTool?: { prototype: SpawnToolProto };
	SessionManager?: { prototype: { getEntries(): SessionEntry[] } };
}

interface ModelRef {
	provider: string;
	id: string;
}
interface ModelRegistry {
	find(provider: string, id: string): ModelRef | undefined;
	getApiKey(model: ModelRef, sessionId?: string): Promise<string | undefined>;
}

interface SessionEntry {
	type: string;
	agent?: string;
	modelRole?: string;
	resolvedModel?: string;
	retryFallback?: { primary: string; chain: string[] };
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
const AGENT: Record<Cli, string> = { fast: "sonic", good: "task" };
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
	const pattern = `${model}:${level}`;
	if (!allowedPattern(tiers, cli, pattern)) {
		return { error: `vibe_spawn ${cli} worker: "${model} ${level}" is not allowed. Allowed: ${choices(tiers)}.` };
	}
	return { prompt: match ? prompt.slice(match[0].length) : prompt, pattern };
}

function bounded(tiers: Tiers, cli: Cli, pattern?: string): string {
	const tier = tiers[cli];
	const patternWithLevel = pattern?.includes(":") ? pattern : `${pattern}:${tier.level}`;
	return allowedPattern(tiers, cli, patternWithLevel)
		? patternWithLevel
		: `${tier.model}:${tier.level}`;
}

function allowedPattern(tiers: Tiers, cli: Cli, pattern: string, fallback = false): boolean {
	const [model, level] = pattern.split(":");
	const tier = tiers[cli];
	const allowedModel = tier.models.includes(model) ||
		(fallback && model === "anthropic/claude-haiku-5-5" && tiers.fast.models.includes(model));
	return allowedModel && tier.levels.includes(level);
}

function retryPattern(tiers: Tiers, primary: string): string {
	const haiku = "anthropic/claude-haiku-5-5";
	if (!tiers.fast.models.includes(haiku)) return primary;
	const level = primary.split(":")[1];
	return `${haiku}:${ABOVE_MEDIUM.includes(level) ? level : "medium"}`;
}

function boundedChain(tiers: Tiers, cli: Cli, primary: string, chain: string[]): string[] {
	const fallback = retryPattern(tiers, primary);
	return [...new Set(chain.map(pattern => allowedPattern(tiers, cli, pattern, true) ? pattern : fallback))];
}

async function authenticatedPattern(tiers: Tiers, cli: Cli, pattern: string, ctx: Ctx): Promise<string | undefined> {
	const fallback = retryPattern(tiers, pattern);
	const candidates = pattern === fallback ? [pattern] : [pattern, fallback];
	for (const candidate of candidates) {
		if (!allowedPattern(tiers, cli, candidate, true)) continue;
		const [selector] = candidate.split(":");
		const [provider, id] = selector.split("/");
		const model = ctx.modelRegistry.find(provider, id);
		if (model && (await ctx.modelRegistry.getApiKey(model, ctx.sessionManager.getSessionId()))?.trim()) {
			return candidate;
		}
	}
	return undefined;
}

async function availableModels(tiers: Tiers, ctx: Ctx): Promise<Set<string>> {
	const available = new Set<string>();
	for (const selector of new Set(Object.values(tiers).flatMap(tier => tier.models))) {
		const [provider, id] = selector.split("/");
		const model = ctx.modelRegistry.find(provider, id);
		if (model && (await ctx.modelRegistry.getApiKey(model, ctx.sessionManager.getSessionId()))?.trim()) {
			available.add(selector);
		}
	}
	return available;
}

export default function (pi: GluttonyApi) {
	const env = process.env;
	if (env.FM_OMP_HARNESS !== "omp" || env.OMP_SKIP_SETUP !== "1" || !env.FM_TASK_ID || !env.FM_TASK_INBOX) return;
	const home = path.dirname(path.dirname(env.FM_TASK_INBOX));
	let tiers: Tiers | undefined;
	let sessionId: string | undefined;
	let patch: SpawnPatch | undefined;
	pi.on("session_start", async (_event, ctx) => {
		if (!fs.existsSync(path.join(home, "config", "gluttony"))) return;
		if (ctx.agent.kind === "main" && !ctx.hasUI) return;
		const provider = ctx.model?.provider ?? "";
		tiers = provider === "openai-codex" || provider === "openai" ? codexTiers(provider) : anthropicTiers();
		if (ctx.agent.kind === "sub") {
			const model = `${provider}/${ctx.model?.id}`;
			const cli = tiers.fast.models.includes(model) ? "fast" : "good";
			if (!tiers[cli].levels.includes(pi.getThinkingLevel() ?? "")) pi.setThinkingLevel(tiers[cli].level);
			const settings = findScopedSettings();
			if (settings) {
				const primary = `${model}:${pi.getThinkingLevel()}`;
				const chains = cfgRetryFallbackChains.get(settings);
				cfgRetryFallbackChains.override(settings, Object.fromEntries(
					Object.entries(chains).map(([key, chain]) => [key, boundedChain(tiers, cli, primary, chain)]),
				));
			}
			return;
		}
		const sm = ctx.sessionManager;
		if (sm.buildSessionContext().mode !== "vibe") sm.appendModeChange("vibe");
		sessionId = sm.getSessionId();
		patch = patchSpawn(pi.pi);
		patchRestore(pi.pi, home, tiers, await availableModels(tiers, ctx));
	});
	pi.on("before_subagent_spawn", async (event, ctx) => {
		if (!tiers) return undefined;
		const cli = event.modelRole === "smol" || event.agent === "sonic" ? "fast" : "good";
		const pattern = await authenticatedPattern(tiers, cli, bounded(tiers, cli, event.patterns[0]), ctx);
		return pattern
			? { model: pattern }
			: { block: true, reason: "Gluttony: no allowed subagent model has a usable credential." };
	});
	pi.on("before_agent_start", (event, ctx) =>
		tiers && ctx.agent.kind === "main" ? { systemPrompt: [...event.systemPrompt, gluttonLine(tiers)] } : undefined,
	);
	pi.on("tool_call", async (event, ctx) => {
		if (!tiers || !sessionId || event.toolName !== "vibe_spawn") return undefined;
		const cli: Cli = event.input.cli === "good" ? "good" : "fast";
		const result = choose(tiers, cli, event.input.prompt ?? "");
		if ("error" in result) return { block: true, reason: result.error };
		const pattern = await authenticatedPattern(tiers, cli, result.pattern, ctx);
		if (!pattern) return { block: true, reason: "Gluttony: no allowed worker model has a usable credential." };
		patch?.picked.set(`${sessionId}:${event.toolCallId}`, pattern);
		return { input: { ...event.input, prompt: result.prompt } };
	});
}

const PATCHED = Symbol.for("fm-gluttony.spawn-patched");
const RESTORE_PATCHED = Symbol.for("fm-gluttony.restore-patched");
interface SpawnPatch {
	picked: Map<string, string>;
}

function patchSpawn(host: HostModule | undefined): SpawnPatch | undefined {
	const proto = host?.VibeSpawnTool?.prototype as (SpawnToolProto & { [PATCHED]?: SpawnPatch }) | undefined;
	if (!proto || !host?.Settings?.prototype?.overlay) return;
	if (proto[PATCHED]) return proto[PATCHED];
	const state: SpawnPatch = { picked: new Map() };
	proto[PATCHED] = state;
	const original = proto.execute;
	proto.execute = function (toolCallId, params, ...rest) {
		const sessionId = this.session.sessionManager?.getSessionId?.();
		if (!sessionId) return original.call(this, toolCallId, params, ...rest);
		const key = `${sessionId}:${toolCallId}`;
		const pattern = state.picked.get(key);
		state.picked.delete(key);
		if (!pattern) return original.call(this, toolCallId, params, ...rest);
		const settings = this.session.settings.overlay({
			modelRoles: { [ROLE[params.cli]]: pattern },
			"task.agentModelOverrides": { [AGENT[params.cli]]: pattern },
		});
		const tool = Object.assign(Object.create(Object.getPrototypeOf(this)), this, {
			session: { ...this.session, settings, getActiveModelString: () => pattern },
		});
		return original.call(tool, toolCallId, params, ...rest);
	};
	return state;
}

interface RestoreBounds {
	tiers: Tiers;
	available: Set<string>;
}

function patchRestore(host: HostModule | undefined, home: string, tiers: Tiers, available: Set<string>): void {
	const proto = host?.SessionManager?.prototype as
		({ getEntries(): SessionEntry[]; [RESTORE_PATCHED]?: Map<string, RestoreBounds> }) | undefined;
	if (!proto) return;
	if (proto[RESTORE_PATCHED]) {
		proto[RESTORE_PATCHED].set(home, { tiers, available });
		return;
	}
	const homes = new Map([[home, { tiers, available }]]);
	proto[RESTORE_PATCHED] = homes;
	const original = proto.getEntries;
	proto.getEntries = function () {
		const entries = original.call(this);
		const inbox = process.env.FM_TASK_INBOX;
		const active = inbox && homes.get(path.dirname(path.dirname(inbox)));
		if (!active) return entries;
		return entries.map(entry => {
			if (entry.type !== "session_init") return entry;
			const cli = entry.modelRole === "smol" || entry.agent === "sonic" ? "fast" : "good";
			const selected = entry.resolvedModel && allowedPattern(active.tiers, cli, entry.resolvedModel, true)
				? entry.resolvedModel
				: bounded(active.tiers, cli, entry.resolvedModel);
			const primary = [selected, retryPattern(active.tiers, selected)].find(
				pattern => allowedPattern(active.tiers, cli, pattern, true) && active.available.has(pattern.split(":")[0]),
			);
			if (!primary) throw new Error("Gluttony: no allowed restored worker model has a usable credential.");
			const chain = boundedChain(active.tiers, cli, primary, entry.retryFallback?.chain ?? []);
			return {
				...entry,
				modelRole: undefined,
				resolvedModel: primary,
				retryFallback: entry.retryFallback
					? { primary, chain: chain.filter(pattern => pattern !== primary) }
					: undefined,
			};
		});
	};
}
