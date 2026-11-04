/**
 * Runs compact-adviser (npm `compact-adviser`, a Pi extension) inside omp in automatic mode:
 * TypeSafe Jev judges each settled checkpoint and the session compacts itself.
 *
 * omp has no `agent_settled` event, so `agent_end` feeds the package's handler once the
 * session is idle. The package's `session_before_compact` guard is not registered: an
 * extension on that event switches off omp's speculative compaction for every session.
 *
 * A compaction the adviser starts tries snapcompact, retries it after two failures, and only
 * after three failures in a row falls through to remote, then soft. Native threshold
 * maintenance walks compaction.methodOrder on its own and is unchanged.
 *
 * Privacy: a session whose cwd or Firstmate directories match a pattern in
 * ~/.omp/agent/compact-adviser-deny.json never reaches the adviser, so none of its text goes
 * to TypeSafe. A missing file excludes nothing; an unreadable or invalid one excludes every
 * session. COMPACT_ADVISER_DISABLE=1 turns the package off before it registers anything.
 *
 * The key comes from TYPESAFE_API_KEY, else ~/super.env at run time. It is never written here.
 * The first run writes ~/.omp/agent/compact-adviser.json (auto mode, 150k context budget) when
 * absent; it never rewrites an existing one.
 */
import { mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { getAgentDir, VERSION } from "@earendil-works/pi-coding-agent";
// Static imports only: omp rewrites the package's own @earendil-works imports for the static graph of an
// extension, not for a dynamic import(). Relative to ~/.omp/agent/extensions, where Crewship installs this file.
import { installAdviser } from "../../../.local/share/crewship/compact-adviser/current/node_modules/compact-adviser/src/adviser.ts";
import { parseDotenvKey } from "../../../.local/share/crewship/compact-adviser/current/node_modules/compact-adviser/src/env.ts";

const SETTINGS = { version: 1, mode: "auto", minContextTokens: 40000, contextBudgetTokens: 150000, autoAcknowledged: true, logRequests: false };
// Directories a Firstmate-spawned session carries in its environment, besides its cwd.
const FLEET_DIR_ENV = ["FM_HOME", "FM_ROOT_OVERRIDE", "FM_DATA_OVERRIDE", "FM_STATE_OVERRIDE", "FM_CONFIG_OVERRIDE", "FM_PROJECTS_OVERRIDE"];
// Three snapcompact attempts, then the other methods a one-off ctx.compact() accepts.
export const COMPACT_MODES = ["snapcompact", "snapcompact", "snapcompact", "remote", "soft"] as const;

export interface Ctx {
	cwd: string;
	isIdle(): boolean;
	sessionManager: { getBranch(): unknown };
	compact(options: CompactOptions): unknown;
}
interface CompactOptions {
	mode?: string;
	onComplete?: (result: unknown) => void;
	onError?: (error: unknown) => void;
}
type Handler = (event: unknown, ctx: Ctx) => unknown;
interface PiLike {
	on(event: string, handler: Handler): void;
	registerCommand(name: string, def: { handler: Handler }): void;
}

function real(path: string): string {
	try {
		return realpathSync(path);
	} catch {
		return path;
	}
}

export function isExcluded(cwd: string, env: NodeJS.ProcessEnv, denyFile: string): boolean {
	let patterns: RegExp[];
	try {
		const list: unknown = JSON.parse(readFileSync(denyFile, "utf8"));
		if (!Array.isArray(list) || !list.every(p => typeof p === "string")) return true;
		patterns = list.map(p => new RegExp(p, "i"));
	} catch (error) {
		if (error instanceof Error && "code" in error && error.code === "ENOENT") return false;
		return true;
	}
	const paths = [cwd, ...FLEET_DIR_ENV.map(k => env[k]).filter((v): v is string => !!v)];
	return paths.some(p => patterns.some(re => re.test(p) || re.test(real(p))));
}

export function typesafeKey(env: NodeJS.ProcessEnv, envFile: string): string | undefined {
	if (env.TYPESAFE_API_KEY?.trim()) return env.TYPESAFE_API_KEY;
	try {
		return parseDotenvKey(readFileSync(envFile, "utf8"), "TYPESAFE_API_KEY");
	} catch {
		return undefined;
	}
}

/** agent_end also fires when the run resumes by itself (a continuation or background job): not a checkpoint. */
function isContinuing(event: unknown): boolean {
	return typeof event === "object" && event !== null && (("willContinue" in event && !!event.willContinue) || ("awaitingAsyncWork" in event && !!event.awaitingAsyncWork));
}

/** Runs ctx.compact with each mode in turn; the next mode starts when the last one failed. */
export function compactWithFallback(ctx: Ctx, options: CompactOptions, modes: readonly string[] = COMPACT_MODES): void {
	const attempt = (i: number): void => {
		ctx.compact({
			...options,
			mode: modes[i],
			onError: error => (i + 1 < modes.length ? attempt(i + 1) : options.onError?.(error)),
		});
	};
	attempt(0);
}

export default function (pi: PiLike) {
	const agentDir = getAgentDir();
	const denyFile = join(agentDir, "compact-adviser-deny.json");
	try {
		mkdirSync(agentDir, { recursive: true, mode: 0o700 });
		writeFileSync(join(agentDir, "compact-adviser.json"), `${JSON.stringify(SETTINGS, null, 2)}\n`, { flag: "wx", mode: 0o600 });
	} catch {
		// An existing settings file stays as it is.
	}
	const excluded = (cwd: string) => isExcluded(cwd, process.env, denyFile);

	// Pi's sessionManager has buildContextEntries(); omp's equivalent root-to-leaf path is getBranch().
	const adapt = (ctx: Ctx): Ctx =>
		new Proxy(ctx, {
			get(target, prop) {
				if (prop === "compact") return (options: CompactOptions) => compactWithFallback(target, options);
				const value = Reflect.get(target, prop);
				if (prop !== "sessionManager") return typeof value === "function" ? value.bind(target) : value;
				return new Proxy(target.sessionManager, {
					get(sm, p) {
						if (p === "buildContextEntries") return () => sm.getBranch();
						const v = Reflect.get(sm, p);
						return typeof v === "function" ? v.bind(sm) : v;
					},
				});
			},
		});
	const guarded =
		(h: Handler): Handler =>
		(event, ctx) =>
			excluded(ctx.cwd) ? undefined : h(event, adapt(ctx));

	const shim = new Proxy(pi, {
		get(target, prop) {
			if (prop === "on") {
				return (event: string, handler: Handler) => {
					if (event === "session_before_compact") return;
					if (event === "agent_settled") {
						// agent_end fires before the session is idle, which the adviser requires.
						target.on("agent_end", (ev, ctx) => {
							if (isContinuing(ev)) return;
							const settle = (tries: number) =>
								setTimeout(() => {
									if (ctx.isIdle() || tries >= 20) guarded(handler)(ev, ctx);
									else settle(tries + 1);
								}, 250);
							settle(0);
						});
						return;
					}
					target.on(event, guarded(handler));
				};
			}
			if (prop === "registerCommand") {
				return (name: string, def: { handler: Handler }) => target.registerCommand(name, { ...def, handler: guarded(def.handler) });
			}
			const value = Reflect.get(target, prop);
			return typeof value === "function" ? value.bind(target) : value;
		},
	});

	installAdviser(shim, {
		agentDir,
		version: VERSION,
		key: () => typesafeKey(process.env, join(homedir(), "super.env")),
	});
}
