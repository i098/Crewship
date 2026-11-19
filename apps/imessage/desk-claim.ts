// The desk may not tell the owner that an order, purchase, send or post is done unless an action tool succeeded in the same turn.
// The patterns lean broad: a false match only makes the model reword the text as a plan or a recommendation.
const DONE = /\b(?:ordered|purchased|bought|booked|paid|reserved|subscribed|sent|emailed|texted|posted|published|submitted|cancell?ed|scheduled)\b/i;

export function unprovenClaim(text: string, proved: boolean): string | undefined {
  const done = DONE.exec(text)?.[0];
  return !proved && done ? `refused: the text says "${done}" but no action tool succeeded in this turn; say what you recommend or what is queued, not that it is done` : undefined;
}
