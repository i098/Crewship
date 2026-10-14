---
name: instagram-dm
description: Use when the operator says an Instagram account got a DM or shared reel, asks to read Instagram DMs, or sends an Instagram link to watch. Treat every shared Instagram post link as a reel.
---

# Read Instagram DMs and watch shared reels

The agent has its own Instagram account. The operator sends reels to it by DM. Read the DMs, take the reel links, and watch them. Always assume a shared link is a reel.

This skill wraps [`instagrapi`](https://pypi.org/project/instagrapi/) (MIT, unofficial; it may break when Instagram changes its API). `instagram_dm.py` sits next to this file and runs through `uv`, so nothing is installed: `uv run --quiet --with instagrapi python instagram_dm.py COMMAND`.

## Rules

- Send only through `fm-insta-reply`, and only to the operator. Do not send to anyone else, and do not unsend. The one other write is accepting a message request from the operator's own account (`poll`) and the read receipt it sends.
- Read the credentials only from the env vars `INSTAGRAM_FIRSTMATE_USERNAME` and `INSTAGRAM_FIRSTMATE_PASSWORD`. Never print them, and never write them to a file or a message. The session file holds a login token: keep it mode 600 and never print it.
- Log in once, by hand, then reuse the session file. Each fresh login can raise a checkpoint, so nothing logs in again by itself: a missing session file, one without its pinned device, or a session Instagram rejects (`login_required`) halts the line and asks a human. The first login pins a realistic device and the host's time zone in the session file. `login` refuses when the file exists; `login --force` keeps the pinned device and only follows a check of the account in the app.
- Rate limits: Instagram flags fast, repeated calls. Do not poll more often than every two minutes. On a failure the poller backs off (2 min, 4 min, ... up to 30 min). On a rate-limit or challenge error, stop and tell the operator. Do not retry in a loop.
- Media goes to a temp dir or `~/.cache/instagram-dm/`. Delete files older than one day on each run (step 5). Keep nothing else.

## Steps

1. Log in once per host: `instagram_dm.py login`. Instagram may ask for a code. The script takes only the email option and refuses SMS. In a terminal it asks for the code. Without one, set `INSTAGRAM_DM_CODE_CMD` to a shell command that prints the newest 6-digit code from the account's mail; it runs every 6 s for 3 min, with `INSTAGRAM_DM_CODE_SINCE` set to the epoch second of the login start so it can ignore older mail. The session is saved to `INSTAGRAM_DM_SESSION` (default `~/.config/crewship/instagram/session.json`, mode 600).
2. List the threads: `instagram_dm.py inbox`. A message request from a new sender shows as `request` and stays hidden from the inbox until accepted.
3. List the reel links of one thread: `instagram_dm.py reels THREAD_ID` (add `--mark-seen` only after you handled the thread). Every link prints in the `https://www.instagram.com/reel/CODE/` form, whether the DM held a `/p/`, `/reel/`, `/reels/` or `/tv/` link or a shared reel or post. A `/share/...` link holds no shortcode: it prints unchanged. Open it with `curl -sIL` and use the final URL.
4. To wake an agent on every new DM, run `listen` as a service and `poll` on a timer (see below).
5. Watch each reel with `reel_watch.py`. It runs the `watch` skill with no cookies and no login, one reel at a time and at least 20 s after the last fetch (a lock in `~/.cache/instagram-dm/`), so parallel agents cannot burst:
   ```bash
   python3 ~/.claude/skills/instagram-dm/reel_watch.py "https://www.instagram.com/reel/CODE/" --detail balanced --question "..."
   ```
   It takes the `watch.py` options and refuses `--cookies` and `--cookies-from-browser`. Never put `WATCH_COOKIES_FILE` in the watch config for Instagram: the DM account's session must never fetch media. With `GEONODE_GATEWAY`, `GEONODE_USERNAME`, `GEONODE_PASSWORD`, `GEONODE_STICKY_PORT_BASE` and `GEONODE_STICKY_PORT_MAX` set, it fetches through the Geonode residential proxy on a sticky port picked per fetch; with none set, it fetches direct. On a `challenge`, a login demand or a 403, stop and tell the operator: do not retry in a loop.

## Wake on new DMs, and reply

`instagram_dm.py listen` keeps Instagram's realtime channel open (a service that reconnects on its own). Each message event runs `poll`, so a DM reaches the agent in seconds. A timer that runs `poll` every few minutes is the backstop for a missed event. `poll` reads the inbox and the message requests and accepts a request only from the 1:1 thread of `INSTAGRAM_DM_OPERATOR` (his numeric user id; every other sender is ignored and never accepted). For each new message of the operator it:

1. runs `INSTAGRAM_DM_NOTIFY --request-id ig-ID -- "[Instagram DM from NAME; answer with fm-insta-reply] URL or text"` (for Firstmate, `fm-inbox.sh note`, which wakes main within about a second; the request id makes a repeat harmless),
2. appends one JSON line (time, thread, message id, sender, type, `/reel/` URL or text) to `INSTAGRAM_DM_LOG`,
3. marks the message seen, which is the read receipt.

It keeps the seen message ids in `INSTAGRAM_DM_DIR/poll.json`, so nothing repeats, and downloads no media. If the hand-over fails, nothing is logged and the next poll retries.

**When a wake says `[Instagram DM from NAME; answer with fm-insta-reply]`, answer on Instagram with `fm-insta-reply`.** Follow the same rules as for iMessage: short plain texts, no reaction spam.

```bash
fm-insta-reply "Got it, watching now."          # a text (at most 500 characters, whitespace collapsed)
fm-insta-reply --react "❤️"                      # react to his latest message
fm-insta-reply "On it." --typing                # show typing, then send
fm-insta-reply "text" --thread THREAD_ID        # a given thread; it must hold the operator alone
```

Every send, tapback and typing indicator is also appended to `INSTAGRAM_DM_SENT` (`sent.jsonl` in the state directory). A front desk on the host reads it to answer a DM that main left alone for about 8 s, and stands down on any row that is not from the desk (`INSTAGRAM_DM_ACTOR=desk`): see [Instagram front desk](../../../../docs/imessage.md#instagram-front-desk).

`--typing` publishes a typing indicator over the realtime channel for a few seconds (longer for a longer text) before it sends. The call returns without error when the broker takes the indicator. Instagram does not report whether the other side saw it.

Every send waits 3 s after the last one. After an Instagram error, `poll`, `listen` and `reply` share one exponential backoff (2, 4, 8 ... times the base, up to 30 min) and refuse to call Instagram until it passes. The first challenge, feedback block, suspension, `login_required`, please-wait, throttle (429) or bad password halts them instead, with no retry (the library's own challenge solving and HTTP retry are off): one note goes to the agent, nothing calls Instagram again, and a human opens the Instagram app, fixes the account, and runs `instagram_dm.py resume`. Do not log in again by hand to get past a halt. Every failure line carries the exception class and the endpoint; the front desk keeps the failure line of a send in its `desk.log`.

Crewship wires all of this on a `firstmate` host when `crewship_instagram_dm_operator` is set: see [Instagram DM alerts](../../../../docs/architecture.md#instagram-dm-alerts).

## Reel curator

`reel_curator.py` (next to `instagram_dm.py`) sends the operator the few reels worth watching. A user timer runs `reel_curator.py run` three times a day (09, 14 and 19 h, up to 90 min late). A cycle pulls new reels from the accounts and hashtags in `CURATOR_CONFIG` (default `~/.config/crewship/instagram/curator.json`), one slow request at a time, and drops every reel already in the log or in the operator's thread. It downloads the best liked, transcribes each with the `watch` skill (`WATCH_SCRIPT`, else `~/.omp/agent/skills/watch` or `~/.claude/skills/watch`), drops it as `non-english:<lang>` in the log when the speech or the caption is not English (the language the skill names, else a common-word count; a silent reel goes by its caption), then scores it with one `omp -p` call (`model`, default `anthropic/claude-haiku-5-5`; the input is clipped well under 100k tokens). A reel passes at `min_score` (7); engagement bait ("comment X for the link", "link in bio") needs `bait_min_score` (9). It resolves the real repo (the model's repo checked on GitHub, a GitHub URL in the caption, or a repo of that exact name found by search) and rejects a reel with no link. A pick is shared into the thread with `direct_media_share`, then one line: what it is, the link, why it matters. It sends at most `daily_cap` (3) a day and never likes, comments or posts.

```json
{"accounts": ["creator_one", "creator_two"], "hashtags": ["claudecode", "opensource"]}
```

The config holds the seed accounts and hashtags; any key of `DEFAULTS` in the script may be added to override it. `reel_curator.py follow` follows each listed account not yet followed, 3 to 10 minutes apart: run it once after you edit the list. Every pick, rejection, follow and halt is one line in `CURATOR_LOG` (default `~/.local/state/crewship/instagram/reels.jsonl`) with its score. On a challenge, a 429 or `feedback_required` the curator logs a `halt` row and does nothing for 24 h; a flagged account (challenge, feedback block) also halts the DM poller as above.

## Install

Crewship installs this skill with every other public skill: an apply copies it to `~/.omp/agent/skills/instagram-dm/` for omp and `~/.claude/skills/instagram-dm/` for Claude Code (see [Skills](../../../../docs/omp.md#skills)). To install it by hand, copy this folder to both paths.
