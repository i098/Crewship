// Picks the text a thread reply goes to, from the `?reply=N` or `?reply-id=ID` parameter of a /send or /image request.
// An id pins one message: a newer text cannot move it. N counts from the newest text, so a newer text shifts it.
export type Picked<T> = { target?: T; error?: string };

export function pickTarget<T extends { id: string }>(recent: T[], params: URLSearchParams): Picked<T> {
  const id = params.get("reply-id");
  const n = Number(params.get("reply") ?? 0);
  if (id !== null && n > 0) return { error: "use either reply or reply-id, not both" };
  if (id !== null) {
    const target = id ? recent.find((r) => r.id === id) : undefined;
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
