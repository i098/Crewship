// Outbound text filter for fm-imessage: strips tags, ids, raw paths and status prefixes from mate texts.
// URLs are never touched. `bun clean.ts` filters stdin to stdout.
const HOLD = /https?:\/\/\S+/g;
const STRIP: RegExp[] = [
  /\[D[0-9a-f]{4,8}\]/gi,
  /\[(?:key|corr)=[^\]]*\]/g,
  /(?<![\w-])(?:key|corr)=[^\s)\]]*/g,
  /^[ \t\x01]*(?:cf|sm)-[a-z0-9][a-z0-9-]*[ \t]*:[ \t]*/gim,
  /^[ \t\x01]*(?:working|done|needs-decision|paused)[ \t]*:[ \t]*/gim,
  /\b[a-z0-9]+(?:-[a-z0-9]+)*-mate-[a-z0-9]+\b/gi,
  /`(?:cf|sm)-[a-z0-9][a-z0-9-]*`/gi,
  /(?<![\w/.:~-])(?:~(?:\/[\w.@-]+)+|(?:\/[\w.@-]+){2,})\/?/g,
  /(?<![\w/.-])(?:state|data)\/[\w./-]*\.[A-Za-z0-9]+/g,
  /^[ \t\x01]*decision stuck after \d+ attempts.*\n?/gim,
  /decision stuck after \d+ attempts[.,:;]?/gi,
];
const MARK = "\x01";
const EMPTY_BRACKETS = /\[[\x01\s]*\x01[\x01\s]*\]|\([\x01\s]*\x01[\x01\s]*\)/g;
const MARK_RUN = /[ \t]*(?:\x01[ \t]*)+/g;

export function cleanText(text: string): string {
  const held: string[] = [];
  let out = text.replace(HOLD, (m) => `\0${held.push(m) - 1}\0`);
  const held0 = out;
  for (const re of STRIP) out = out.replace(re, MARK);
  if (out === held0) return text; // no slop found: leave the text byte-exact
  out = out.replace(EMPTY_BRACKETS, MARK).replace(MARK_RUN, (m, off: number, s: string) => {
    const next = s[off + m.length];
    return off === 0 || s[off - 1] === "\n" || next === undefined || "\n,.;:!?".includes(next) ? "" : " ";
  });
  out = out.replace(/\0(\d+)\0/g, (_, i) => held[+i]).trim();
  return out || text; // never turn a send into nothing
}

if (import.meta.main) process.stdout.write(cleanText(await Bun.stdin.text()));
