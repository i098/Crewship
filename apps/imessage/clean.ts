// Outbound text filter for fm-imessage: strips tags, ids, raw paths and status prefixes from mate texts.
// URLs are never touched. `bun clean.ts` filters stdin to stdout.
const HOLD = /https?:\/\/\S+/g;
const STRIP: RegExp[] = [
  /\[D[0-9a-f]{4,8}\]/gi,
  /\[(?:key|corr)=[^\]\0]*\]/g,
  /(?<![\w-])(?:key|corr)=[^\s)\]\0]*/g,
  /^[ \t\x01]*(?:cf|sm)-[a-z0-9][a-z0-9-]*[ \t]*:[ \t]*/gim,
  /^[ \t\x01]*(?:working|done|needs-decision|paused)[ \t]*:[ \t]*/gim,
  /\b[a-z0-9]+(?:-[a-z0-9]+)*-mate-[a-z0-9]+\b/gi,
  /`(?:cf|sm)-[a-z0-9][a-z0-9-]*`/gi,
  /^[ \t\x01]*(?:supervisor[ \t]*:[ \t]*)?child[ \t]+[a-z0-9][a-z0-9-]*[ \t]+(?:working|done|failed|blocked|paused|needs-decision)[ \t]*:[ \t]*/gim,
  /(?<![\w-])(?:pr|mode|yolo|head|task)=[^\s)\]]*/g,
  /(?<![\w/.:~-])(?:~(?:\/[\w.@-]+)+|(?:\/[\w.@-]+){2,})\/?/g,
  /(?<![\w/.-])(?:state|data)\/[\w./-]*\.[A-Za-z0-9]+/g,
  /^[ \t\x01]*decision stuck after \d+ attempts[^\n\0]*\n?/gim,
  /decision stuck after \d+ attempts[.,:;]?/gi,
];
const READER = /(?<![\w/.`-])the (owner|captain)(?:('s)|(?![\w/`-]|\.\w))/gi; // third-person phrase for the reader
const COLON = /^[ \t]*:(?:[ \t]+|$)/gm; // a bare colon at the start of any line, not an emoticon
const MARK = "\x01";
const EMPTY_BRACKETS = /\[[\x01\s]*\x01[\x01\s]*\]|\([\x01\s]*\x01[\x01\s]*\)/g;
const MARK_RUN = /[ \t]*(?:\x01[ \t]*)+/g;

export function cleanText(text: string): string {
  const held: string[] = [];
  let out = text.replace(HOLD, (m) => `\0${held.push(m) - 1}\0`);
  const held0 = out;
  out = out.replace(READER, (m, _word, poss, off: number, s: string) => {
    const rest = s.slice(off + m.length);
    if (/^ of\b/i.test(rest) || /^ +[A-Z]/.test(rest)) return m;
    const you = poss ? "your" : "you";
    return m[0] === "T" ? "Y" + you.slice(1) : you;
  });
  for (const re of STRIP) out = out.replace(re, MARK);
  if (out === held0) return text.replace(COLON, "") || text; // no slop found: leave the text byte-exact
  out = out.replace(EMPTY_BRACKETS, MARK).replace(MARK_RUN, (m, off: number, s: string) => {
    const next = s[off + m.length];
    return off === 0 || "\n([".includes(s[off - 1]) || next === undefined || "\n,.;:!?".includes(next) ? "" : " ";
  });
  out = out.replace(/\0(\d+)\0/g, (_, i) => held[+i]).trim().replace(COLON, ""); // a stripped prefix can leave a bare colon
  return out || text.replace(COLON, "") || text; // never turn a send into nothing
}

// A status line is internal detail, not a text for the owner. Returns why a paragraph is one, or undefined for prose.
const STATUS: [string, RegExp][] = [
  ["starts with a task or mate id", /^[ \t\x01]*(?:(?:cf|sm)-[a-z0-9][a-z0-9-]*|[a-z0-9]+(?:-[a-z0-9]+)*-mate-[a-z0-9]+)\b/i],
  ["key= tokens", /(?<![\w-])(?:key|corr)=\S/],
  ["commit hashes in a detail clause", /:[ \t]+[^\n]*\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b[^\n]*\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b/],
];
const BARE_PR_LINK = /^(?:(?:pr|pull request)[ \t]*)?<?https?:\/\/\S+\/pull\/\d+\S*>?$/i;
export function statusLine(text: string): string | undefined {
  if (BARE_PR_LINK.test(text.trim())) return "bare PR link";
  for (const para of text.split(/\n\s*\n/)) {
    const p = para.trim();
    const bare = p.replace(/https?:\/\/\S+/g, "<url>");
    const hit = p && STATUS.find(([name, re]) => re.test(name.startsWith("commit hashes") ? bare : p));
    if (hit) return hit[0];
  }
}

if (import.meta.main) process.stdout.write(cleanText(await Bun.stdin.text()));
