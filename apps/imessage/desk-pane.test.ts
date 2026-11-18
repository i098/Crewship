import { expect, test } from "bun:test";
import { keysTo, paneId, parsePrompt, promptRefusal } from "./desk-pane.ts";

const screen = (title: string[], options: string[], hint = " ↑↓ navigate  enter select  esc cancel") =>
  ["old output", "", "", ...title.map((line) => ` ${line}`), "", ...options, "", hint, "", "❯", " status bar"].join("\n");

const RESET = screen(["Spend a saved Claude rate-limit reset?", "Claude work: 5h reset, about 2h left."], [
  " ❯ Yes", "     Redeem now and set auto-redeem to yes.", "   No", "     Do not redeem, and set auto-redeem to no.",
]);

test("reads the title, the options and the cursor of an omp selector", () => {
  const p = parsePrompt(RESET)!;
  expect(p.title).toBe("Spend a saved Claude rate-limit reset?\nClaude work: 5h reset, about 2h left.");
  expect(p.options).toEqual(["Yes", "No"]);
  expect(p.selected).toBe(0);
  expect(p.unclear).toBeUndefined();
  expect(promptRefusal(p)).toBeUndefined();
});

test("the prompt id ignores the cursor position", () => {
  const moved = RESET.replace(" ❯ Yes", "   Yes").replace("   No", " ❯ No");
  expect(parsePrompt(moved)!.id).toBe(parsePrompt(RESET)!.id);
  expect(parsePrompt(moved)!.selected).toBe(1);
});

test("a screen with no selector hint has no prompt", () => {
  expect(parsePrompt("working...\n\n❯\n status")).toBeUndefined();
});

test("a prompt about credentials, payments or public posts is refused, whatever the options say", () => {
  const ask = (title: string, a = "Yes", b = "No") => parsePrompt(screen([title], [` ❯ ${a}`, `   ${b}`]))!;
  expect(promptRefusal(ask("Log in to the account again?"))).toBe("credentials or logins");
  expect(promptRefusal(ask("Continue?", "Pay $20 now", "Cancel"))).toBe("payments or purchases");
  expect(promptRefusal(ask("Continue?", "Publish the post", "Skip"))).toBe("public posts");
  expect(promptRefusal(ask("Continue?", "Yes", "No, I will paste my API key"))).toBe("credentials or logins");
});

test("a prompt the bridge cannot read exactly is unclear", () => {
  const unclear = (lines: string[]) => parsePrompt(screen(["Pick one"], lines))!.unclear;
  expect(unclear(["   One", "   Two"])).toBe("no selected option is visible");
  expect(unclear([" ❯ Only"])).toBe("fewer than two options");
  expect(unclear([" ❯ One", "   Two", "  (1/9)  Type to search"])).toBe("the list is scrolled");
  expect(unclear([" ❯ [x] One", "   [ ] Two"])).toBe("a multiple choice");
  expect(promptRefusal(parsePrompt(screen(["Pick one"], [" ❯ One", "   Two", "  (1/9)  Type to search"]))!)).toBe("the list is scrolled");
});

test("keysTo moves the cursor by arrows only", () => {
  const p = parsePrompt(screen(["Pick"], [" ❯ A", "   B", "   C"]))!;
  expect(keysTo(p, 1)).toEqual([]);
  expect(keysTo(p, 3)).toEqual(["down", "down"]);
  expect(keysTo({ ...p, selected: 2 }, 1)).toEqual(["up", "up"]);
});

const list = (agents: unknown[]) => JSON.stringify({ result: { agents } });

test("paneId finds the supervisor and a mate by their who token, and nothing ambiguous", () => {
  const json = list([
    { pane_id: "a:1", tokens: { who: "firstmate" } },
    { pane_id: "a:2", tokens: { who: "crewship" } },
    { pane_id: "a:3" },
    { pane_id: "a:4", tokens: { who: "dup" } },
    { pane_id: "a:5", tokens: { who: "dup" } },
  ]);
  expect(paneId(json, "main")).toBe("a:1");
  expect(paneId(json, "crewship")).toBe("a:2");
  expect(() => paneId(json, "dup")).toThrow("more than one pane");
  expect(() => paneId(json, "ghost")).toThrow("no pane for ghost");
});
