# browser-tui

Terminal view of every browser that runs on the host, headed and headless.
Each row shows the kind, name, pid, CDP port, age, memory (the whole process tree) and the number of open pages.
Open a browser to see its pages, with title and URL, from the CDP `/json/list` endpoint.
The background is transparent; colors come from `../tui-theme/theme.ts`.

```bash
bun install
bun browser-tui.ts
```

## How it finds browsers

- Processes named `chrome`, `chromium`, `headless_shell`, `obscura` or `obscura-worker` (Playwright and Puppeteer ship Chromium under these names). Child processes such as renderers count toward their browser.
- The CDP port comes from `--remote-debugging-port` or `--port`, else from a socket the browser listens on (`ss -ltnp`).
- A known CDP port (9222-9229, 9522, 9523) whose owner is not visible is listed as `cdp` with no pid.
- A browser started with `--headless`, Obscura, or a CDP user agent that says `Headless` is headless; any other browser is headed.
- The fleet-browser tiers have fixed names: `fleet obscura` (9222), `fleet chrome` (9522) and `fleet vnc (noVNC)` (9523). The VNC tier shows its noVNC viewer link: the tailnet name from `tailscale status` on port 6909, else `http://127.0.0.1:6909/vnc.html`.

The view reads again every 3 seconds and renders only the visible rows.

## Keys

`↑↓`/`jk` move, `Enter` open or close a browser, `r` reload, `c` copy the CDP URL (OSC 52), `x` close the selected page (`/json/close`), `K` stop the selected browser (SIGTERM), `q` quit.
`x` and `K` ask y/n first; any key other than `y` cancels.
A systemd unit with a restart policy can start a stopped browser again.

## Flags

`--once` prints the list with every page and exits.
`--fixture file.json` reads a recorded list (the `Browser[]` shape in `browser-tui.ts`) instead of the host; `x` and `K` then send nothing.

```bash
bun test   # discovery, rows and formats, against recorded ps and ss output
```
