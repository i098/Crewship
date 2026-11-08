// An owner text is marked read only once firstmate or a mate has taken it, never on arrival or on a desk answer.
// Firstmate takes it when its inbox note is acknowledged; a mate when the delivered message moves to its handled/ folder.
// ponytail: the pending texts live in memory; a text taken after a restart is not marked read. Persist them if that matters.
const KEEP_UNREAD = 100;

export type Unread = { id: string; read(): Promise<unknown> };
export type Receipts = { handled?: { request_id?: string; acknowledged?: boolean }[] };

export type ReadMarksHost = {
  receipts(): Promise<Receipts>; // `fm-inbox.sh receipts`
  mateTook(mate: string, marker: string): boolean; // the mate's handled/ folder holds the delivered message
  log(what: string): (error: unknown) => void;
  trace(message: Unread, event: string): void;
};

export function createReadMarks(host: ReadMarksHost) {
  const unread = new Map<string, Unread>(); // request id -> the text
  const noteOf = new Map<string, string[]>(); // a desk task note id -> the request ids it answers
  const mateOf = new Map<string, { mate: string; ids: string[] }>(); // the marker id of a delivery -> the mate and request ids
  let polling = false;

  // True when no read failed, so a failed read is retried on the next poll.
  async function markRead(ids: string[]) {
    let ok = true;
    for (const id of ids) {
      const message = unread.get(id);
      if (!message) continue;
      try {
        await message.read();
        unread.delete(id);
        host.trace(message, "read");
      } catch (e) {
        ok = false;
        host.log("mark read")(e);
      }
    }
    return ok;
  }

  return {
    hold(requestId: string, message: Unread) {
      unread.set(requestId, message);
      if (unread.size > KEEP_UNREAD) unread.delete(unread.keys().next().value!);
    },
    // The note `noteId` answers these owner texts.
    noted(noteId: string, requests: string[]) { noteOf.set(noteId, requests); },
    // The message marked `marker` went to `mate` for these owner texts.
    delivered(marker: string, mate: string, requests: string[]) { mateOf.set(marker, { mate, ids: requests }); },
    async poll() {
      if (polling || !unread.size) return;
      polling = true;
      try {
        for (const [marker, { mate, ids }] of mateOf) {
          if (!ids.some((id) => unread.has(id))) mateOf.delete(marker);
          else if (host.mateTook(mate, marker) && await markRead(ids)) mateOf.delete(marker);
        }
        const { handled = [] } = await host.receipts();
        for (const { request_id, acknowledged } of handled) {
          if (request_id && acknowledged === true && await markRead(noteOf.get(request_id) ?? [request_id])) noteOf.delete(request_id);
        }
      } catch (e) {
        host.log("read receipts")(e);
      } finally {
        polling = false;
      }
    },
  };
}
