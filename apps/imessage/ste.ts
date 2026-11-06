// The one style rule for every text the owner reads. Each prompt that produces owner-visible text embeds it.
export const STE_STYLE = `Text style (his order): write every reply in ASD-STE100 Simplified Technical English. Use approved words, one meaning per word.
Use the active voice and simple verb tenses. Write one topic per sentence: 20 words maximum for an instruction, 25 for a description.
Keep the articles (a, an, the). No slang, no idioms, no jokes, no dashes between clauses. Keep the reply short and plain, with no Markdown. Exact quotes and identifiers stay as they are.`;

// STE check on desk text before it goes out. Vale runs the rules in ste-vale/ (dashes, contractions, semicolons, idioms, sentences over 25 words).
// ste100-checker was tried first and fails as a gate: rule 1.1 flags "you", "will" and "command", and it misses dashes and contractions.
// Every step has a time limit, and any failure sends the original text, so the check never blocks a send.
const VALE_CONFIG = `${import.meta.dir}/ste-vale/.vale.ini`;
const LINT_MS = 3_000;
const REWRITE_MS = 12_000;

// The messages for each STE violation in `text`, or undefined when the check could not run.
export async function steViolations(text: string, vale = process.env.FM_STE_VALE || Bun.which("vale")): Promise<string[] | undefined> {
  if (!vale) return;
  try {
    const proc = Bun.spawn([vale, `--config=${VALE_CONFIG}`, "--ext=.txt", "--output=JSON"], {
      stdin: new TextEncoder().encode(text), stdout: "pipe", stderr: "ignore", timeout: LINT_MS });
    const out = await new Response(proc.stdout).text();
    const code = await proc.exited;
    if (code !== 0 && code !== 1) return;
    const found = Object.values(JSON.parse(out || "{}") as Record<string, { Message: string }[]>).flat();
    return found.map((f) => f.Message);
  } catch { return; }
}

// One rewrite from the model, or undefined when it fails or gives nothing.
export async function steRewrite(text: string, issues: string[], opts: { apiKey: string; endpoint?: string; redact: (body: string) => string }): Promise<string | undefined> {
  if (!opts.apiKey) return;
  try {
    const body = opts.redact(JSON.stringify({
      model: "mercury-3", reasoning_effort: "low", max_tokens: 1024,
      messages: [
        { role: "system", content: `Rewrite the text so it follows the style rules. Keep every fact, number, name, identifier and quoted text. Add no facts. Return only the rewritten text.\n${STE_STYLE}` },
        { role: "user", content: `Problems found:\n${[...new Set(issues)].join("\n")}\n\nText:\n${text}` }],
    }));
    const response = await fetch(opts.endpoint ?? "https://api.inceptionlabs.ai/v1/chat/completions", {
      method: "POST", headers: { Authorization: `Bearer ${opts.apiKey}`, "Content-Type": "application/json" }, body, signal: AbortSignal.timeout(REWRITE_MS) });
    if (!response.ok) return;
    const content = (await response.json() as { choices?: { message?: { content?: unknown } }[] }).choices?.[0]?.message?.content;
    return typeof content === "string" && content.trim() ? content.trim() : undefined;
  } catch { return; }
}

// The text to send: the original when it passes or the check fails, else the one rewrite when it has fewer violations.
export async function steGate(text: string, rewrite: (text: string, issues: string[]) => Promise<string | undefined>, lint = steViolations): Promise<string> {
  if (text.includes("```")) return text;
  const issues = await lint(text);
  if (!issues?.length) return text;
  const fixed = await rewrite(text, issues);
  if (!fixed || fixed.length > 2000) return text;
  const left = await lint(fixed);
  return left && left.length < issues.length ? fixed : text;
}

// The outbox item with its bubbles checked once; `ste` marks it so a retry does not check again.
export async function steChecked<T extends { kind?: string; done?: number; bubbles?: string[]; ste?: true }>(o: T, opts: { apiKey: string; endpoint?: string; redact?: (body: string) => string; split: (text: string) => string[] }): Promise<T> {
  if (o.kind !== "desk" || o.ste || o.done || !o.bubbles?.length) return o;
  const before = o.bubbles.join("\n\n");
  const text = await steGate(before, (t, issues) => opts.redact ? steRewrite(t, issues, { ...opts, redact: opts.redact }) : Promise.resolve(undefined));
  return { ...o, ste: true, bubbles: text === before ? o.bubbles : opts.split(text) };
}
