/**
 * Refuses pattern-based process kills and ambiguous GitHub issue writes.
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
const BOOL_FLAGS: Record<string, true> = {
	"--help": true, "--web": true, "-w": true, "--editor": true, "-e": true,
	"--yes": true, "-y": true, "--verify": true, "--undo": true, "--remove": true,
	"--confirm": true, "--paginate": true, "--slurp": true, "--include": true, "-i": true,
	"--silent": true, "--verbose": true, "--full": true, "--no-type": true,
	"--allow-escape-sequences": true, "--remove-milestone": true, "--remove-parent": true,
	"--remove-type": true, "--edit-last": true, "--create-if-none": true,
	"--delete-last": true, "--checkout": true, "--list": true,
};
const VALUE_FLAGS: Record<string, true> = {
	"--repo": true, "--method": true, "--field": true, "--raw-field": true,
	"--header": true, "--preview": true, "--input": true, "--jq": true, "--template": true,
	"--cache": true, "--hostname": true, "--title": true, "--body": true, "--body-file": true,
	"--assignee": true, "--label": true, "--milestone": true, "--project": true,
	"--type": true, "--reason": true, "--comment": true, "--to-repo": true,
	"--parent": true, "--add-sub-issue": true, "--remove-sub-issue": true,
	"--add-blocked-by": true, "--remove-blocked-by": true, "--add-blocking": true,
	"--remove-blocking": true, "--add-assignee": true, "--remove-assignee": true,
	"--add-label": true, "--remove-label": true, "--add-project": true,
	"--remove-project": true, "--lock-reason": true, "--recover": true, "--attach": true,
	"--base": true, "--name": true, "--branch-repo": true, "-t": true, "-b": true,
	"-a": true, "-l": true, "-m": true, "-p": true, "-q": true, "-T": true,
	"-P": true, "-B": true, "-n": true,
};
const RELATION_FLAGS = [
	"--parent", "--add-sub-issue", "--remove-sub-issue", "--add-blocked-by",
	"--remove-blocked-by", "--add-blocking", "--remove-blocking",
];
const TARGET_REQUIRED =
	"Blocked: GitHub issue writes need an explicit repository target. Use -R owner/repo, " +
	"a supported issue URL, or a literal repos/owner/repo/issues API path. " +
	"GraphQL issue writes and unresolved relationship writes require " +
	"CREWSHIP_GITHUB_APPROVED_REPO after explicit approval.";

type GithubArgs = { positionals: string[]; flags: Record<string, string[]>; uncertain: boolean };
type ShellWord = { value: string; operator: boolean };

function shellWords(command: string): ShellWord[] {
	const words = command.replace(/\\\r?\n/g, "").match(/#[^\n]*|[0-9]*(?:>&|<&|<>|>>?|<<<?)|&>>?|(?:[^\s'"\\;&|()<>`]+|\\[\s\S]|"(?:\\[\s\S]|[^"\\])*"|'[^']*')+|[;&|()\n`]/g) ?? [];
	return words.filter((word) => !word.startsWith("#")).map((word) => ({
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

function githubArgs(words: string[], cli: string): GithubArgs {
	const positionals: string[] = [];
	const flags: Record<string, string[]> = {};
	let uncertain = false;
	const aliases: Record<string, string> = {
		"-R": "--repo", "-X": "--method", "-f": "--raw-field", "-F": "--field", "-H": "--header",
		"-h": "--help", "-c": "--comment",
	};
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
		const flag = word.match(/^(--[^=]+|-[a-zA-Z])(?:=(.*)|(.+))?$/);
		let name = aliases[flag?.[1] ?? word] ?? flag?.[1] ?? word;
		if (cli === "gh" && positionals[0] === "issue" && positionals[1] === "develop") {
			if (flag?.[1] === "-c") name = "--checkout";
			if (flag?.[1] === "-l") name = "--list";
		}
		if (cli === "gh-axi" && name === "--help" && word !== "--help") continue;
		const attached = flag?.[2] ?? flag?.[3];
		let value: string;
		if (BOOL_FLAGS[name]) {
			value = attached ?? "true";
			if (!/^(true|false|1|0|t|f)$/i.test(value)) uncertain = true;
		} else if (VALUE_FLAGS[name]) {
			value = attached ?? words[++i] ?? "";
		} else {
			uncertain = true;
			continue;
		}
		(flags[name] ??= []).push(value);
	}
	return { positionals, flags, uncertain };
}

function literalRepo(value: string): string {
	return /^[\w.-]+\/[\w.-]+$/.test(value) ? value.toLowerCase() : "";
}

function urlRepo(value: string): string {
	const match = value.match(/^https?:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/(?:issues|pull)\/\d+/);
	return match?.[1].toLowerCase() ?? "";
}

function graphqlTargets(flags: GithubArgs["flags"]): string[] {
	const queries = [...(flags["--field"] ?? []), ...(flags["--raw-field"] ?? [])]
		.filter((field) => field.startsWith("query=")).map((field) => field.slice(6));
	const opaque = flags["--input"] || queries.length !== 1 || /^\s*[@$`]/.test(queries[0]);
	if (!opaque) {
		const query = queries[0].replace(/"""[\s\S]*?"""|"(?:\\[\s\S]|[^"\\])*"|#[^\n]*/g, "");
		const issueField = /\b(?:\w*Issue\w*|(?:create|delete)LinkedBranch|addComment|(?:un)?minimizeComment|clearLabelsFromLabelable|replaceActorsForAssignable|(?:add|remove)(?:BlockedBy|Blocking|RelatesTo|Reaction|LabelsToLabelable|LabelsFromLabelable|AssigneesToAssignable|AssigneesFromAssignable)|(?:un)?lockLockable|(?:add|delete|update)ProjectV2Item\w*)\s*[\({]/;
		if (/^\s*(?:query\b|\{)/.test(query) && !/\bmutation\b/.test(query)) return [];
		if (/\bmutation\b/.test(query) && !issueField.test(query)) return [];
	}
	return [literalRepo(process.env.CREWSHIP_GITHUB_APPROVED_REPO ?? "")];
}

function apiTargets(args: GithubArgs, cli: string): string[] {
	const { positionals, flags } = args;
	if (args.uncertain) return [""];
	const positionalMethod = cli === "gh-axi" && /^(GET|HEAD|POST|PATCH|PUT|DELETE)$/i.test(positionals[1] ?? "");
	const endpoint = positionals[positionalMethod ? 2 : 1] ?? "";
	const path = endpoint.replace(/^https:\/\/api\.github\.com\//, "").replace(/^\//, "");
	if (/^graphql(?:[?#]|$)/.test(path)) {
		return /[?#]/.test(path) ? [literalRepo(process.env.CREWSHIP_GITHUB_APPROVED_REPO ?? "")] : graphqlTargets(flags);
	}
	const payload = flags["--field"] || flags["--raw-field"] || flags["--input"];
	const method = flags["--method"]?.at(-1) ??
		(positionalMethod ? positionals[1] : payload && cli === "gh" ? "POST" : "GET");
	if (/^(GET|HEAD|OPTIONS)$/i.test(method)) return [];
	if (!/^(POST|PATCH|PUT|DELETE)$/i.test(method)) return [""];
	if (!endpoint) return [""];
	const resource = path.match(/^repos\/(?:[\w.-]+|\{owner\})\/(?:[\w.-]+|\{repo\})\/([\w-]+)(?:[/?#]|$)/)?.[1];
	if (resource && resource !== "issues") return [];
	if (!/(?:^|\/)issues(?:[/?#]|$)/.test(endpoint) && !/[$`{]/.test(endpoint)) return [];
	const match = path.match(/^repos\/([\w.-]+\/[\w.-]+)\/issues(?:[/?#]|$)/);
	const targets = [match?.[1].toLowerCase() ?? ""];
	if (/\/issues\/[^/?#]+\/(?:parent|sub_issues?|dependencies)(?:[/?#]|$)/.test(path)) {
		targets.push(literalRepo(process.env.CREWSHIP_GITHUB_APPROVED_REPO ?? ""));
	}
	return targets;
}

function relationshipTargets({ flags, positionals }: GithubArgs, cli: string): string[] {
	const targets: string[] = [];
	for (const name of RELATION_FLAGS) {
		for (const value of (flags[name] ?? []).flatMap((field) => field.split(","))) {
			if (!/^#?\d+$/.test(value)) targets.push(urlRepo(value));
		}
	}
	if (cli === "gh" && positionals[1] === "edit" && (
		/^(true|1|t)$/i.test(flags["--remove-parent"]?.at(-1) ?? "") ||
		flags["--parent"]?.some(Boolean) || flags["--add-sub-issue"]?.some(Boolean)
	)) targets.push(literalRepo(process.env.CREWSHIP_GITHUB_APPROVED_REPO ?? ""));
	return targets;
}

function mutationTargets(args: GithubArgs, cli: string): string[] {
	const { positionals, flags } = args;
	const [kind, operation, selector] = positionals;
	const subissueWrite = cli === "gh-axi" && operation === "subissue" && /^(add|remove)$/.test(selector);
	if (kind !== "issue" || (!ISSUE_WRITES[operation] && !subissueWrite)) return [];
	if (args.uncertain) return [""];
	if (cli === "gh" && operation === "develop" && /^(true|1|t)$/i.test(flags["--list"]?.at(-1) ?? "")) return [];
	const targets = (flags["--repo"] ?? []).map(literalRepo);
	const selectors = operation === "create" || operation === "new" ? [] :
		positionals.slice(subissueWrite ? 3 : 2, operation === "transfer" ? 3 : undefined);
	for (const value of selectors) {
		if (/^#?\d+$/.test(value)) continue;
		targets.push(cli === "gh" ? urlRepo(value) : "");
	}
	if (targets.length === 0) targets.push("");
	targets.push(...relationshipTargets(args, cli));
	if (operation === "transfer") {
		const destination = cli === "gh-axi" ? flags["--to-repo"]?.at(-1) : positionals[3];
		targets.push(literalRepo(destination ?? ""));
	}
	return targets;
}

function checkGithubWrite(words: string[], cli: string): string {
	const args = githubArgs(words, cli);
	if (!args.uncertain && /^(true|1|t)$/i.test(args.flags["--help"]?.at(-1) ?? "")) return "";
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
		if (/^(?:bash|sh|zsh)$/.test(cli)) {
			const args = commandArgs(words, i + 1);
			let commandString = false;
			for (let j = 0; j < args.length; j++) {
				const arg = args[j];
				if (arg === "--" || !/^[+-].+/.test(arg)) {
					if (commandString) {
						const reason = githubWriteReason(args[arg === "--" ? j + 1 : j] ?? "");
						if (reason) return reason;
					}
					break;
				}
				if (/^-[^-]*c/.test(arg)) commandString = true;
				if (/^(?:--rcfile|--init-file|[+-][^-]*[oO])$/.test(arg) && !/^[+-]/.test(args[j + 1] ?? "")) j++;
			}
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
