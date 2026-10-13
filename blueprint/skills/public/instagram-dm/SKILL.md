---
name: instagram-dm
description: Use when the operator says an Instagram account got a DM or shared reel, asks to read Instagram DMs, or sends an Instagram link to watch. Treat every shared Instagram post link as a reel.
---

# Read Instagram DMs and watch shared reels

The agent has its own Instagram account. The operator sends reels to it by DM. Read the DMs, take the reel links, and watch them. Always assume a shared link is a reel.

This skill wraps [`instagram-cli`](https://www.npmjs.com/package/@i7m/instagram-cli) (npm `@i7m/instagram-cli`, source repository `supreme-gg-gg/instagram-cli`, MIT, unofficial; it may break when Instagram changes its API). Its own agent guide is `skills/instagram-skill/SKILL.md` in that source repository. It was not vendored: it forbids the agent to log in and covers sending, and this skill needs env-var login and a reel hand-off.

## Rules

- Read-only. Do not run `send`, `reply` or `unsend` unless the operator asks for it in this conversation.
- Read the credentials only from the env vars `INSTAGRAM_FIRSTMATE_USERNAME`, `INSTAGRAM_FIRSTMATE_PASSWORD` and (if 2FA is on) `INSTAGRAM_FIRSTMATE_TOTP`. Never print them, and never write them to a file or a message.
- Rate limits: Instagram flags fast, repeated calls. Make one `inbox` call, then one `reels` call per thread with unread messages. Do not poll more often than every few minutes. On a rate-limit or challenge error, stop and tell the operator. Do not retry in a loop.
- Media goes to a temp dir or `~/.cache/instagram-dm/`. Delete files older than one day on each run (step 4). Keep nothing else.

## Steps

1. Install once (needs Node.js 22 or newer): `npm install -g @i7m/instagram-cli`. Homebrew also works: `brew tap supreme-gg-gg/tap && brew install instagram-cli`.
2. Log in once per host: `instagram_dm.py login` (the script sits next to this file). It reuses a saved session when one exists.
3. List the threads: `instagram_dm.py inbox`. Then list the reel links of one thread: `instagram_dm.py reels THREAD_ID` (add `--mark-seen` only after you handled the thread). Every link prints in the `https://www.instagram.com/reel/CODE/` form, whether the DM held a `/p/`, `/reel/`, `/reels/` or `/tv/` link. A `/share/...` link cannot be normalised: open it with `curl -sIL` and use the final URL.
4. Watch each reel with the video-watch path (yt-dlp on the `/reel/` URL):
   ```bash
   cache=~/.cache/instagram-dm; mkdir -p "$cache"; find "$cache" -type f -mtime +0 -delete
   yt-dlp -o "$cache/%(id)s.%(ext)s" "https://www.instagram.com/reel/CODE/"
   ```
   If yt-dlp needs a login, add `--cookies-from-browser` only with the operator's approval. Delete the file when you finish.

## Install

Crewship installs this skill with every other public skill: an apply copies it to `~/.omp/agent/skills/instagram-dm/` for omp and `~/.claude/skills/instagram-dm/` for Claude Code (see [Skills](../../../../docs/omp.md#skills)). To install it by hand, copy this folder to both paths.
