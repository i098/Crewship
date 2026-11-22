/**
 * Texts the owner when an agent starts a browser session through omp's own browser tools.
 *
 * The `chrome-devtools-axi` wrapper covers the CLI path; omp's `browser` namespace in eval
 * connects directly and never runs it. This hook calls the same `fleet-browser notice`, which
 * shares the wrapper's once-per-window claim, so the two paths never send twice.
 */
type ToolCallEvent = { toolName?: string; input?: Record<string, unknown> };
interface NoticeExtensionApi {
	on(event: "tool_call", handler: (event: ToolCallEvent) => Promise<Record<string, never>>): void;
}

export function startsBrowser(event: ToolCallEvent): boolean {
	if (event.toolName === "browser") return true;
	if (event.toolName !== "eval") return false;
	return typeof event.input?.code === "string" && /\bbrowser\s*\.\s*open\s*\(/.test(event.input.code);
}

export default function (pi: NoticeExtensionApi) {
	let sent = false;
	pi.on("tool_call", async (event) => {
		if (sent || !startsBrowser(event)) return {};
		sent = true;
		try {
			Bun.spawn(["fleet-browser", "notice", process.env.FLEET_BROWSER_TIER ?? "obscura"], {
				stdout: "ignore",
				stderr: "ignore",
			}).unref();
		} catch {} // a missing wrapper or failed notice never blocks the browser
		return {};
	});
}
