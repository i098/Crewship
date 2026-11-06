import { expect, test } from "bun:test";
import { appendFileSync, mkdtempSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { wakeNotice, watchStrandedWake } from "./wake-notice.ts";

test("a woken line becomes one honest sentence with the note count", () => {
  expect(wakeNotice(["1794008507\twoken\tnotes=1\tqueue=false"])).toContain("1 of your note was waiting");
  expect(wakeNotice(["1\twoken\tnotes=3\tqueue=true"])).toContain("3 of your notes were waiting");
  expect(wakeNotice(["1\twoken\tnotes=0\tqueue=true"])).toContain("a queued wake was waiting");
  expect(wakeNotice(["noise"])).toBeUndefined();
});

test("a new log line sends once; old lines and a second line inside the cooldown send nothing", async () => {
  const dir = mkdtempSync(join(process.env.TMPDIR || "/tmp", "wake-"));
  const log = join(dir, ".stranded-wake.log");
  writeFileSync(log, "1\twoken\tnotes=1\tqueue=false\n");
  const sent: string[] = [];
  const w = watchStrandedWake(log, (t) => sent.push(t))!;
  appendFileSync(log, "2\twoken\tnotes=2\tqueue=false\n");
  await Bun.sleep(300);
  appendFileSync(log, "3\twoken\tnotes=2\tqueue=false\n");
  await Bun.sleep(300);
  w.close();
  expect(sent).toHaveLength(1);
  expect(sent[0]).toContain("2 of your notes");
});
