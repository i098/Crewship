import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { isAbsolute } from "node:path";
import type { AssistantMessage, AssistantMessageEventStream } from "@oh-my-pi/pi-ai";

type Kind = "chat" | "judgment" | "helper";
type Metadata = { provider: string; model: string; producer_kind: Kind };
type Source = {
	producer: string;
	registration: Record<string, unknown>;
	registered: boolean;
	sequence: number;
	gap?: string;
};
const sources = new Map<Kind, Source>();

function command() {
	const collector = process.env.CREWSHIP_USAGE_COLLECTOR;
	const data = process.env.CREWSHIP_USAGE_DATA_DIR;
	const mount = process.env.CREWSHIP_USAGE_MOUNT;
	if (!collector || !isAbsolute(collector) || !data || !isAbsolute(data) || !mount || !isAbsolute(mount))
		throw new Error("usage metadata configuration is incomplete");
	return ["-I", collector, "--data-dir", data, "--mount", mount,
		"--store", process.env.CREWSHIP_USAGE_STORE ?? "spool", "collect"];
}

function send(source: Source, row: Record<string, unknown>) {
	// ponytail: one process per durable acknowledgement; use persistent IPC if measured throughput needs it.
	const result = spawnSync("python3", command(), {
		input: JSON.stringify(row) + "\n", encoding: "utf8", timeout: 15000, maxBuffer: 8192,
		env: { PATH: process.env.PATH ?? "/usr/bin:/bin", LANG: "C.UTF-8" },
	});
	let acknowledged = false;
	if (result.status === 0) {
		try {
			const reply: unknown = JSON.parse(result.stdout);
			acknowledged = reply !== null && typeof reply === "object"
				&& "accepted" in reply && reply.accepted === true;
		} catch {}
	}
	if (!acknowledged) {
		source.gap ??= new Date().toISOString();
		throw new Error("usage metadata delivery failed");
	}
}

function record(source: Source, kind: string, event: string, at: string, fields = {}) {
	if (source.gap) {
		send(source, { schema: 1, kind: "gap", producer: source.producer, event: randomUUID(),
			at: source.gap, end: at, reason: "delivery" });
		source.gap = undefined;
	}
	send(source, { schema: 1, kind, producer: source.producer, event, at, ...fields });
}

function sourceFor(kind: Kind): Source {
	if (kind !== "chat" && kind !== "judgment" && kind !== "helper")
		throw new Error("usage metadata producer kind is invalid");
	let source = sources.get(kind);
	if (!source) {
		const producer = randomUUID();
		source = { producer, sequence: 0, registered: false, registration: {
			schema: 1, kind: "register", producer, event: randomUUID(), at: new Date().toISOString(),
			producer_kind: kind,
		} };
		sources.set(kind, source);
	}
	if (!source.registered) {
		send(source, source.registration);
		source.registered = true;
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
	const completed = stream.result().then(
		(message: AssistantMessage) => { finish(message); return message; },
		(error: unknown) => { finish(undefined, "error"); throw error; },
	);
	completed.catch(() => {});
	stream.finalResultPromise = completed;
	const iterator = stream[Symbol.asyncIterator].bind(stream);
	stream[Symbol.asyncIterator] = async function* () {
		try {
			for await (const item of { [Symbol.asyncIterator]: iterator }) {
				if (item.type === "done" || item.type === "error") await completed;
				yield item;
			}
			await completed;
		} catch (error) { await completed; throw error; }
	};
	return stream;
}

setInterval(() => {
	for (const kind of sources.keys()) {
		try {
			const source = sourceFor(kind);
			record(source, "checkpoint", randomUUID(), new Date().toISOString(), { sequence: source.sequence });
		} catch {
			process.stderr.write("usage metadata checkpoint acknowledgement failed\n");
		}
	}
}, 60_000).unref();

process.on("exit", () => {
	for (const source of sources.values()) {
		if (!source.registered) continue;
		try {
			record(source, "shutdown", randomUUID(), new Date().toISOString(), { sequence: source.sequence });
		} catch {
			process.stderr.write("usage metadata shutdown acknowledgement failed\n");
			process.exitCode = 1;
		}
	}
});
