// Topics the desk never acts on. The bridge checks them in code on a pane prompt (desk-pane.ts) and on a script's name and
// header comment (desk-scripts.ts); the session prompt repeats them, but this is the rule. A false match only sends the
// owner the text instead, so the patterns lean broad.
const TOPICS: readonly [string, RegExp][] = [
  ["credentials or logins", /\b(?:passwords?|passcodes?|credentials?|log ?ins?|log(?:ging)? (?:in|out)|sign(?:ing)? ?(?:in|up|out)|oauth|api[ -]?keys?|secrets?|tokens?|2fa|mfa|otp|authenticat\w*|authoriz\w*|private keys?|ssh keys?|keychain|cookies?)\b/i],
  ["payments or purchases", /\b(?:pay\w*|paid|buy\w*|bought|purchas\w*|prices?|invoic\w*|billing|checkout|subscri\w*|refund\w*|charg\w*|credit cards?|debit|wire transfer|trad(?:e|es|ed|ing)|top[ -]?up|place (?:an? )?orders?)\b|[$€£]\s?\d/i],
  ["public posts", /\b(?:post\w*|publish\w*|tweet\w*|public\w*|announc\w*|share\w*|comment\w*|linkedin|twitter|instagram|facebook|newsletter|blog|go live|open (?:an? |the )?(?:pr|pull request|issue))\b/i],
];

// The first denied topic that `text` concerns, or undefined.
export function deniedTopic(text: string): string | undefined {
  return TOPICS.find(([, pattern]) => pattern.test(text))?.[0];
}
