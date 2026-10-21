/**
 * Refuses pattern-based process kills and ambiguous GitHub issue or PR writes.
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

const ISSUE_WRITES: Record<string, true> = {
	create: true, new: true, edit: true, comment: true, close: true, reopen: true, delete: true,
	transfer: true, lock: true, unlock: true, pin: true, unpin: true, develop: true,
};
const PR_WRITES: Record<string, true> = {
	create: true, new: true, comment: true, edit: true, close: true, reopen: true,
	merge: true, review: true, ready: true,
};
const BOOL_FLAGS: Record<string, true> = {
	"--help": true, "-h": true, "--web": true, "-w": true, "--editor": true, "-e": true,
	"--yes": true, "-y": true, "--delete-branch": true, "-d": true, "--squash": true,
	"--rebase": true, "--merge": true, "--auto": true, "--disable-auto": true, "--admin": true,
	"--draft": true, "--allow-maintainer-edit": true, "--verify": true, "--exit-status": true,
	"--undo": true, "--remove": true, "--confirm": true, "--paginate": true, "--slurp": true,
	"--include": true, "-i": true, "--silent": true, "--verbose": true, "--full": true,
	"--approve": true, "--request-changes": true, "--no-type": true,
};
const TARGET_REQUIRED =
	"Blocked: GitHub writes need an explicit repository target. Use -R owner/repo, " +
	"a supported issue or pull-request URL, or a literal repos/owner/repo/ API path.";

type GithubArgs = { positionals: string[]; flags: Record<string, string[]> };
type ShellWord = { value: string; operator: boolean };

function shellWords(command: string): ShellWord[] {
	const words = command.replace(/\\\r?\n/g, "").match(/[0-9]*(?:>&|<&|<>|>>?|<<<?)|&>>?|(?:[^\s'"\\;&|()<>`]+|\\[\s\S]|"(?:\\[\s\S]|[^"\\])*"|'[^']*')+|[;&|()\n`]/g) ?? [];
	return words.map((word) => ({
		operator: /^(?:[;&|()\n`]|[0-9]*(?:>&|<&|<>|>>?|<<<?)|&>>?)$/.test(word),
		value: word.replace(
			/'([^']*)'|"((?:\\[\s\S]|[^"\\])*)"|\\([\s\S])/g,
			(_match, single, double, escaped) => single ?? double?.replace(/\\(["\\$`])/g, "$1") ?? escaped,
		),
	}));
}

function commandArgs(words: ShellWord[], start: number): string[] {
	const args: string[] = [];
	for (let i = start; i < words.length; i++) {
		const { value, operator } = words[i];
		if (operator && /[<>]/.test(value)) {
			i++;
			continue;
		}
		if (operator) break;
		args.push(value);
	}
	return args;
}

function githubArgs(words: string[]): GithubArgs {
	const positionals: string[] = [];
	const flags: Record<string, string[]> = {};
	const aliases: Record<string, string> = { "-R": "--repo", "-X": "--method", "-f": "--raw-field", "-F": "--field" };
	for (let i = 0; i < words.length; i++) {
		const word = words[i];
		if (word === "--") {
			positionals.push(...words.slice(i + 1));
			break;
		}
		if (!word.startsWith("-")) {
			positionals.push(word);
			continue;
		}
		const flag = word.match(/^(--[^=]+|-[RXfF])(?:=(.*)|(.+))?$/);
		const name = aliases[flag?.[1] ?? word] ?? flag?.[1] ?? word;
		const boolean = BOOL_FLAGS[word] || (positionals[1] === "review" && word === "--comment");
		const value = boolean ? "" : flag?.[2] ?? flag?.[3] ?? words[++i] ?? "";
		(flags[name] ??= []).push(value);
	}
	return { positionals, flags };
}

function literalRepo(value: string): string {
	return /^[\w.-]+\/[\w.-]+$/.test(value) ? value.toLowerCase() : "";
}

function urlRepo(value: string, kind: string): string {
	const match = value.match(/^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/(issues|pull)\/\d+(?:[/?#].*)?$/);
	return match && match[2] === (kind === "issue" ? "issues" : "pull") ? match[1].toLowerCase() : "";
}

function apiTargets(args: GithubArgs, cli: string): string[] {
	const { positionals, flags } = args;
	const positionalMethod = cli === "gh-axi" && /^(GET|HEAD|POST|PATCH|PUT|DELETE)$/i.test(positionals[1] ?? "");
	const payload = flags["--field"] || flags["--raw-field"] || flags["--input"];
	const method = flags["--method"]?.at(-1) ??
		(positionalMethod ? positionals[1] : payload && cli === "gh" ? "POST" : "GET");
	if (!/^(POST|PATCH|PUT|DELETE)$/i.test(method)) return [];
	const endpoint = positionals[positionalMethod ? 2 : 1] ?? "";
	if (!/(?:^|\/)(?:issues|pulls|comments)(?:[/?#]|$)/.test(endpoint) && !/[$`{]/.test(endpoint)) return [];
	const path = endpoint.replace(/^https:\/\/api\.github\.com\//, "").replace(/^\//, "");
	const match = path.match(/^repos\/([\w.-]+\/[\w.-]+)\/(?:issues|pulls|comments)(?:[/?#]|$)/);
	return [match?.[1].toLowerCase() ?? ""];
}

function mutationTargets(args: GithubArgs, cli: string): string[] {
	const { positionals, flags } = args;
	const [kind, operation, selector] = positionals;
	const writes = kind === "issue" ? ISSUE_WRITES : kind === "pr" ? PR_WRITES : undefined;
	const subissueWrite = cli === "gh-axi" && operation === "subissue" && /^(add|remove)$/.test(selector);
	if (!writes?.[operation] && !subissueWrite) return [];
	const targets = (flags["--repo"] ?? []).map(literalRepo);
	if (cli === "gh" && selector?.startsWith("https://") && operation !== "create" && operation !== "new") {
		targets.push(urlRepo(selector, kind));
	}
	if (targets.length === 0) targets.push("");
	if (kind === "issue" && operation === "transfer") {
		const destination = cli === "gh-axi" ? flags["--to-repo"]?.at(-1) : positionals[3];
		targets.push(literalRepo(destination ?? ""));
	}
	return targets;
}

function checkGithubWrite(words: string[], cli: string): string {
	const args = githubArgs(words);
	if (args.flags["--help"] || args.flags["-h"]) return "";
	const targets = args.positionals[0] === "api" ? apiTargets(args, cli) : mutationTargets(args, cli);
	if (targets.some((target) => !target)) return TARGET_REQUIRED;
	const contract = process.env.CREWSHIP_GITHUB_REPO;
	const approval = process.env.CREWSHIP_GITHUB_APPROVED_REPO;
	if (contract && targets.some((target) => target !== literalRepo(contract) && target !== literalRepo(approval ?? ""))) {
		return "Blocked: GitHub write target differs from CREWSHIP_GITHUB_REPO. " +
			"Set CREWSHIP_GITHUB_APPROVED_REPO to the exact repository only after explicit approval.";
	}
	return "";
}

function githubWriteReason(command: string): string {
	const words = shellWords(command);
	for (let i = 0; i < words.length; i++) {
		const cli = words[i].value.split("/").pop() ?? "";
		if (/^(?:bash|sh|zsh)$/.test(cli) && /^-[a-z]*c[a-z]*$/.test(words[i + 1]?.value ?? "")) {
			const reason = githubWriteReason(words[i + 2]?.value ?? "");
			if (reason) return reason;
		}
		if (cli !== "gh" && cli !== "gh-axi") continue;
		const args = commandArgs(words, i + 1);
		const reason = checkGithubWrite(args, cli);
		if (reason) return reason;
	}
	return "";
}

export default function (pi: GuardExtensionApi) {
	pi.on("tool_call", async (event) => {
		const tool = String(event.toolName ?? "");
		if (tool !== "bash" && tool !== "eval") return {};
		let text = "";
		try {
			text = typeof event.input?.command === "string" ? event.input.command :
				typeof event.input?.code === "string" ? event.input.code : JSON.stringify(event.input ?? {});
		} catch {
			return {};
		}
		if (isPatternKill(text)) return { block: true, reason: REASON };
		const reason = githubWriteReason(text);
		return reason ? { block: true, reason } : {};
	});
}
