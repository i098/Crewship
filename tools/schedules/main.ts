import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { parseArgs } from "node:util";
import type { Subprocess } from "bun";
import {
  BoxRenderable, createCliRenderer, RGBA, StyledText, TextAttributes, TextRenderable,
  type CliRenderer, type KeyEvent, type TextChunk,
} from "@opentui/core";

type Column = "name" | "schedule" | "next" | "last" | "result" | "owner" | "purpose";
type Row = {
  name: string; source: string; owner: string; command: string; unit?: string;
  stale: boolean; kind: "ok" | "running" | "failed" | "unknown";
  display: Record<Column, string>; summary: string[]; properties: string[];
};
type Snapshot = {
  rows: Row[]; errors: Record<string, string>;
  saved: Record<string, unknown>; owners: Record<string, string>;
};
const colors = {
  background: RGBA.fromHex("#111c1c"), text: RGBA.fromHex("#c6d1cc"),
  muted: RGBA.fromHex("#788b85"), selected: RGBA.fromHex("#294337"),
  ok: RGBA.fromHex("#b4d98b"), failed: RGBA.fromHex("#ed8a8a"),
  running: RGBA.fromHex("#e6cf83"), unknown: RGBA.fromHex("#788b85"),
};
const columns: Column[] = ["name", "schedule", "next", "last", "result", "owner", "purpose"];
const collector = existsSync(join(import.meta.dir, "collector.py"))
  ? join(import.meta.dir, "collector.py")
  : resolve(import.meta.dir, "../../blueprint/maintenance/crewship-schedules.py");
const safe = (value: string) => value.replace(/[\p{Cc}\p{Cf}]/gu,
  (char) => JSON.stringify(char).slice(1, -1));
const chunk = (text: string, fg = colors.text, bg = colors.background, attributes = 0): TextChunk =>
  ({ __isChunk: true, text, fg, bg, attributes });

function fit(value: string, width: number): string {
  let result = "", used = 0;
  for (const char of value) {
    const size = Bun.stringWidth(char);
    if (used + size > width) break;
    result += char;
    used += size;
  }
  return result + " ".repeat(Math.max(0, width - used));
}

function layout(width: number): [Column, number][] {
  if (width >= 120) return [
    ["name", 22], ["schedule", 16], ["next", 11], ["last", 11],
    ["result", 13], ["owner", 18], ["purpose", width - 110],
  ];
  if (width >= 75) return [["name", 23], ["result", 14], ["owner", 17], ["purpose", width - 64]];
  return [["name", Math.max(1, width - 22)], ["result", 18]];
}

function rowChunks(row: Row, fields: [Column, number][], selected: boolean, stale: boolean): TextChunk[] {
  const background = selected ? colors.selected : colors.background;
  const result: TextChunk[] = [];
  fields.forEach(([key, width], index) => {
    if (index) result.push(chunk(" │ ", colors.muted, background));
    let value = row.display[key];
    if (key === "result" && stale && !row.stale) value = "STALE " + value;
    const color = key === "result" ? colors[row.kind] : value === "-" ? colors.muted : colors.text;
    result.push(chunk(fit(value, width), color, background));
  });
  result.push(chunk("\n"));
  return result;
}

class SchedulesView {
  private snapshot: Snapshot = { rows: [], errors: {}, saved: {}, owners: {} };
  private selected = 0;
  private expanded = true;
  private properties = false;
  private editing = false;
  private search = "";
  private source = "All";
  private owner = "All";
  private journal: string[] = [];
  private busy = false;
  private failure = "";
  private closed = false;
  private child?: Subprocess<"pipe", "pipe", "pipe">;
  private title: TextRenderable;
  private filters: TextRenderable;
  private errors: TextRenderable;
  private table: TextRenderable;
  private panel: BoxRenderable;
  private details: TextRenderable;
  private help: TextRenderable;

