---
name: instagram-dm
description: Use when the operator says an Instagram account got a DM or shared reel, asks to read Instagram DMs, or sends an Instagram link to watch. Treat every shared Instagram post link as a reel.
---

# Read Instagram DMs and watch shared reels

The agent has its own Instagram account. The operator sends reels to it by DM. Read the DMs, take the reel links, and watch them. Always assume a shared link is a reel.

This skill wraps [`instagrapi`](https://pypi.org/project/instagrapi/) (MIT, unofficial; it may break when Instagram changes its API). `instagram_dm.py` sits next to this file and runs through `uv`, so nothing is installed: `uv run --quiet --with instagrapi python instagram_dm.py COMMAND`.

## Rules

- Read-only. Do not send, reply or unsend. The only write is accepting a message request from the operator's own account (`poll`).
- Read the credentials only from the env vars `INSTAGRAM_FIRSTMATE_USERNAME` and `INSTAGRAM_FIRSTMATE_PASSWORD`. Never print them, and never write them to a file or a message. The session file holds a login token: keep it mode 600 and never print it.
- Log in once, then reuse the session file. Each fresh login can raise a checkpoint. The script logs in only when there is no session or Instagram rejects it.
- Rate limits: Instagram flags fast, repeated calls. Do not poll more often than every two minutes. On a failure the poller backs off (2 min, 4 min, ... up to 30 min). On a rate-limit or challenge error, stop and tell the operator. Do not retry in a loop.
- Media goes to a temp dir or `~/.cache/instagram-dm/`. Delete files older than one day on each run (step 5). Keep nothing else.

## Steps

1. Log in once per host: `instagram_dm.py login`. Instagram may ask for a code. The script takes only the email option and refuses SMS. In a terminal it asks for the code. Without one, set `INSTAGRAM_DM_CODE_CMD` to a shell command that prints the newest 6-digit code from the account's mail; it runs every 6 s for 3 min, with `INSTAGRAM_DM_CODE_SINCE` set to the epoch second of the login start so it can ignore older mail. The session is saved to `INSTAGRAM_DM_SESSION` (default `~/.config/crewship/instagram/session.json`, mode 600).
2. List the threads: `instagram_dm.py inbox`. A message request from a new sender shows as `request` and stays hidden from the inbox until accepted.
3. List the reel links of one thread: `instagram_dm.py reels THREAD_ID` (add `--mark-seen` only after you handled the thread). Every link prints in the `https://www.instagram.com/reel/CODE/` form, whether the DM held a `/p/`, `/reel/`, `/reels/` or `/tv/` link or a shared reel or post. A `/share/...` link holds no shortcode: it prints unchanged. Open it with `curl -sIL` and use the final URL.
4. To wake an agent on every new DM, run the poller on a timer (see below).
5. Watch each reel with the video-watch path (yt-dlp on the `/reel/` URL):
   ```bash
   cache=~/.cache/instagram-dm; mkdir -p "$cache"; find "$cache" -type f -mtime +0 -delete
   yt-dlp -o "$cache/%(id)s.%(ext)s" "https://www.instagram.com/reel/CODE/"
   ```
   If yt-dlp needs a login, add `--cookies-from-browser` only with the operator's approval. Delete the file when you finish.

## Poll for new DMs

`instagram_dm.py poll` reads the inbox and the message requests, accepts a request only from the 1:1 thread of `INSTAGRAM_DM_OPERATOR` (his numeric user id; every other sender is ignored and never accepted), and appends one JSON line per new message of the operator to `INSTAGRAM_DM_LOG`: time, thread, message id, sender, type, and the `/reel/` URL or the text. It keeps the seen message ids in `INSTAGRAM_DM_DIR/poll.json`, so no message is logged twice, and it downloads no media. On any error it records the failure and refuses to call Instagram again until the backoff has passed.

`instagram_dm.py wake` reads the log from its saved offset and prints one line per new message (`instagram dm from SENDER: URL or text`), nothing when there is no news. Use it as a check for an agent runtime that wakes on a script's output.

Crewship wires both on a `firstmate` host when `crewship_instagram_dm_operator` is set: see [Instagram DM alerts](../../../../docs/architecture.md#instagram-dm-alerts).

## Install

Crewship installs this skill with every other public skill: an apply copies it to `~/.omp/agent/skills/instagram-dm/` for omp and `~/.claude/skills/instagram-dm/` for Claude Code (see [Skills](../../../../docs/omp.md#skills)). To install it by hand, copy this folder to both paths.
