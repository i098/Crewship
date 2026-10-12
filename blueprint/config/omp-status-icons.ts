/**
 * One status-line entry of evenly spaced icons for the always-on modes:
 *   compress = caveman, brain = ADHD, scissors = ponytail (Nerd Font icons)
 * An icon shows if and only if its mode is on in this omp session; an off mode
 * is hidden. omp strips all styling from extension statuses, so a dimmed icon
 * would look lit.
 *
 * ponytail and i-have-adhd set their own text statuses ("🐴 ponytail: ⚡ FULL",
 * "● ADHD ON") and clear them when their mode turns off. omp gives every
 * extension the same ui object, so this wraps ui.setStatus once, keeps those
 * two keys for itself, and renders the combined icons under one key.
 * Crewship installs it as ~/.omp/agent/extensions/aa-mode-icons.ts: omp loads
 * extensions in name order, so the "aa-" name sorts first and the wrap is in
 * place before the plugins' own session_start handlers run.
 *
 * caveman has no omp extension and omp does not run its Claude Code hooks, so
 * nothing records its state. Here caveman is on when this session's system
 * prompt puts it in force (a rule that names skill://caveman), and then the
 * session's own history decides: each prompt the user sends is read with
 * caveman's own mode parser, so "stop caveman", "normal mode" and
 * "/caveman off" turn it off and "talk like caveman" turns it back on, and
 * invoking the caveman skill ("/caveman", which omp resolves to the skill)
 * turns it on unless its arguments turn it off ("/skill:caveman off").
 */
import { existsSync, readFileSync } from "fs";
import { createRequire } from "module";
import { join } from "path";

const KEY = "aa-modes";
const WRAPPED = Symbol.for("aa-mode-icons.wrapped");
const OWNED = new Set(["ponytail", "i-have-adhd"]);
const PLUGINS = join(process.env.HOME ?? "", ".omp", "plugins", "installed_plugins.json");

type ModeChange = { action: "set" | "clear" | "unresolved"; mode?: string } | null;

// caveman's own prompt parser (src/hooks/caveman-parse.js) from the installed
// caveman@caveman plugin, or undefined when the plugin is not installed.
function cavemanParser(): ((prompt: string) => ModeChange) | undefined {
	try {
		const installs = JSON.parse(readFileSync(PLUGINS, "utf8")).plugins?.["caveman@caveman"] ?? [];
		const dir = installs.find((i) => existsSync(join(i.installPath ?? "", "src/hooks/caveman-parse.js")))?.installPath;
		if (!dir) return undefined;
		const { parseModeChange } = createRequire(join(dir, "src/hooks/"))("./caveman-parse.js");
		return (prompt) => parseModeChange(prompt);
	} catch {
		return undefined;
	}
}

function applyChange(on: boolean, change: ModeChange): boolean {
	if (change?.action === "clear") return false;
	if (change?.action === "set") return change.mode !== "off";
	return on;
}

// caveman after this branch of the session: `inForce` at its start, then each
// user prompt read by caveman's parser and each caveman skill invocation.
export function cavemanFrom(entries, inForce: boolean, parse: (prompt: string) => ModeChange): boolean {
	let on = inForce;
	for (const e of entries ?? []) {
		if (e?.type === "custom_message" && e.customType === "skill-prompt" && e.details?.name === "caveman") {
			on = applyChange(true, parse(`/caveman ${e.details.args ?? ""}`));
			continue;
		}
		if (e?.type !== "message" || e.message?.role !== "user") continue;
		const { content } = e.message;
		const text = typeof content === "string" ? content : (content ?? []).map((p) => (p?.type === "text" ? p.text : "")).join("\n");
		on = applyChange(on, parse(text));
	}
	return on;
}

// Hooks from ~/.claude/settings.json and <cwd>/.claude/settings.json, as icons.
// Present = active; anything unmapped counts toward the hook-icon N guard-hook total.
const HOOK_ICONS: Record<string, string> = {
	"chrome-devtools-axi": "\uf268",
	"gh-axi": "\uf09b",
	"lavish-axi": "\uf1fc",
	lint: "\u{f00e2}",
	"auto-format": "\uf0d0",
	codegraph: "\uf0e8",
	"quality-gate": "\uf219",
	"herdr-agent-state": "\uf09e",
};
const HOOK_BINS = ["gh-axi", "lavish-axi", "chrome-devtools-axi", "codegraph"];
const HIDDEN = new Set(["session-start", "session-end", "notify", "headroom", "codex-review-diff", "codex-review-plan", "codex-review-surface"]);

