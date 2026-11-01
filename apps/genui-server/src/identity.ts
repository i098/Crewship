export type Identity = { id: string; kind: "user" | "agent" };

/**
 * Single auth seam. Stub: everyone is the local dev user; agents must present
 * GENUI_AGENT_TOKEN when it is set. Later: CF Access JWT + tailnet identity, same signature.
 */
export function resolveIdentity(req: Request, env: { GENUI_AGENT_TOKEN?: string }, kind: Identity["kind"]): Identity | null {
  if (kind === "agent" && env.GENUI_AGENT_TOKEN) {
    if (req.headers.get("authorization") !== `Bearer ${env.GENUI_AGENT_TOKEN}`) return null;
  }
  return { id: kind === "agent" ? "agent" : "dev", kind };
}
