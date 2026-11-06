import { existsSync, readFileSync, statSync, watch, type FSWatcher } from "node:fs";

// The omp extension fm-stranded-wake.ts appends "<epoch>\twoken\tnotes=N\tqueue=bool" to state/.stranded-wake.log
// when it starts a turn in an idle main. This turns each new line into one honest owner text, at most one per cooldown.
export const WAKE_NOTICE_COOLDOWN_MS = 30 * 60_000;

export function wakeNotice(lines: string[]): string | undefined {
  const notes = lines.map((l) => /\twoken\tnotes=(\d+)/.exec(l)).filter((m) => m).map((m) => Number(m![1]));
  if (!notes.length) return undefined;
  const n = Math.max(...notes);
  return `Main was idle and ${n > 0 ? `${n} of your note${n > 1 ? "s were" : " was"}` : "a queued wake was"} waiting, so I woke it. It should answer in a minute.`;
}

/** Watches the wake log; `send` gets the text. Returns the watcher, or undefined when the state folder is missing. */
export function watchStrandedWake(log: string, send: (text: string) => void, now = Date.now): FSWatcher | undefined {
  let offset = existsSync(log) ? statSync(log).size : 0;
  let lastSent = -Infinity;
  const read = () => {
    if (!existsSync(log)) return;
    const size = statSync(log).size;
    if (size < offset) offset = 0;
    if (size === offset) return;
    const text = readFileSync(log, "utf8").slice(offset);
    offset = size;
    const notice = wakeNotice(text.split("\n").filter(Boolean));
    if (notice && now() - lastSent >= WAKE_NOTICE_COOLDOWN_MS) {
      lastSent = now();
      send(notice);
    }
  };
  const dir = log.slice(0, log.lastIndexOf("/"));
  return existsSync(dir) ? watch(dir, (_event, name) => { if (name === ".stranded-wake.log") read(); }) : undefined;
}