type HookSettings = { hooks?: Record<string, Array<{ hooks?: Array<{ command?: string }> }>> };

function hookNames(cwd: string): string[] {
	const names = new Set<string>();
	for (const file of [join(process.env.HOME ?? "", ".claude", "settings.json"), join(cwd, ".claude", "settings.json")]) {
		let settings: HookSettings;
		try {
			// Local config file this account writes; a wrong shape just yields no hooks.
			settings = JSON.parse(readFileSync(file, "utf8")) as HookSettings;
		} catch {
			continue;
		}
		for (const events of Object.values(settings.hooks ?? {}))
			for (const entry of events ?? [])
				for (const { command } of entry.hooks ?? []) {
					if (!command) continue;
					for (const m of command.matchAll(/([\w][\w.-]*?)\.(?:sh|py|js|ts)\b/g)) names.add(m[1]);
					for (const bin of HOOK_BINS) if (command.includes(bin)) names.add(bin);
				}
	}
	return [...names].filter((n) => !HIDDEN.has(n));
}

export default function (pi) {
	const on: Record<string, boolean> = { caveman: false, "i-have-adhd": false, ponytail: false };
	const parse = cavemanParser();
	let hooks = "";
	let set; // the unwrapped ui.setStatus

	function render() {
		const modes = [["\uf066", on.caveman], ["\u{f09d1}", on["i-have-adhd"]], ["\uf0c4", on.ponytail]]
			.filter(([, lit]) => lit)
			.map(([glyph]) => glyph);
		set?.(KEY, [...modes, ...(hooks ? [hooks] : [])].join("   "));
	}

	function hookIcons(cwd: string): string {
		const names = hookNames(cwd);
		const shown = Object.entries(HOOK_ICONS).filter(([n]) => names.includes(n)).map(([, g]) => g);
		const guards = names.filter((n) => !(n in HOOK_ICONS)).length;
		return [...shown, ...(guards ? [`\u{f06e2} ${guards}`] : [])].join("   ");
	}

	let cavemanInForce = false; // this session's system prompt puts caveman in force

	function syncCaveman(ctx) {
		if (parse) on.caveman = cavemanFrom(ctx?.sessionManager?.getBranch?.(), cavemanInForce, parse);
		render();
	}

	function install(ctx) {
		const ui = ctx?.ui;
		if (ctx?.hasUI !== true || !ui?.setStatus) return;
		if (!ui[WRAPPED]) {
			const original = ui.setStatus.bind(ui);
			ui.setStatus = (key: string, text?: string) => {
				if (!OWNED.has(key)) return original(key, text);
				// Plugins send "" (or nothing) only when the mode is off; ponytail's "○" just means idle.
				on[key] = Boolean(text);
				original(key, undefined);
				render();
			};
			ui[WRAPPED] = original;
			for (const k of OWNED) original(k, undefined);
		}
		set = ui[WRAPPED];
		render();
	}

	for (const event of ["session_start", "session_switch"])
		pi.on(event, async (_event, ctx) => {
			hooks = hookIcons(ctx?.cwd ?? process.cwd());
			install(ctx);
			try {
				cavemanInForce = [await ctx.getSystemPrompt?.()].flat().join("\n").includes("skill://caveman");
			} catch {
				cavemanInForce = false;
			}
			syncCaveman(ctx);
		});

	// A prompt changes the icon as it is sent. agent_end replays the branch,
	// which by then holds that prompt and any caveman skill invocation, which
	// reaches the session without an input event.
	pi.on("input", (event) => {
		if (!parse || event?.source === "extension") return;
		on.caveman = cavemanFrom([{ type: "message", message: { role: "user", content: String(event?.text ?? "") } }], on.caveman, parse);
		render();
	});
	for (const event of ["agent_end", "session_tree"]) pi.on(event, (_event, ctx) => syncCaveman(ctx));
}
