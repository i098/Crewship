/**
 * Starts a turn when an owner note or queued wake waits in an idle firstmate home.
 *
 * Why: omp resumes queued follow-ups on an idle session only while the context
 * tail is an assistant or toolResult message (AgentSession#canAutoContinueForFollowUp).
 * After a context compaction the session-start digest lands as a custom message
 * and becomes the tail, so every later watcher wake (pi.sendUserMessage with
 * deliverAs "followUp") stays queued and no turn starts. On 2026-11-06 that left
 * main silent 22:36Z-23:20Z with 8 owner texts unanswered, until a text typed
 * into the pane started a turn.
 *
 * What: it watches the home's state/inbox directory and state/.wake-queue with
 * fs.watch (events, no polling timer). When either holds something older than
 * GRACE_MS and the session is idle, it sends one plain user message. That starts
 * a prompt turn, which drains the stranded follow-ups. The next resend waits
 * RESEND_MS. Every wake appends a line to state/.stranded-wake.log for the desk.
 *
 * Active only for a non-subagent session whose cwd holds bin/fm-wake-drain.sh and
 * state/inbox; any other omp session ignores it.
 */
import { appendFileSync, existsSync, readdirSync, statSync, watch, type FSWatcher } from "node:fs";
import { join } from "node:path";

export const GRACE_MS = 45_000;
export const RESEND_MS = 300_000;

interface Ctx {
	cwd?: string;
	agent?: { kind?: string };
	isIdle?: () => boolean;
}
interface Api {
	on(event: string, handler: (event: unknown, ctx: Ctx) => unknown): void;
	sendUserMessage(text: string): unknown;
}

/** Oldest waiting item in the home as an epoch-ms mtime, with a count; undefined when nothing waits. */
export function oldestWaiting(home: string): { since: number; notes: number; queued: boolean } | undefined {
	const state = join(home, "state");
	let since = Infinity;
	let notes = 0;
	let queued = false;
	try {
		for (const name of readdirSync(join(state, "inbox"))) {
			if (!name.endsWith(".note")) continue;
			notes++;
			since = Math.min(since, statSync(join(state, "inbox", name)).mtimeMs);
		}
	} catch {
		// inbox vanished between readdir and stat; the next event rescans
	}
	try {
		const q = statSync(join(state, ".wake-queue"));
		if (q.size > 0) {
			queued = true;
			since = Math.min(since, q.mtimeMs);
		}
	} catch {
		// no queue file: nothing queued
	}
	return notes > 0 || queued ? { since, notes, queued } : undefined;
}

export default function (pi: Api) {
	let home = "";
	let ctx: Ctx | undefined;
	let timer: NodeJS.Timeout | undefined;
	let lastSent = 0;
	const watchers: FSWatcher[] = [];

	function schedule(): void {
		if (timer) return;
		const waiting = home ? oldestWaiting(home) : undefined;
		if (!waiting) return;
		const due = Math.max(waiting.since + GRACE_MS, lastSent + RESEND_MS);
		timer = setTimeout(fire, Math.max(1000, due - Date.now()));
		timer.unref?.();
	}

	function fire(): void {
		timer = undefined;
		const waiting = home ? oldestWaiting(home) : undefined;
		if (!waiting) return;
		if (Date.now() - waiting.since >= GRACE_MS && ctx?.isIdle?.() === true) {
			lastSent = Date.now();
			try {
				appendFileSync(
					join(home, "state", ".stranded-wake.log"),
					`${Math.floor(lastSent / 1000)}\twoken\tnotes=${waiting.notes}\tqueue=${waiting.queued}\n`,
				);
			} catch {
				// the log is a courtesy for the desk; the wake matters more
			}
			pi.sendUserMessage(
				`STRANDED WAKE: ${waiting.notes} inbox note(s)${waiting.queued ? " and queued watcher wakes" : ""} waited over 45 s while this session was idle. ` +
					"omp did not start a turn for them. Run bin/fm-wake-drain.sh first and handle everything it prints.",
			);
		}
		schedule();
	}

	pi.on("session_start", (_event, c) => {
		if (c?.agent?.kind === "sub") return;
		const cwd = c?.cwd ?? process.cwd();
		if (!existsSync(join(cwd, "bin", "fm-wake-drain.sh")) || !existsSync(join(cwd, "state", "inbox"))) return;
		ctx = c;
		home = cwd;
		for (const w of watchers.splice(0)) w.close();
		try {
			watchers.push(watch(join(home, "state", "inbox"), schedule));
			watchers.push(watch(join(home, "state"), (_kind, name) => name === ".wake-queue" && schedule()));
		} catch {
			// no watch support: the session-start scan below still covers a note that already waits
		}
		schedule();
	});
	pi.on("session_shutdown", () => {
		for (const w of watchers.splice(0)) w.close();
		clearTimeout(timer);
		timer = undefined;
		home = "";
	});
	// Compaction rebuilds the tail; rescan so a note that arrived mid-compaction is timed.
	pi.on("session_compact", () => schedule());
}
