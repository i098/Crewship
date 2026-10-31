import type { Component, PatchOp } from "@crewship/genui-spec";

/** What an agent write must not change: ids whose rect is locked, ids whose pin is kept, and the current components. */
export type Locks = { components: Record<string, Component>; rectLocked: (id: string) => boolean; keepPin: boolean };

const componentPath = /^\/components(?:\/([^/]+)(\/.*)?)?$/;
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object";
const unesc = (s: string) => s.replace(/~1/g, "/").replace(/~0/g, "~");
const withValue = (p: PatchOp, f: (v: unknown) => unknown): PatchOp => (p.op === "remove" ? p : { ...p, value: f(p.value) });

const old = (l: Locks, id: string) => (Object.hasOwn(l.components, id) ? l.components[id] : undefined);
const pinned = (l: Locks, id: string) => l.keepPin && old(l, id)?.props?.pinned === true;

function carry(l: Locks, id: string, v: unknown): unknown {
  const o = old(l, id);
  if (!o || !isObj(v)) return v;
  const c = { ...(v as Component) };
  if (l.rectLocked(id)) { if (o.rect) c.rect = o.rect; else delete c.rect; }
  if (pinned(l, id)) c.props = { ...c.props, pinned: true };
  return c;
}

function guardField(l: Locks, p: PatchOp, id: string, rest: string): PatchOp | null {
  if (rest === "/rect" || rest.startsWith("/rect/")) return l.rectLocked(id) ? null : p;
  if (rest === "/props/pinned" || (rest === "/props" && p.op === "remove")) return pinned(l, id) ? null : p;
  if (rest === "/props") return withValue(p, (v) => (pinned(l, id) && isObj(v) ? { ...v, pinned: true } : v));
  return p;
}

function guardOp(l: Locks, p: PatchOp): PatchOp | null {
  const m = componentPath.exec(p.path);
  if (!m) return p;
  if (m[1] === undefined) return withValue(p, (v) => (isObj(v) ? Object.fromEntries(Object.entries(v).map(([k, c]) => [k, carry(l, k, c)])) : v));
  const id = unesc(m[1]);
  return m[2] ? guardField(l, p, id, m[2]) : withValue(p, (v) => carry(l, id, v));
}

/** Agent writes of any shape (rect, props, whole component, whole map) keep locked rects and kept pins. */
export const guardPatch = (l: Locks, patch: PatchOp[]): PatchOp[] => patch.map((p) => guardOp(l, p)).filter((p): p is PatchOp => p !== null);
