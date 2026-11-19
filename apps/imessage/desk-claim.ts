// The desk may not tell the owner that an action is done unless a tool that can do that kind of action succeeded in the same turn.
// A kind with no tool in its list can never be claimed: no desk tool orders, buys, pays, books or posts.
// shortcut: a word list, so an unlisted wording slips through and a loose match makes the model reword; upgrade to gating reply text structurally.
// A verb whose subject is the owner or another person ("the email you sent") is history, not a claim.
const OTHER = String.raw`(?<!\b(?:you|they|he|she)\s+)`;
const CLAIMS: [kind: string, pattern: RegExp, tools: string[]][] = [
  ["order", /\b(?:ordered|order placed|placed (?:the|an?|your) order|purchased|bought|paid|payment (?:made|sent)|booked|reserved|subscribed|on its way|on the way)\b/i, []],
  ["post", /\b(?:posted|published|tweeted|submitted|cancell?ed|scheduled)\b/i, []],
  ["send", /\b(?:sent|emailed|texted|messaged)\b/i, ["message_mate"]],
].map(([kind, re, tools]) => [kind, new RegExp(OTHER + (re as RegExp).source, "i"), tools]) as [string, RegExp, string[]][];

// The refusal for `text`, or undefined; `succeeded` holds the tools that succeeded so far in this turn.
export function unprovenClaim(text: string, succeeded: ReadonlySet<string>): string | undefined {
  for (const [kind, pattern, tools] of CLAIMS) {
    const said = pattern.exec(text)?.[0];
    if (said && !tools.some((t) => succeeded.has(t)))
      return `refused: the text says "${said}" (${kind}) but ${tools.length ? `${tools.join(" or ")} did not succeed in this turn` : "no desk tool can do that"}; say what you recommend or what is queued, not that it is done`;
  }
}
