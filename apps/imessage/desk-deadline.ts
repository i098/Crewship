// A desk turn never runs forever: past the limit it is aborted and the owner gets one honest reply.
export const TURN_MAX_MS = 150_000;
export const TIMEOUT_REPLY = "The answer is delayed. Firstmate has your text and will reply.";

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
