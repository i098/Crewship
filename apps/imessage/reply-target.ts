// Picks the text a thread reply goes to, from the `?reply=N` or `?reply-id=ID` parameter of a /send or /image request.
// An id pins one message: a newer text cannot move it. N counts from the newest text, so a newer text shifts it.
export type Picked<T> = { target?: T; error?: string };

export function pickTarget<T extends { id: string; line?: string }>(recent: T[], params: URLSearchParams): Picked<T> {
  const id = params.get("reply-id");
  const n = Number(params.get("reply") ?? 0);
  if (id !== null && n > 0) return { error: "use either reply or reply-id, not both" };
  if (id !== null) {
    // The id is the message id, or the inbox request id <line>-<id>; a Photon text has no line field and is line "photon".
    const target = id ? recent.find((r) => r.id === id || `${r.line ?? "photon"}-${r.id}` === id) : undefined;
    return target ? { target } : { error: `no kept text has the id ${id || "(empty)"}; ${recent.length} text(s) kept since the service started` };
  }
  if (n > 0) {
    const target = recent[recent.length - n];
    return target ? { target } : { error: `only ${recent.length} text(s) kept since the service started` };
  }
  return {};
}

// The 400 answer for a refused target, or undefined when the pick succeeded.
export function refusal(picked: Picked<unknown>): Response | undefined {
  return picked.error ? new Response(`nothing queued: ${picked.error}\n`, { status: 400 }) : undefined;
}

// The handler seam of /send and /image: refuses a bad target with the 400, else runs `next` with the pick.
export function withTarget<T extends { id: string; line?: string }>(recent: T[], params: URLSearchParams, next: (target?: T) => Response): Response {
  const chosen = pickTarget(recent, params);
  return refusal(chosen) ?? next(chosen.target);
}

// The routing-log row for a threaded reply.
export function routeRow(target: { id: string; space: string }, params: URLSearchParams) {
  return { replyTarget: target.id, space: target.space, by: params.has("reply-id") ? "id" as const : "position" as const };
}

// A reply names its target by message id when a bubble was recorded with one. Otherwise the start of the text counts,
// and only when every recent bubble with that start has one sender.
export type SentBubble = { key: string; sender: string; id?: string };

export const quoteKey = (text: string) => text.slice(0, 120).trim();

export function senderOfQuoted(bubbles: SentBubble[], text: string, id?: string) {
  const byId = id ? bubbles.find((b) => b.id === id) : undefined;
  if (byId) return byId.sender;
  const senders = new Set(bubbles.filter((b) => b.key === quoteKey(text)).map((b) => b.sender));
  return senders.size === 1 ? [...senders][0] : undefined;
}

// Who sent a thread-reply target: a bubble recorded with this id is ours by id alone; the text start only matches
// bubbles recorded without an id. The owner (a text the bridge heard) or us (a bubble the bridge sent); undefined when neither record has it.
export function whoSent(said: { has(id: string): boolean }, bubbles: SentBubble[], id: string, text: string) {
  if (said.has(id)) return "the owner";
  const ours = bubbles.some((b) => b.id === id) || bubbles.some((b) => b.id === undefined && b.key === quoteKey(text));
  if (!ours) return undefined;
  const sender = senderOfQuoted(bubbles, text, id);
  return `us${sender ? ` (sender ${sender})` : ""}`;
}
