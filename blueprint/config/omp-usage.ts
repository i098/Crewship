import { execFile, execFileSync, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { writeSync } from "node:fs";
import { isAbsolute } from "node:path";
import type { AssistantMessage, AssistantMessageEventStream } from "@oh-my-pi/pi-ai";

type Kind = "chat" | "judgment" | "helper";
type Metadata = { provider: string; model: string; producer_kind: Kind };
type Row = Record<string, unknown> & { at: string };
type Source = {
	producer: string;
	registration: Row;
	registered: boolean;
	sequence: number;
	gap?: string;
	pending: Row[];
	inflight: Row[];
};
const sources = new Map<Kind, Source>();
const collectors = new Set<ChildProcess>();

function command(action = "collect") {
	const collector = process.env.CREWSHIP_USAGE_COLLECTOR;
	const data = process.env.CREWSHIP_USAGE_DATA_DIR;
	const mount = process.env.CREWSHIP_USAGE_MOUNT;
	if (!collector || !isAbsolute(collector) || !data || !isAbsolute(data) || !mount || !isAbsolute(mount))
		throw new Error("usage metadata configuration is incomplete");
	return ["-I", collector, "--data-dir", data, "--mount", mount,
		"--store", process.env.CREWSHIP_USAGE_STORE ?? "spool", action];
}

function send(rows: Row[]) {
	return new Promise<void>((resolve, reject) => {
		const child = execFile("python3", command(), {
			encoding: "utf8", maxBuffer: 16384,
			env: { PATH: process.env.PATH ?? "/usr/bin:/bin", LANG: "C.UTF-8" },
		}, (error, stdout) => {
			clearTimeout(timeout);
			collectors.delete(child);
			try {
				if (error) throw error;
				const replies = stdout.trim().split("\n").map(line => JSON.parse(line));
				if (replies.length !== rows.length || replies.some(reply => reply?.accepted !== true))
					throw new Error("usage metadata delivery failed");
				resolve();
			} catch (error) { reject(error); }
		});
		const timeout = setTimeout(() => child.kill("SIGKILL"), 15000).unref();
		collectors.add(child);
		child.unref();
		for (const stream of child.stdio) (stream as { unref?: () => void } | null)?.unref?.();
		child.stdin!.on("error", reject);
		child.stdin!.end(rows.map(row => JSON.stringify(row)).join("\n") + "\n");
	});
}

async function flush(source: Source) {
	if (source.inflight.length) return;
	while (source.pending.length) {
		const rows = source.pending.splice(0);
		const gap = source.gap;
		source.gap = undefined;
		source.inflight = gap ? [{ schema: 1, kind: "gap", producer: source.producer,
			event: randomUUID(), at: gap, end: rows[0].at, reason: "delivery" }, ...rows] : rows;
		try {
			if (!source.registered) {
				await send([source.registration]);
				source.registered = true;
			}
			await send(source.inflight);
		} catch {
			source.gap = gap ?? rows[0].at;
			source.pending.length = 0;
			process.stderr.write("usage metadata delivery failed; coverage is unknown\n");
		}
		source.inflight = [];
	}
}

function record(source: Source, kind: string, event: string, at: string, fields = {}) {
	// ponytail: keep at most 64 waiting records; use durable IPC if this limit drops useful coverage.
	if (source.pending.length >= 64) {
		source.gap ??= source.pending[0].at;
		source.pending.length = 0;
	}
	source.pending.push({ schema: 1, kind, producer: source.producer, event, at, ...fields });
	void flush(source);
}

function sourceFor(kind: Kind): Source {
	if (kind !== "chat" && kind !== "judgment" && kind !== "helper")
		throw new Error("usage metadata producer kind is invalid");
	let source = sources.get(kind);
	if (!source) {
		const producer = randomUUID();
		source = { producer, sequence: 0, registered: false, pending: [], inflight: [], registration: {
			schema: 1, kind: "register", producer, event: randomUUID(), at: new Date().toISOString(),
			producer_kind: kind,
		} };
		sources.set(kind, source);
	}
	return source;
}

export function capture(metadata: Metadata, run: () => AssistantMessageEventStream) {
	const source = sourceFor(metadata.producer_kind);
	const event = randomUUID();
	const sequence = ++source.sequence;
	record(source, "start", event, new Date().toISOString(), {
		sequence, provider: metadata.provider, model: metadata.model,
	});
	let settled = false;
	function finish(message?: AssistantMessage, failure?: "error") {
		if (settled) return;
		const usage = message?.usageMetadata;
		const stop = message?.stopReason;
		const outcome = failure ?? (stop === "error" || stop === "aborted" ? stop
			: stop === "stop" || stop === "length" || stop === "toolUse" ? "success" : "unknown");
		record(source, "complete", event, new Date().toISOString(), {
			sequence, outcome, usage_present: usage === undefined ? null : usage !== null,
			input_basis: usage?.input_basis ?? "unknown",
			input: usage?.input ?? null, cache_read: usage?.cache_read ?? null,
			cache_write: usage?.cache_write ?? null, output: usage?.output ?? null,
			reasoning: usage?.reasoning ?? null,
		});
		settled = true;
		record(source, "checkpoint", randomUUID(), new Date().toISOString(), { sequence: source.sequence });
	}
	let stream: AssistantMessageEventStream;
	try { stream = run(); } catch (error) { finish(undefined, "error"); throw error; }
	void stream.result().then(
		(message: AssistantMessage) => finish(message),
		() => finish(undefined, "error"),
	).catch(() => {});
	return stream;
}

setInterval(() => {
	for (const source of sources.values())
		record(source, "checkpoint", randomUUID(), new Date().toISOString(), { sequence: source.sequence });
}, 60_000).unref();

process.once("exit", () => {
	for (const child of collectors) child.kill("SIGKILL");
	if (!sources.size) return;
	const rows: Row[] = [];
	const at = new Date().toISOString();
	for (const source of sources.values()) {
		if (source.gap || source.inflight.length || source.pending.length)
			rows.push({ schema: 1, kind: "gap", producer: source.producer, event: randomUUID(),
				at: source.gap ?? source.inflight[0]?.at ?? source.pending[0]?.at ?? at,
				end: at, reason: "shutdown" });
		rows.push({ schema: 1, kind: "shutdown", producer: source.producer,
			event: randomUUID(), at, sequence: source.sequence });
	}
	try {
		execFileSync("python3", command("shutdown"), {
			input: JSON.stringify(rows), timeout: 1000, killSignal: "SIGKILL",
			stdio: ["pipe", "ignore", "ignore"],
			env: { PATH: process.env.PATH ?? "/usr/bin:/bin", LANG: "C.UTF-8" },
		});
	} catch {
		try { writeSync(2, "usage metadata delivery failed at shutdown; coverage is unknown\n"); } catch {}
	}
});
