// The desk's file tools. Every path is checked in code, before the claim and the effect: it must sit under an allowed root
// (the user skills folder, the desk files folder), outside any git checkout, and name no credential file or credential, payment or posting topic.
import { closeSync, existsSync, lstatSync, mkdirSync, openSync, readFileSync, realpathSync, renameSync, writeSync, fsyncSync, statSync } from "node:fs";
import { basename, dirname, relative, resolve } from "node:path";
import { deniedTopic } from "./desk-deny.ts";

export type FileRoots = { write: string[]; read: string[] };
export const WRITE_MAX = 256 * 1024; // chars of text one write_file call stores
export const SEND_MAX = 25 * 1024 * 1024; // bytes of one sent file
export const SEND_TYPES = /\.(?:png|jpe?g|webp)$/i; // the only types the transport sends (image.ts)

const CREDENTIAL = /(?:^|\/)(?:\.env[^/]*|\.ssh|\.aws|\.gnupg|\.netrc|\.npmrc|\.pypirc|\.git-credentials|\.docker|\.kube|id_(?:rsa|dsa|ecdsa|ed25519)[^/]*|[^/]*\.(?:pem|key|p12|pfx|kdbx)|[^/]*(?:secret|credential|passw|token|keychain|auth\.json|super\.env)[^/]*)(?:\/|$)/i;

// `target` with the deepest existing part resolved, so a symlink out of the root is caught; the rest is new.
function realOf(target: string): string {
  let near = target;
  while (!existsSync(near)) near = dirname(near);
  return resolve(realpathSync(near), relative(near, target));
}

// Refuses a real path (`inside` is its part under the real root) that holds project files, a credential or a denied topic.
function vet(real: string, realRoot: string, inside: string): void {
  for (let dir = real; ; dir = dirname(dir)) { // a git checkout (the root included) holds project files
    if (existsSync(`${dir}/.git`)) throw new Error("refused: the path is inside a git checkout (project files)");
    if (dir === realRoot || dir === dirname(dir)) break;
  }
  if (/(?:^|\/)(?:\.treehouse|worktrees)(?:\/|$)/.test(real)) throw new Error("refused: the path is inside a project worktree");
  if (CREDENTIAL.test(inside)) throw new Error("refused: the path names a credential file");
  const topic = deniedTopic(inside);
  if (topic) throw new Error(`refused: the path concerns ${topic}`);
}

// The real path `path` would have, or the reason it may not be used. `roots` are the allowed roots.
function check(path: string, roots: string[]): string {
  if (typeof path !== "string" || !path || path.includes("\0") || !path.startsWith("/")) throw new Error("refused: path must be absolute");
  const target = resolve(path);
  const root = roots.find((r) => existsSync(r) && !relative(resolve(r), target).startsWith("..") && target !== resolve(r));
  if (!root) throw new Error(`refused: the path is outside the allowed folders (${roots.join(", ") || "none set"})`);
  const realRoot = realpathSync(root);
  const real = realOf(target);
  const inside = relative(realRoot, real);
  if (inside.startsWith("..") || inside === "") throw new Error("refused: the path leaves the allowed folder");
  vet(real, realRoot, inside);
  return real;
}

export function planWrite(roots: FileRoots, path: string, content: unknown, safe: (text: string) => string): { real: string; text: string } {
  if (typeof content !== "string") throw new Error("content must be a string");
  if (content.length > WRITE_MAX) throw new Error(`refused: content is over ${WRITE_MAX} characters`);
  if (safe(content) !== content) throw new Error("refused: the content holds protected content");
  const real = check(path, roots.write);
  if (existsSync(real) && !statSync(real).isFile()) throw new Error("refused: the path is not a file");
  return { real, text: content };
}

export function writeText(real: string, text: string): void {
  mkdirSync(dirname(real), { recursive: true });
  const tmp = `${real}.${process.pid}.tmp`;
  const fd = openSync(tmp, "w", 0o644);
  try { writeSync(fd, text); fsyncSync(fd); } finally { closeSync(fd); }
  renameSync(tmp, real);
}

export function planSend(roots: FileRoots, path: string): string {
  const real = check(path, roots.read);
  if (!SEND_TYPES.test(real)) throw new Error("refused: the transport sends png, jpg or webp images only");
  const stat = lstatSync(real, { throwIfNoEntry: false });
  if (!stat?.isFile()) throw new Error("refused: no such file");
  if (stat.size > SEND_MAX) throw new Error("refused: the file is too large");
  return real;
}

export const readFile = (real: string) => ({ bytes: readFileSync(real), name: basename(real) });
