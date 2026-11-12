// Who sent a thread-reply target. A bubble recorded with its message id is matched by id alone; the start of the text
// only matches bubbles recorded without an id, and only when they all have one sender.
export type SentBubble = { key: string; sender: string; id?: string };

export const quoteKey = (text: string) => text.slice(0, 120).trim();

export function senderOfQuoted(bubbles: SentBubble[], text: string, id?: string) {
  const byId = id ? bubbles.find((b) => b.id === id) : undefined;
  if (byId) return byId.sender;
  const senders = new Set(bubbles.filter((b) => b.id === undefined && b.key === quoteKey(text)).map((b) => b.sender));
  return senders.size === 1 ? [...senders][0] : undefined;
}

// The owner (a text the bridge heard) or us (a bubble the bridge sent); undefined when neither record has it.
export function whoSent(said: { has(id: string): boolean }, bubbles: SentBubble[], id: string, text: string) {
  if (said.has(id)) return "the owner";
  const ours = bubbles.some((b) => b.id === id) || bubbles.some((b) => b.id === undefined && b.key === quoteKey(text));
  if (!ours) return undefined;
  const sender = senderOfQuoted(bubbles, text, id);
  return `us${sender ? ` (sender ${sender})` : ""}`;
}
