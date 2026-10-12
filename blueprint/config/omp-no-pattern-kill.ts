/**
 * Refuses process kills that select targets by name or command-line pattern.
 *
 * Every omp worker on this host runs as the same uid, and a worker's full brief
 * sits in its own argv. So `pkill -f '<anything in a brief>'` matches sibling
 * workers too: on 2026-10-01 one worker's `pkill -f 'ponytail-review main'`
 * SIGTERMed two other workers, twice. Kill by PID instead (`cmd & pid=$!` then
 * `kill "$pid"`).
 *
 * Loaded by every omp session from ~/.omp/agent/extensions/ (primary,
 * crewmates, scouts, secondmates). no-mistakes gate agents run omp with
 * --no-extensions, so they are not covered here.
 */
type ToolCallEvent = { toolName?: string; input?: Record<string, unknown> };
type ToolCallResult = { block?: boolean; reason?: string };
interface GuardExtensionApi {
	on(event: "tool_call", handler: (event: ToolCallEvent) => Promise<ToolCallResult>): void;
}

const PATTERN_KILLS: RegExp[] = [
	/(^|[^\w./-])(pkill|killall)(\s|$)/m, // pkill / killall by name or pattern
	/\bpgrep\b[^\n;]*\|\s*xargs\b[^\n;]*\bkill\b/, // pgrep ... | xargs kill
	/\bkill\b[^\n;]*(\$\(|`)\s*pgrep\b/, // kill $(pgrep ...)
];

const REASON =
	"Blocked: pkill/killall and kill-by-pgrep select processes by name or command line, " +
	"and every agent on this host shares one uid, so the pattern can match other workers " +
	"(their briefs sit in their argv). Kill only PIDs you started: `cmd & pid=$!`, then " +
	'`kill "$pid"`, or `kill` a PID you verified under your own process tree.';

export function isPatternKill(command: string): boolean {
	return PATTERN_KILLS.some((re) => re.test(command));
}

export default function (pi: GuardExtensionApi) {
	pi.on("tool_call", async (event) => {
		const tool = String(event.toolName ?? "");
		if (tool !== "bash" && tool !== "eval") return {};
		let text = "";
		try {
			text = typeof event.input?.command === "string" ? event.input.command : JSON.stringify(event.input ?? {});
		} catch {
			return {};
		}
		return isPatternKill(text) ? { block: true, reason: REASON } : {};
	});
}
