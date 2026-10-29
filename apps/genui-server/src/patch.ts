import type { PatchOp, BoardSpec } from "@crewship/genui-spec";

const unescape = (s: string) => s.replace(/~1/g, "/").replace(/~0/g, "~");

function parse(path: string): string[] {
  if (path === "") return [];
  if (path[0] !== "/") throw new Error(`bad pointer: ${path}`);
  const keys = path.slice(1).split("/").map(unescape);
  if (keys.includes("__proto__")) throw new Error(`bad pointer: ${path}`);
  return keys;
}

type Container = Record<string, unknown> | unknown[];

function walk(doc: unknown, keys: string[], path: string): Container {
  let cur = doc;
  for (const k of keys) {
    if (cur === null || typeof cur !== "object") throw new Error(`no such path: ${path}`);
    const next = Object.hasOwn(cur, k) ? (cur as Record<string, unknown>)[k] : undefined;
    if (next === undefined) throw new Error(`no such path: ${path}`);
    cur = next;
  }
  if (cur === null || typeof cur !== "object") throw new Error(`no such path: ${path}`);
  return cur as Container;
}

function index(arr: unknown[], key: string, allowEnd: boolean, path: string): number {
  if (key === "-" && allowEnd) return arr.length;
  if (!/^(0|[1-9]\d*)$/.test(key)) throw new Error(`bad index: ${path}`);
  const i = Number(key);
  if (i > arr.length || (!allowEnd && i === arr.length)) throw new Error(`index out of range: ${path}`);
  return i;
}

/** Apply a patch to a deep copy of spec; return the new spec and the inverse patch. */
export function applyPatch(spec: BoardSpec, patch: PatchOp[]): { spec: BoardSpec; inverse: PatchOp[] } {
  const doc = structuredClone(spec);
  const inverse: PatchOp[] = [];
  for (const op of patch) {
    const keys = parse(op.path);
    if (keys.length === 0) throw new Error("root patch not allowed");
    const last = keys[keys.length - 1];
    const parent = walk(doc, keys.slice(0, -1), op.path);
    if (Array.isArray(parent)) {
      const i = index(parent, last, op.op === "add", op.path);
      if (op.op === "add") {
        parent.splice(i, 0, structuredClone(op.value));
        inverse.unshift({ op: "remove", path: op.path.slice(0, op.path.lastIndexOf("/") + 1) + i });
      } else if (op.op === "replace") {
        inverse.unshift({ op: "replace", path: op.path, value: structuredClone(parent[i]) });
        parent[i] = structuredClone(op.value);
      } else {
        inverse.unshift({ op: "add", path: op.path, value: structuredClone(parent[i]) });
        parent.splice(i, 1);
      }
    } else {
      const has = Object.prototype.hasOwnProperty.call(parent, last);
      if (op.op === "add") {
        inverse.unshift(has ? { op: "replace", path: op.path, value: structuredClone(parent[last]) } : { op: "remove", path: op.path });
        parent[last] = structuredClone(op.value);
      } else {
        if (!has) throw new Error(`no such path: ${op.path}`);
        inverse.unshift(op.op === "replace" ? { op: "replace", path: op.path, value: structuredClone(parent[last]) } : { op: "add", path: op.path, value: structuredClone(parent[last]) });
        if (op.op === "replace") parent[last] = structuredClone(op.value);
        else delete parent[last];
      }
    }
  }
  return { spec: doc, inverse };
}

const esc = (s: string) => s.replace(/~/g, "~0").replace(/\//g, "~1");
export const pointer = (...keys: string[]) => "/" + keys.map(esc).join("/");

export function validatePatch(p: unknown): PatchOp[] {
  if (!Array.isArray(p)) throw new Error("patch must be an array");
  for (const op of p) {
    if (!op || typeof op.path !== "string" || !["add", "replace", "remove"].includes(op.op)) throw new Error("bad patch op");
    if (op.op !== "remove" && !("value" in op)) throw new Error("patch op needs value");
  }
  return p as PatchOp[];
}