  constructor(private renderer: CliRenderer, private args: string[]) {
    const root = new BoxRenderable(renderer, {
      width: "100%", height: "100%", flexDirection: "column", backgroundColor: colors.background,
    });
    renderer.root.add(root);
    const label = (height: number, fg = colors.text) => {
      const node = new TextRenderable(renderer, { height, width: "100%", fg, wrapMode: "none", truncate: true });
      root.add(node);
      return node;
    };
    this.title = label(1, colors.ok);
    this.title.attributes = TextAttributes.BOLD;
    this.filters = label(1);
    this.errors = label(0, colors.failed);
    this.table = label(1);
    this.panel = new BoxRenderable(renderer, {
      width: "100%", flexGrow: 1, minHeight: 0, border: ["top"], borderColor: colors.muted,
    });
    this.details = new TextRenderable(renderer, {
      width: "100%", height: "100%", fg: colors.text, wrapMode: "word", selectable: false,
    });
    this.panel.add(this.details);
    root.add(this.panel);
    label(1, colors.muted).content = "Local login + system only; no other accounts, containers, remote hosts, or cron child scripts.";
    this.help = label(1, colors.ok);
    renderer.keyInput.on("keypress", (key) => this.handleKey(key));
    renderer.on("resize", () => this.draw());
    this.draw();
  }

  cancel() {
    this.closed = true;
    this.child?.kill();
  }

  private visible(): Row[] {
    const query = this.search.toLowerCase();
    return this.snapshot.rows.filter((row) =>
      (this.source === "All" || row.source === this.source) &&
      (this.owner === "All" || row.owner === this.owner) &&
      [...columns.map((key) => row.display[key]), row.source, ...row.summary].join(" ").toLowerCase().includes(query));
  }

  private async collect(args: string[], input: unknown): Promise<unknown> {
    const child = Bun.spawn(["python3", collector, ...args], {
      stdin: "pipe", stdout: "pipe", stderr: "pipe", timeout: 75_000,
    });
    this.child = child;
    child.stdin.write(JSON.stringify(input));
    child.stdin.end();
    const [output, error, code] = await Promise.all([
      new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited,
    ]);
    if (this.child === child) this.child = undefined;
    if (code !== 0) throw new Error(error.trim() || `Collector exited ${code}`);
    return JSON.parse(output);
  }

  async refresh() {
    if (this.busy || this.closed) return;
    this.busy = true;
    this.journal = [];
    this.draw();
    try {
      this.snapshot = await this.collect(this.args, this.snapshot) as Snapshot;
      this.failure = "";
    } catch (error) {
      this.failure = safe(String(error));
    } finally {
      this.busy = false;
      this.draw();
    }
  }

  private async readJournal(row: Row) {
    if (!row.unit || this.busy) return;
    this.busy = true;
    this.draw();
    let lines: string[];
    try {
      const args = ["--journal", row.unit, ...(row.source === "user timer" ? ["--user"] : [])];
      const result = await this.collect(args, {}) as { journal: string[] };
      lines = ["Journal (last 40 lines):", ...result.journal];
    } catch (error) {
      lines = ["Journal read error: " + safe(String(error))];
    }
    if (this.visible()[this.selected] === row) {
      this.journal = lines;
      this.properties = false;
      this.expanded = true;
      this.details.scrollY = 0;
    }
    this.busy = false;
    this.draw();
  }

  private draw() {
    if (this.closed) return;
    const rows = this.visible();
    this.selected = Math.min(this.selected, Math.max(0, rows.length - 1));
    this.title.content = `crewship schedules   READ ONLY · OpenTUI · ${rows.length}/${this.snapshot.rows.length} records${this.busy ? " · Reading…" : ""}`;
    this.filters.content = `${this.editing ? "Search: " : "/ "}${safe(this.search) || "Search name or purpose"} | Source: ${safe(this.source)} | Owner: ${safe(this.owner)}`;
    const errors = Object.keys(this.snapshot.errors).length;
    this.errors.visible = Boolean(this.failure || errors);
    this.errors.height = this.errors.visible ? 1 : 0;
    this.errors.content = this.failure || `${errors} source read errors. Select a Read error row for details.`;
    const available = Math.max(1, this.renderer.height - 6 - Number(this.errors.visible));
    const count = Math.min(Math.max(1, rows.length), this.expanded ? Math.max(1, Math.floor(available / 2)) : available);
    const fields = layout(this.renderer.width);
    const chunks = [chunk(fields.map(([key, size]) => fit(key[0].toUpperCase() + key.slice(1), size)).join(" │ ") + "\n", colors.text, colors.background, TextAttributes.BOLD)];
    const start = Math.max(0, this.selected - count + 1);
    rows.slice(start, start + count).forEach((row, index) => chunks.push(...rowChunks(row, fields, start + index === this.selected, Boolean(this.failure))));
    this.table.height = count + 1;
    this.table.content = new StyledText(chunks);
    this.panel.visible = this.expanded;
    this.drawDetails(rows[this.selected]);
    this.help.content = this.renderer.width >= 115
      ? "q quit  j/k select  Enter details  / search  s source  o owner  r refresh  p properties  J journal  PgUp/Dn scroll"
      : "q quit | j/k Enter / s o r p J PgUp/Dn";
  }

