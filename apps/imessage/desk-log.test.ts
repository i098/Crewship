import { expect, test } from "bun:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { deskLog } from "./outbox.ts";

// bridge.ts spreads deskLog(dir) into the desk host next to the host `log(what)` factory.
// A member named `log` would replace the factory and crash `host.log("desk task")` at startup.
test("spreading deskLog into a host keeps the host log factory", () => {
  const errors: unknown[] = [];
  const host = { log: (_what: string) => (e: unknown) => void errors.push(e), ...deskLog(mkdtempSync(join(tmpdir(), "desklog-"))) };
  expect(() => host.log("desk task")(new Error("x"))).not.toThrow();
  expect(errors).toHaveLength(1);
});
