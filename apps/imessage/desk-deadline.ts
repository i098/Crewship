// A desk turn never runs forever: past the limit it is aborted and the owner gets one honest reply.
export const TURN_MAX_MS = 150_000;
export const TIMEOUT_REPLY = "The answer is delayed. Firstmate has your text and will reply.";
export const FRONT_TIMEOUT_REPLY = "I got your text. I am passing it to Firstmate now.";

// One honest line per burst in each chat: the texts sent before the next desk reply there. `claim` is true only the first time per chat.
export function createBurst() {
  const acked = new Set<string>();
  return {
    claim: (chat: string) => !acked.has(chat) && !!acked.add(chat),
    reset: (chat: string) => void acked.delete(chat),
  };
}

// True when the turn finished in time. On a timeout `onTimeout` runs once and the late result of `turn` is ignored.
export async function withDeadline(turn: Promise<void>, ms: number, onTimeout: () => void): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<false>((resolve) => { timer = setTimeout(() => resolve(false), ms); });
  turn.catch(() => {}); // a turn that fails after the limit is already answered
  try {
    const result = await Promise.race([turn.then(() => true as const), late]);
    if (!result) onTimeout();
    return result;
  } finally { clearTimeout(timer); }
}

type Turn = { route: string; out?: { bubbles?: string[] } };

// Abort a turn past its limit. A still-pending, still-current turn goes to Firstmate and queues one honest reply.
export function timeOutTurn(pending: Turn[], controller: AbortController, current: () => boolean, handoff: () => void, reply: (bubble: string) => void) {
  const stuck = current() && pending.every((r) => r.route === "pending");
  controller.abort();
  if (!stuck) return false;
  handoff();
  reply(TIMEOUT_REPLY);
  return true;
}

// Typing stays on after a turn only while a desk answer waits for delivery; a handoff or an empty turn ends it.
export function typingOutlivesTurn(pending: Turn[]) {
  return pending.some((r) => r.route === "desk" && !!r.out?.bubbles?.length);
}