  private drawDetails(row?: Row) {
    const lines = row ? (this.journal.length ? [row.display.name, ...this.journal] : row.summary) : ["No matching schedules."];
    const content = lines.map((line, index) => chunk(line + "\n", index ? colors.text : colors.ok, colors.background, index ? 0 : TextAttributes.BOLD));
    if (row && this.properties) content.push(chunk("\nProperties:\n" + row.properties.join("\n")));
    this.details.content = new StyledText(content);
  }

  private clearSelection() {
    this.selected = 0;
    this.journal = [];
    this.properties = false;
    this.details.scrollY = 0;
  }

  private filter(key: string) {
    if (key === "escape") {
      this.search = "";
      this.source = this.owner = "All";
    } else {
      const field = key === "s" ? "source" : "owner";
      const values = ["All", ...new Set(this.snapshot.rows.map((row) => row[field]).sort())];
      this[field] = values[(values.indexOf(this[field]) + 1) % values.length];
    }
    this.clearSelection();
  }

  private editSearch(key: KeyEvent) {
    if (["return", "enter", "escape"].includes(key.name)) this.editing = false;
    else if (key.name === "backspace") this.search = Array.from(this.search).slice(0, -1).join("");
    else if (!key.ctrl && !key.meta && !/[\p{Cc}\p{Cf}]/u.test(key.sequence)) this.search += key.sequence;
    this.clearSelection();
  }

  private handleKey(key: KeyEvent) {
    const name = key.sequence.length === 1 && !/[\p{Cc}\p{Cf}]/u.test(key.sequence)
      ? key.sequence : key.name;
    if (this.editing) this.editSearch(key);
    else if (name === "q") { this.renderer.destroy(); return; }
    else if (["j", "k", "down", "up"].includes(name)) {
      const step = ["j", "down"].includes(name) ? 1 : -1;
      this.selected = Math.max(0, Math.min(this.selected + step, this.visible().length - 1));
      this.journal = [];
      this.details.scrollY = 0;
    } else if (["return", "enter"].includes(name)) this.expanded = !this.expanded;
    else if (name === "/") this.editing = true;
    else if (["s", "o", "escape"].includes(name)) this.filter(name);
    else if (name === "r") void this.refresh();
    else if (name === "p") {
      this.properties = !this.properties;
      this.expanded = true;
      this.journal = [];
      this.details.scrollY = 0;
    } else if (["pageup", "pagedown"].includes(name)) this.details.scrollY += name === "pagedown" ? 5 : -5;
    else if (name === "J") { const row = this.visible()[this.selected]; if (row) void this.readJournal(row); }
    this.draw();
  }
}

async function main() {
  const { values } = parseArgs({ options: {
    home: { type: "string" }, registry: { type: "string" }, help: { type: "boolean", short: "h" },
  } });
  if (values.help) {
    console.log("Usage: crewship schedules [--home DIR] [--registry FILE]\nRead-only OpenTUI schedule viewer. Keys: j/k, Enter, /, s, o, r, p, J, q.");
    return;
  }
  if (!process.stdin.isTTY || !process.stdout.isTTY) throw new Error("Open schedules in a terminal.");
  const args = [...(values.home ? ["--home", values.home] : []), ...(values.registry ? ["--registry", values.registry] : [])];
  let view: SchedulesView | undefined;
  const renderer = await createCliRenderer({
    exitOnCtrlC: true, screenMode: "alternate-screen", useMouse: false,
    backgroundColor: colors.background, consoleMode: "disabled", onDestroy: () => view?.cancel(),
  });
  view = new SchedulesView(renderer, args);
  void view.refresh();
  await renderer.closed;
}

await main().catch((error) => {
  console.error("crewship schedules: " + safe(String(error)));
  process.exitCode = 1;
});
