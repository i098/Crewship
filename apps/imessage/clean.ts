// Outbound text filter for fm-imessage: strips tags, ids, raw paths and status prefixes from mate texts.
// URLs are never touched. `bun clean.ts` filters stdin to stdout.
const HOLD = /https?:\/\/\S+/g;
const STRIP: [RegExp, string][] = [
  [/\[D[0-9a-f]{4,8}\]/gi, ""],
  [/\[(?:key|corr)=[^\]]*\]/g, ""],
  [/(?<![\w-])(?:key|corr)=\S*/g, ""],
  [/^[ \t]*(?:cf|sm)-[a-z0-9][a-z0-9-]*[ \t]*:[ \t]*/gim, ""],
  [/^[ \t]*(?:working|done|needs-decision|paused)[ \t]*:[ \t]*/gim, ""],
  [/\b[a-z0-9]+(?:-[a-z0-9]+)*-mate-[a-z0-9]+\b/gi, ""],
  [/`(?:cf|sm)-[a-z0-9][a-z0-9-]*`/gi, ""],
  [/(?<![\w/.:~-])(?:~(?:\/[\w.@-]+)+|(?:\/[\w.@-]+){2,})\/?/g, ""],
  [/(?<![\w/.-])(?:state|data)\/[\w./-]*\.[A-Za-z0-9]+/g, ""],
  [/^[ \t]*decision stuck after \d+ attempts.*\n?/gim, ""],
  [/decision stuck after \d+ attempts[.,:;]?/gi, ""],
];
const TIDY: [RegExp, string][] = [
  [/\[\s*\]|\(\s*\)/g, ""],
  [/[ \t]{2,}/g, " "],
  [/[ \t]+([,.;:!?])/g, "$1"],
  [/[ \t]+$/gm, ""],
  [/\n{3,}/g, "\n\n"],
];

export function cleanText(text: string): string {
  const held: string[] = [];
  let out = text.replace(HOLD, (m) => `\0${held.push(m) - 1}\0`);
  const held0 = out;
  for (const [re, to] of STRIP) out = out.replace(re, to);
  if (out === held0) return text; // no slop found: leave the text byte-exact
  for (const [re, to] of TIDY) out = out.replace(re, to);
  out = out.replace(/\0(\d+)\0/g, (_, i) => held[+i]).trim();
  return out || text; // never turn a send into nothing
}

if (import.meta.main) process.stdout.write(cleanText(await Bun.stdin.text()));
