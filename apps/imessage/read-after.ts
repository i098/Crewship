// Holds each owner text's read mark until the text is answered. A text that never gets an answer stays unread on his phone.
// ponytail: the holds live in memory; a text answered after a restart is not marked read. Persist them if that matters.
const KEEP = 100;

export function createReadAfter(onError: (what: string) => (e: unknown) => void) {
  const held = new Map<string, () => Promise<unknown>>();
  return {
    hold(requestId: string, read: () => Promise<unknown>) {
      held.set(requestId, read);
      if (held.size > KEEP) held.delete(held.keys().next().value!);
    },
    // Marks each held text read once; an id with no hold, or already released, does nothing.
    answered(requestIds: string[]) {
      for (const id of requestIds) {
        const read = held.get(id);
        if (!read) continue;
        held.delete(id);
        void read().catch(onError("mark read"));
      }
    },
  };
}
