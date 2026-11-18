// The desk's view of an omp selection prompt on a supervisor pane, read and answered through herdr (the multiplexer the
// bridge already polls in herdr-watch.ts). Pure parsing and checks here; the bridge supplies `run`, so tests need no herdr.
import { createHash } from "node:crypto";
import { deniedTopic } from "./desk-deny.ts";

export type PanePrompt = { id: string; title: string; options: string[]; selected: number; raw: string; unclear?: string }; // raw: the title and every option line, descriptions too

// omp's selector (HookSelectorComponent) draws: title lines, a blank line, the options (the selected one behind a cursor glyph,
// the others two columns in, a description deeper), a blank line and the hint "navigate / select / cancel".
const HINT = /\bnavigate\b.*\bselect\b.*\bcancel\b/i;
const CURSOR = /^\s*[❯›▸▶→➜>]\s/u;
const COUNTER = /^\s*\(\d+\/\d+\)/;
const MARKED = /^(?:\[[ xX]\]|[☐☑◯◉○●])\s/u;
const TITLE_LINES = 5;

const idOf = (title: string, lines: string[]) => createHash("sha1").update(`${title}\n${lines.join("\n")}`).digest("hex").slice(0, 8);

// The title: up to TITLE_LINES non-blank lines above the options, stopping at two blank lines in a row.
function titleAbove(lines: string[], start: number): string[] {
  const title: string[] = [];
  for (let i = start - 1, blanks = 0; i >= 0 && title.length < TITLE_LINES && blanks < 2; i--) {
    if (lines[i]) { title.unshift(lines[i]!.trim()); blanks = 0; } else blanks++;
  }
  return title;
}

// The option labels in the block and the index of the one under the cursor (-1 when no cursor shows).
function optionsOf(block: string[]): { options: string[]; selected: number } {
  const cursor = block.findIndex((line) => CURSOR.test(line));
  if (cursor < 0) return { options: [], selected: -1 };
  const label = CURSOR.exec(block[cursor]!)![0].length;
  const options: string[] = [];
  let selected = -1;
  block.forEach((line, i) => {
    if (i === cursor) { selected = options.length; options.push(line.slice(label).trim()); } else if (line.length - line.trimStart().length === label) options.push(line.trim());
  });
  return { options, selected };
}

function unclearReason(block: string[], options: string[], selected: number): string | undefined {
  if (block.some((line) => COUNTER.test(line))) return "the list is scrolled";
  if (selected < 0) return "no selected option is visible";
  if (options.length < 2) return "fewer than two options";
  if (options.some((option) => MARKED.test(option))) return "a multiple choice";
  return undefined;
}

// The prompt open at the bottom of a pane's visible text, or undefined when no selector hint is there.
// A prompt the bridge cannot read exactly (a scrolled list, no cursor, one option, checkboxes) comes back with `unclear` set.
export function parsePrompt(screen: string): PanePrompt | undefined {
  const lines = screen.split("\n").map((line) => line.trimEnd());
  const hint = lines.findLastIndex((line) => HINT.test(line));
  if (hint < 0) return undefined;
  let end = hint - 1;
  while (end >= 0 && !lines[end]) end--;
  let start = end;
  while (start > 0 && lines[start - 1]) start--;
  const block = lines.slice(start, end + 1);
  const title = titleAbove(lines, start);
  const { options, selected } = optionsOf(block);
  const text = title.join("\n");
  return { id: idOf(text, options.length ? options : block), title: text || block.join(" "), options, selected, raw: [...title, ...block].join("\n"), unclear: unclearReason(block, options, selected) };
}

// Why the desk must not answer this prompt, or undefined. The title, every option and the descriptions count.
export function promptRefusal(p: PanePrompt): string | undefined {
  return p.unclear ?? deniedTopic(p.raw);
}

// Arrow keys that move the cursor to option `n` (1-based); Enter is sent separately, after the cursor is checked.
export function keysTo(p: PanePrompt, n: number): string[] {
  const delta = n - 1 - p.selected;
  return Array<string>(Math.abs(delta)).fill(delta > 0 ? "down" : "up");
}

export const promptList = (p: PanePrompt) => p.options.map((option, i) => `${i + 1}. ${option}`).join("\n");

// The pane id of the one agent whose `who` token is the supervisor (`main`) or the second mate; `herdr agent list` output.
export function paneId(json: string, who: string): string {
  const agents: unknown = JSON.parse(json)?.result?.agents;
  if (!Array.isArray(agents)) throw new Error("herdr agent list: no agents array");
  const found = agents.filter((a) => a?.tokens?.who === (who === "main" ? "firstmate" : who) && typeof a?.pane_id === "string");
  if (found.length !== 1) throw new Error(`${found.length ? "more than one pane" : "no pane"} for ${who}`);
  return found[0].pane_id;
}

export type Run = (cmd: string[]) => Promise<string>; // stdout; rejects on a non-zero exit

export function paneIO(run: Run, bin: string) {
  const pane = async (who: string) => paneId(await run([bin, "agent", "list"]), who);
  return {
    read: async (who: string) => run([bin, "pane", "read", await pane(who), "--source", "visible"]),
    press: async (who: string, keys: string[]) => {
      await run([bin, "pane", "send-keys", await pane(who), ...keys]);
      await Bun.sleep(400); // omp redraws after the keys
    },
  };
}
