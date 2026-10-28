import { expect, test } from "bun:test"
import { age, discover, flatten, keyOf, mem, snapshot, type Page } from "./browser-tui.ts"

// pid ppid etimes rss args
const PS = `
    1     0  9000   100 /sbin/init
  100     1  5000 20000 /opt/obscura serve --host 127.0.0.1 --port 9222 --storage-dir /s/obscura
  101   100  5000 10000 /opt/obscura-worker --id 1
  200     1   120 50000 /c/chrome --headless=new --remote-debugging-port=9522 --user-data-dir=/s/chrome-profile
  201   200   120 30000 /c/chrome --type=zygote --headless=new
  202   201   100 40000 /c/chrome --type=renderer --headless=new
  300     1  4000 60000 /c/chrome --no-sandbox --remote-debugging-port=9523 --user-data-dir=/s/vnc-profile about:blank
  400     1    30 70000 /home/u/.cache/ms-playwright/chromium-1/chrome --remote-debugging-port=0 --user-data-dir=/tmp/pw-abc
  500     1    10  9000 chrome-devtools-mcp
  600     1    10  8000 /c/chrome --remote-debugging-pipe
`
const SS = `
LISTEN 0 128 127.0.0.1:9222 0.0.0.0:* users:(("obscura",pid=100,fd=9))
LISTEN 0 128 127.0.0.1:9522 0.0.0.0:* users:(("chrome",pid=200,fd=9))
LISTEN 0 128 127.0.0.1:9523 0.0.0.0:* users:(("chrome",pid=300,fd=9))
LISTEN 0 128 127.0.0.1:41000 0.0.0.0:* users:(("chrome",pid=400,fd=9))
LISTEN 0 128 127.0.0.1:9229 0.0.0.0:*
LISTEN 0 128 127.0.0.1:3389 0.0.0.0:*
LISTEN 0 128 100.64.0.1:9224 0.0.0.0:*
`
const page = (id: string): Page => ({ id, title: `t${id}`, url: `https://example.test/${id}` })
const CDP: Record<number, { ua: string; pages: Page[] }> = {
  9222: { ua: "Mozilla/5.0 Chrome/145", pages: [page("o1")] },
  9522: { ua: "HeadlessChrome/156", pages: [page("c1"), page("c2")] },
  9523: { ua: "Chrome/156", pages: [] },
  41000: { ua: "Chrome/140", pages: [page("p1")] },
  9229: { ua: "HeadlessChrome/150", pages: [] },
  3389: { ua: "", pages: [] },
}
const probed: number[] = []
const probe = async (port: number) => (probed.push(port), CDP[port] ?? null)

test("discover finds each browser once with kind, port, memory and pages", async () => {
  const bs = await discover(PS, SS, probe, "https://viewer.test/vnc.html")
  const by = (pid: number | null) => bs.find(b => b.pid === pid)!
  expect(bs.map(b => b.pid).sort()).toEqual([100, 200, 300, 400, 600, null].sort())
  expect(by(100)).toMatchObject({ name: "fleet obscura", kind: "headless", port: 9222, rssKb: 30000, pages: [page("o1")] })
  expect(by(200)).toMatchObject({ name: "fleet chrome", kind: "headless", port: 9522, rssKb: 120000, ageSec: 120 })
  expect(by(300)).toMatchObject({ name: "fleet vnc (noVNC)", kind: "headed", port: 9523, viewer: "https://viewer.test/vnc.html" })
  // Port 0 is resolved from the listening socket the browser owns.
  expect(by(400)).toMatchObject({ name: "playwright · pw-abc", kind: "headed", port: 41000 })
  expect(by(600)).toMatchObject({ kind: "headed", port: null, pages: [] })
  // An ownerless known CDP port is listed; ownerless unknown and non-loopback ports are never probed.
  expect(by(null)).toMatchObject({ name: "cdp", kind: "headless", port: 9229, ageSec: null })
  expect(probed).not.toContain(3389)
  expect(probed).not.toContain(9224)
  expect(by(200).viewer).toBeUndefined()
})

test("rows show pages only for open browsers, and the snapshot lists every page and viewer", async () => {
  const bs = await discover(PS, SS, probe, "https://viewer.test/vnc.html")
  const chrome = bs.find(b => b.pid === 200)!
  expect(flatten(bs, new Set()).length).toBe(bs.length)
  expect(flatten(bs, new Set([keyOf(chrome)])).filter(r => r.page).map(r => r.page!.id)).toEqual(["c1", "c2"])
  const text = snapshot(bs, 120)
  expect(text).toContain("https://example.test/c2")
  expect(text).toContain("viewer fleet vnc (noVNC): https://viewer.test/vnc.html")
  for (const line of text.split("\n").slice(0, -1)) expect(line.length).toBeLessThanOrEqual(120)
})

test("age and memory formats switch units at their boundaries", () => {
  expect([age(59), age(60), age(3599), age(3600), age(86400), age(null)]).toEqual(["59s", "1m", "59m", "1h", "1d", "?"])
  expect([mem(0), mem(1024), mem(1024 * 1024)]).toEqual(["?", "1M", "1.0G"])
})
