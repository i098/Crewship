# Crewship architecture

## Host layout

<!-- ondine:eNptks1qwzAMx-97Cr1AX2CFwT4OPYyxse5kelBsNQ51rCA5DYU-_IicLmzMF1vS35L8s46JJx9RCuyf7gAA0Pt9VxLdw-fnDoTQR1LYkQQBzAGwpVx0C43wpCRaJZCYhwb9CQZsSaFE4bGNUCLBgKoTS4AWC0142cIL-xMJDMLnLpDCxHKaU835AxaEM6exJ7WGfOooFzd3U48H2GweIM4dmWDpxD3V3cLXW9ErlDFnSqbUsWkFhwiRtbivZsxltPPBwvPqMWNL4r6UBPSihfpQM6YutyTXWthVIEpyJllvW8zaOyai4h5nWPW8isw00Y2h27GWH2tVBuPkFlzP3A-sVJ9fkbk3zhthLov996pJZ6LuDXv6DXfVVkLuOfEYjgmF4GPs_An25q_1lr9z738-c82yOExtQ-BebzMxUVNd_0GwgPkpB9vrWyxYmJOP2OUFpU0Inc2vh29w4-jK -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://ondine.sh/eNptks1qwzAMx-97Cr1AX2CFwT4OPYyxse5kelBsNQ51rCA5DYU-_IicLmzMF1vS35L8s46JJx9RCuyf7gAA0Pt9VxLdw-fnDoTQR1LYkQQBzAGwpVx0C43wpCRaJZCYhwb9CQZsSaFE4bGNUCLBgKoTS4AWC0142cIL-xMJDMLnLpDCxHKaU835AxaEM6exJ7WGfOooFzd3U48H2GweIM4dmWDpxD3V3cLXW9ErlDFnSqbUsWkFhwiRtbivZsxltPPBwvPqMWNL4r6UBPSihfpQM6YutyTXWthVIEpyJllvW8zaOyai4h5nWPW8isw00Y2h27GWH2tVBuPkFlzP3A-sVJ9fkbk3zhthLov996pJZ6LuDXv6DXfVVkLuOfEYjgmF4GPs_An25q_1lr9z738-c82yOExtQ-BebzMxUVNd_0GwgPkpB9vrWyxYmJOP2OUFpU0Inc2vh29w4-jK.svg?scheme=dark">
  <img alt="SSH reaches Herdr and agents; browsers reach loopback pages through the password gateway; Docker provides workers and data volumes" src="https://ondine.sh/eNptks1qwzAMx-97Cr1AX2CFwT4OPYyxse5kelBsNQ51rCA5DYU-_IicLmzMF1vS35L8s46JJx9RCuyf7gAA0Pt9VxLdw-fnDoTQR1LYkQQBzAGwpVx0C43wpCRaJZCYhwb9CQZsSaFE4bGNUCLBgKoTS4AWC0142cIL-xMJDMLnLpDCxHKaU835AxaEM6exJ7WGfOooFzd3U48H2GweIM4dmWDpxD3V3cLXW9ErlDFnSqbUsWkFhwiRtbivZsxltPPBwvPqMWNL4r6UBPSihfpQM6YutyTXWthVIEpyJllvW8zaOyai4h5nWPW8isw00Y2h27GWH2tVBuPkFlzP3A-sVJ9fkbk3zhthLov996pJZ6LuDXv6DXfVVkLuOfEYjgmF4GPs_An25q_1lr9z738-c82yOExtQ-BebzMxUVNd_0GwgPkpB9vrWyxYmJOP2OUFpU0Inc2vh29w4-jK.svg?scheme=light">
</picture>
<!-- /ondine -->

Ansible manages the host; optional containers keep separate process and filesystem lifecycles. The [password gateway](gateway.md) is the default way to open the agents' web pages from a browser.

## Provisioning

<!-- ondine:eNplkbFuxCAMhvc-hV8gub1DpestHbr1NpTBB05BRwLCJKd7-wpMKqpO4N-fbfg9-_DQFlOG6_sLAABqfXXZ0yt8BM6gwzq77y1hdmGFiMzEsKN3RhRcDcREu6MH3GgOieC8srt5AozRu0JTcrMjA4k8YakvRbylnZ4M2dLvEDJgA-f6DhP0XY0nti6ObGs4wTC8NViNPmj0p8KPz8VPtUhyFXMrR9K5a9EUIVtQUdaWFlRf9eg-J6RkZXQxqutY4za5elig5oa6WNL3YQmGDknIw63CetxWbbuOIgh42KU-MRPn_z5OXY9aIdeqoixBHcuIKczOE0vrlq1kcVBd_m5AqHITg-quumeKMP0Ar0jDFA -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://ondine.sh/eNplkbFuxCAMhvc-hV8gub1DpestHbr1NpTBB05BRwLCJKd7-wpMKqpO4N-fbfg9-_DQFlOG6_sLAABqfXXZ0yt8BM6gwzq77y1hdmGFiMzEsKN3RhRcDcREu6MH3GgOieC8srt5AozRu0JTcrMjA4k8YakvRbylnZ4M2dLvEDJgA-f6DhP0XY0nti6ObGs4wTC8NViNPmj0p8KPz8VPtUhyFXMrR9K5a9EUIVtQUdaWFlRf9eg-J6RkZXQxqutY4za5elig5oa6WNL3YQmGDknIw63CetxWbbuOIgh42KU-MRPn_z5OXY9aIdeqoixBHcuIKczOE0vrlq1kcVBd_m5AqHITg-quumeKMP0Ar0jDFA.svg?scheme=dark">
  <img alt="Host configuration passes validation and preview before Ansible applies verified releases and surveys the configured host" src="https://ondine.sh/eNplkbFuxCAMhvc-hV8gub1DpestHbr1NpTBB05BRwLCJKd7-wpMKqpO4N-fbfg9-_DQFlOG6_sLAABqfXXZ0yt8BM6gwzq77y1hdmGFiMzEsKN3RhRcDcREu6MH3GgOieC8srt5AozRu0JTcrMjA4k8YakvRbylnZ4M2dLvEDJgA-f6DhP0XY0nti6ObGs4wTC8NViNPmj0p8KPz8VPtUhyFXMrR9K5a9EUIVtQUdaWFlRf9eg-J6RkZXQxqutY4za5elig5oa6WNL3YQmGDknIw63CetxWbbuOIgh42KU-MRPn_z5OXY9aIdeqoixBHcuIKczOE0vrlq1kcVBd_m5AqHITg-quumeKMP0Ar0jDFA.svg?scheme=light">
</picture>
<!-- /ondine -->

Validate the host file, preview the changes, then apply selected profiles; omp plugins have no publisher checksums.

## Agent fleet and supervision

<!-- ondine:eNp1UUluwzAMvPcVfEDzgRYo0AVFLz0lQA-CD4xEx0IV0SAlpwH8-MKSEydFetFCzVDDmTbwwXYoCTYvdwAAaO3Gp0AP8O5F0x4TgeaeZPBKClbooJA64bzrwMct_5ACRgeaMGWF1gfSxxmXlQDd4JVF7wuq1gueLEc39VewGALs2VGAXnjwjkSLGsux9TuzJnLk5lsWTJ5jA6vVE7QnkeYstynM88MEG5fPoEOJpDpeCDDrRcsttvPaY7Id9By8PY51CvO6zGI5p5nakTgxH9MKPUbSKrRQCoAHkoDHQgfe96fCX1y1avof9RgtCA2eDuPJUPNc9-YaPOdg3rLgNtBVLBU6V4otc7Ce47jMfMMBHzVJtpPvOtbYzRfLN0m91M7l-N8U52TN51XQs6gloEvsL74Y66w -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://ondine.sh/eNp1UUluwzAMvPcVfEDzgRYo0AVFLz0lQA-CD4xEx0IV0SAlpwH8-MKSEydFetFCzVDDmTbwwXYoCTYvdwAAaO3Gp0AP8O5F0x4TgeaeZPBKClbooJA64bzrwMct_5ACRgeaMGWF1gfSxxmXlQDd4JVF7wuq1gueLEc39VewGALs2VGAXnjwjkSLGsux9TuzJnLk5lsWTJ5jA6vVE7QnkeYstynM88MEG5fPoEOJpDpeCDDrRcsttvPaY7Id9By8PY51CvO6zGI5p5nakTgxH9MKPUbSKrRQCoAHkoDHQgfe96fCX1y1avof9RgtCA2eDuPJUPNc9-YaPOdg3rLgNtBVLBU6V4otc7Ce47jMfMMBHzVJtpPvOtbYzRfLN0m91M7l-N8U52TN51XQs6gloEvsL74Y66w.svg?scheme=dark">
  <img alt="Firstmate supervises crews through inboxes and status files; crews use advisors, and crews and secondmates call model providers" src="https://ondine.sh/eNp1UUluwzAMvPcVfEDzgRYo0AVFLz0lQA-CD4xEx0IV0SAlpwH8-MKSEydFetFCzVDDmTbwwXYoCTYvdwAAaO3Gp0AP8O5F0x4TgeaeZPBKClbooJA64bzrwMct_5ACRgeaMGWF1gfSxxmXlQDd4JVF7wuq1gueLEc39VewGALs2VGAXnjwjkSLGsux9TuzJnLk5lsWTJ5jA6vVE7QnkeYstynM88MEG5fPoEOJpDpeCDDrRcsttvPaY7Id9By8PY51CvO6zGI5p5nakTgxH9MKPUbSKrRQCoAHkoDHQgfe96fCX1y1avof9RgtCA2eDuPJUPNc9-YaPOdg3rLgNtBVLBU6V4otc7Ce47jMfMMBHzVJtpPvOtbYzRfLN0m91M7l-N8U52TN51XQs6gloEvsL74Y66w.svg?scheme=light">
</picture>
<!-- /ondine -->

Firstmate supervises work through inboxes and status files; crews use the dispatch policy and call model providers directly.

### Stall nudge

A main Firstmate session can go idle after a context compaction and never start a turn, while wakes queue behind it. Hosts with the `firstmate` profile run `fm-main-stall-nudge.timer`, which starts `~/.local/bin/fm-main-stall-nudge` every 15 s (`journalctl --user -u fm-main-stall-nudge.service`). The script types a short nudge into main's Herdr pane when an operator note in `state/inbox` waits more than 45 s or a row in `state/.wake-queue` waits more than 600 s. It also nudges once for each answer a user left on a Lavish board (`~/.lavish-axi/state.json`) that nobody replied to within 300 s, for up to 24 h; `state/.stall-nudge-boards` records the answers it nudged, and a failed send leaves the answer unrecorded so the next try nudges it again. It nudges at most every 120 s.

It finds main as the pane in the Herdr session `default` that runs an agent in the Firstmate home. With no such pane, it logs a line and stops. A failed send is logged and the next try waits for the gap. Override the thresholds (`crewship_stall_nudge_note_max`, `crewship_stall_nudge_wake_max`, `crewship_stall_nudge_board_max`, `crewship_stall_nudge_gap`), the session, or pin a pane id (`crewship_stall_nudge_pane`) in `blueprint/ansible/group_vars/all/stall_nudge.yml`.

### Stuck-composer guard

`fm-send` skips its doorbell while a second mate's input box holds text, so a half-typed line can leave an inbox message unread. Hosts with the `firstmate` profile install `state/stuck-composer.check.sh` in the Firstmate home and bind it with `bin/fm-check-register.sh`, so the watcher runs it every cycle. For each second mate with an inbox message older than 120 s, the check reads the last composer line. If that text has not changed for 120 s, it saves the text to `state/.stuck-composer/<mate>.<epoch>.txt`, clears the line, rings the doorbell and prints one line for main. It reads panes at most every 30 s. A changed script is registered again on the next apply. Override the values (`crewship_stuck_composer_msg_age`, `crewship_stuck_composer_hold`, `crewship_stuck_composer_poll`) in `blueprint/ansible/group_vars/all/stuck_composer.yml`.

### GitHub reply alerts

Set `crewship_gh_replies_account` (the host's GitHub login) in `blueprint/ansible/group_vars/all/gh_replies.yml` to wake main when someone else replies on GitHub. An empty account installs nothing. The playbook installs `~/.local/bin/fm-gh-replies`, writes `state/gh-replies.check.sh` in the Firstmate home and registers it with `bin/fm-check-register.sh`, so the watcher polls it on its normal check cadence.

The script reads `GET /notifications` through `gh` (REST only; the host's `gh` login supplies the token) at most every `crewship_gh_replies_interval` seconds (60). For each new comment or review by another person it prints one line with repository, kind, author and URL, never the body. It ignores the account itself and bots. `state/.gh-replies/` holds the poll time, the `since` mark and the seen ids; the first run only seeds the mark.

### Instagram DM alerts

Set `crewship_instagram_dm_operator` (the operator's numeric Instagram user id) in `blueprint/ansible/group_vars/all/instagram_dm.yml` to wake main when the operator DMs the agent's Instagram account, and to let main answer. An empty id installs nothing. The playbook installs the [`instagram-dm`](../blueprint/skills/public/instagram-dm/SKILL.md) script as `~/.local/bin/instagram_dm.py`, the command `~/.local/bin/fm-insta-reply`, the service `instagram-dm-listen.service` and the backstop timer `instagram-dm-poll.timer`. The units wait until the session file exists: run `instagram_dm.py login` once (see the skill).

The service keeps Instagram's realtime channel (MQTT) open on the saved session. Each message event runs one poll, so a DM arrives in seconds. The event is a doorbell only: the poll reads the inbox and the message requests over HTTP, so the private event format is never parsed. A dead channel reconnects with backoff. Events are coalesced: any number of them cause one poll, at least 30 s after the last poll. The timer runs the same poll every `crewship_instagram_dm_interval` seconds (300) plus or minus 60 s in case an event is missed. Both take one lock, so a message is handled once.

A poll accepts a message request only from a thread that holds the operator alone and ignores every other sender. For each new message of the operator it runs `crewship_instagram_dm_notify` (`fm-inbox.sh note --request-id ig-ID -- "[Instagram DM from NAME; answer with fm-insta-reply] URL (by @AUTHOR, N s) caption: \"CAPTION\""`, which wakes main within about a second and makes a repeat harmless), appends one JSON line to `state/instagram-dms.jsonl`, and marks the message seen (the read receipt). It downloads no media and makes no request beyond the inbox reads: the author, caption and duration of a shared reel come from the DM payload and go into the note and the log row (`meta`), so Firstmate needs no fetch to know what it is. `state/.instagram-dms/poll.json` holds the last 5000 message ids, the failure count and the backoff. `fm-insta-reply [TEXT] [--thread ID] [--react EMOJI] [--typing]` answers the operator only, one short plain text at most.

Every write (text, tapback, typing indicator, read receipt) goes through one limiter, whose memory is `state/.instagram-dms/poll.json`: at least 20 s plus 0-10 s of random jitter after the previous write, at most 10 texts an hour and 40 a day, at most 20 tapbacks and typing indicators an hour together, and a typing indicator only before a text longer than 100 characters. A read receipt is skipped, not delayed, when it falls inside the gap. After any error, sends stop for 30 min (reads follow the shorter backoff below). A send over a limit exits with `not sending: ...`. Set the limits as `KEY=value` lines in `dm.env` next to the session file (`~/.config/crewship/instagram/dm.env`, read by the poll, the listener and `fm-insta-reply`): `INSTAGRAM_DM_WRITE_GAP`, `INSTAGRAM_DM_WRITE_JITTER`, `INSTAGRAM_DM_REPLIES_HOUR`, `INSTAGRAM_DM_REPLIES_DAY`, `INSTAGRAM_DM_SIGNALS_HOUR`, `INSTAGRAM_DM_ERROR_COOLDOWN`, `INSTAGRAM_DM_REALTIME_GAP`.

After a failed call the next calls wait 2, 4, 8 ... times the interval, up to 30 min, and every command refuses to call Instagram meanwhile. The first challenge, feedback block, suspension, `login_required`, please-wait, throttle or bad password halts them with no retry: main gets one note and nothing calls Instagram until a human has checked the account in the app and runs `instagram_dm.py resume`. Nothing logs in by itself: a missing or dead session is such a halt, and the one login is the manual `instagram_dm.py login` (`--force` for a second). Every failure names its exception class and endpoint.

A halt writes a flag file, `state/.instagram-dms/stop`, with its reason. `poll`, `listen`, `reply`, the reel curator, the front desk and `reel_watch.py` all check it and do nothing while it exists (the desk logs `skip (line stopped)`, drops the burst, and calls neither its model nor `fm-insta-reply`). `instagram_dm.py stop` is the kill switch: it writes the same flag by hand, with no Instagram call, and `instagram_dm.py resume` removes it. `reel_watch.py` finds the flag through `INSTAGRAM_DM_DIR` (default `~/.local/state/instagram-dm`): set that variable to the DM state directory in the environment of any agent that runs it.

See [Instagram front desk](imessage.md#instagram-front-desk) for the `instagram-desk.service` acknowledgement contract.

#### Official Instagram API

`crewship_instagram_dm_backend: graph` moves the line to Meta's official Instagram API with Instagram Login (no Facebook Page, Standard Access). The default, `instagrapi`, keeps everything above; the instagrapi units are not changed by the switch. With `graph`:

- `crewship_instagram_dm_operator` is the operator's Instagram-scoped id (IGSID). A DM from any other sender is ignored, and `fm-imessage` logs `instagram webhook: ignored a DM from <IGSID>`, so his first DM shows the id to set.
- The card-page listener of `fm-imessage` (public at the `imessage.cards.url` address, for example `https://cards.crewship.si`) answers `/instagram/webhook`: the Meta webhook verification (`hub.verify_token`) and the signed `messages` events (`X-Hub-Signature-256`, HMAC-SHA256 with the app secret; an unsigned or wrongly signed event gets `403`). Each new DM of the operator goes to `crewship_instagram_dm_notify` and `state/instagram-dms.jsonl` in the same form as above, deduplicated on the message id. A shared reel gives its CDN URL, media id and caption from the payload; nothing fetches the media.
- `fm-insta-reply` keeps its options and sends through `POST graph.instagram.com/v25.0/me/messages` (text, tapback, typing). It refuses, with the reason on stderr, when his last DM is 24 h old or older: Meta allows sends only in that window.
- The token lives in `state/.instagram-dms/graph-token.json` (mode 600). Generate a 60-day token in the Meta App Dashboard and save it with `bun ~/.local/share/crewship/instagram-desk/instagram-graph.ts token < file` (with `INSTAGRAM_DM_DIR` set to the state directory). `instagram-graph-refresh.timer` runs `instagram-graph.ts refresh` weekly; it refreshes only a token older than 24 h, the Meta rule.
- `INSTAGRAM_GRAPH_APP_SECRET` and `INSTAGRAM_GRAPH_VERIFY_TOKEN` go in `dm.env` (mode 600), which `fm-imessage` then reads. No secret is in the repository or a unit file.

### Instagram reel curator

`instagram-reel-curator.timer` (09, 14 and 19 h, plus up to 90 min of jitter) runs `~/.local/bin/reel_curator.py run` as a user service. The curator is OFF by default: `crewship_instagram_curator_enabled: true` renders and enables the timer (false removes it). It scrapes feeds and downloads clips, which the DM bot never does, so it runs on its own Instagram account, never the DM bot's: its session is `crewship_instagram_curator_session` (log in once with `INSTAGRAM_DM_SESSION=<that file> INSTAGRAM_DM_TIMEZONE=<zone> instagram_dm.py login`) and its limiter and halt state are `crewship_instagram_curator_state`, not the DM line's. The script refuses to run on the DM bot's session file. The service waits until that session file and `crewship_instagram_curator_config` (`curator.json`: the seed `accounts` and `hashtags`, kept on the host, never in the repository) exist. A run makes at most 40 Instagram calls (`max_calls`) and then ends quietly. It does not start within 60 min of DM activity on the DM line (`dm_quiet_s`, from the mtime of the message and send logs), for 24 h after a halt of the DM line (`halt_quiet_s`), or while the DM line is stopped (`instagram_dm.py stop`). Its sends go through its own account's limiter. It skips a reel found in `reels.jsonl` or in the operator's thread, transcribes with the `watch` skill, scores with one `omp -p` call, and shares at most 3 reels a day into the operator's thread with one line. Every pick, rejection, follow and halt is a line in `crewship_instagram_curator_log` with its score. A challenge, a 429 or `feedback_required` writes a `halt` row and stops the curator for 24 h. See the [skill](../blueprint/skills/public/instagram-dm/SKILL.md#reel-curator).

### Usage card

The stall nudge service has a second `ExecStart`, `~/.local/bin/fm-usage-remind`. While the owner texts (an iMessage note in `state/inbox` younger than 2 min), it runs `fm-usage-brief --png` and sends the card with `fm-imessage --image`, at most once per `crewship_usage_remind_every` seconds (default 3600). The card shows the 5 h and 7 d use of Claude and Codex, averaged across accounts, each with its soonest reset (from `omp usage --json`), plus server load, RAM and the mounts in `crewship_usage_disks` (default `/`). `fm-usage-brief` alone prints the same figures as text. `fm-text-card OUT.png < text` renders any short update as a card 840 px wide and at least 630 px high (about 4:3, so iMessage does not crop it; the constants `CARD_WIDTH` and `CARD_MIN_HEIGHT` in `fm-text-card`, which `fm-usage-brief` shares): the first line is the title, `# x` a section, `- x` a bullet, `k: v` a row. The scripts take their settings from `blueprint/ansible/group_vars/all/stall_nudge.yml`.

Cards are throwaway and nothing persists. `fm-usage-remind` renders to a temp file and deletes it as soon as the send returns.

The cards render with headless Chrome. The script uses `CHROME`, else `google-chrome`, `google-chrome-stable` or `chromium` on `PATH` (the `desktop` profile installs `google-chrome`; set `crewship_chrome_install: true` to install it without a desktop), else the Chrome that omp's puppeteer downloads under `~/.omp/puppeteer`. Set `CHROME` in the unit to use another binary. Both `ExecStart` lines carry the `-` prefix, so a failed nudge never blocks the card.

## iMessage

See [iMessage bridge](imessage.md) for the optional bridge and its routing contract.

## Boards

<!-- ondine:eNpdUUluwzAMvPcV8wF_oCkCNAW63AokPQk-yAptq5FNQ6SbBPDji5p2EeRESuJwFtWJz6H1WXHYPQCAD-EQNdEjnhvqVUCX0Pq-ISQOPqFin4_oSMQ3JBu8xizaeSVwJZR_SKAtdRt4CA0-_71o7Cgj8BBJUPlwStzA90eIeh0FyniL-j5WpmDmdUZf4qkottNXHy8QDifSyYS4l0xnU1POMJNXFFt01HG-uo--sA7KQwxyNzYtesF9uk6oVx_u35EBFr1uZ7U0ipgzZ2eql0xml4YxX25v9uqYSG5x84y1820UGUnWbXYq74eGzN8U1H1aXTjKm8gsqvVrpmXRL08tprE -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://ondine.sh/eNpdUUluwzAMvPcV8wF_oCkCNAW63AokPQk-yAptq5FNQ6SbBPDji5p2EeRESuJwFtWJz6H1WXHYPQCAD-EQNdEjnhvqVUCX0Pq-ISQOPqFin4_oSMQ3JBu8xizaeSVwJZR_SKAtdRt4CA0-_71o7Cgj8BBJUPlwStzA90eIeh0FyniL-j5WpmDmdUZf4qkottNXHy8QDifSyYS4l0xnU1POMJNXFFt01HG-uo--sA7KQwxyNzYtesF9uk6oVx_u35EBFr1uZ7U0ipgzZ2eql0xml4YxX25v9uqYSG5x84y1820UGUnWbXYq74eGzN8U1H1aXTjKm8gsqvVrpmXRL08tprE.svg?scheme=dark">
  <img alt="Agents exchange local board messages; Firstmate observes them; a separate timer copies backlog and status to GitHub" src="https://ondine.sh/eNpdUUluwzAMvPcV8wF_oCkCNAW63AokPQk-yAptq5FNQ6SbBPDji5p2EeRESuJwFtWJz6H1WXHYPQCAD-EQNdEjnhvqVUCX0Pq-ISQOPqFin4_oSMQ3JBu8xizaeSVwJZR_SKAtdRt4CA0-_71o7Cgj8BBJUPlwStzA90eIeh0FyniL-j5WpmDmdUZf4qkottNXHy8QDifSyYS4l0xnU1POMJNXFFt01HG-uo--sA7KQwxyNzYtesF9uk6oVx_u35EBFr1uZ7U0ipgzZ2eql0xml4YxX25v9uqYSG5x84y1820UGUnWbXYq74eGzN8U1H1aXTjKm8gsqvVrpmXRL08tprE.svg?scheme=light">
</picture>
<!-- /ondine -->

The optional crew board keeps temporary host-local messages (see [how it is built](../apps/crewboard/README.md)); the GitHub board reads backlog and status without changing supervision.

## Data boundaries

<!-- ondine:eNp1kkFOAzEMRfecwhcYDkClSsAGdixGYhHNwmQ8ndA0jmKnFdIcHiVpChJiFzsv9v92Fs8Xu2JSGJ_uAADQ2tGppwcYV4JE1kUCy2Fxh5xIQJm9AIYZLpyOlGQHMfEnWQWMUSALgVDEhEowo-IHloyiPcoOMOtKQZ1FdRxqGdFCiuIXcFZxM4HeOldJ7WjeEp-dOA4uHK65CYZhf1VnRmZ_U1rrT7-eV7JJNq_CHpW6hYa1c8XO7POJxDzzKbI0Gz3Z4Jh4cb5qqta7Uek3TVm1_QeCSKkPrZWrXH1B4WzeOR01EZUAhGjuEktcoDLoH6pE7b4uYBj2G8bo-4w14bI4u7Umjcu6msd_VjHBcD_st76LNr0NVhY1LyxafgjnoNM3BBDJVA -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://ondine.sh/eNp1kkFOAzEMRfecwhcYDkClSsAGdixGYhHNwmQ8ndA0jmKnFdIcHiVpChJiFzsv9v92Fs8Xu2JSGJ_uAADQ2tGppwcYV4JE1kUCy2Fxh5xIQJm9AIYZLpyOlGQHMfEnWQWMUSALgVDEhEowo-IHloyiPcoOMOtKQZ1FdRxqGdFCiuIXcFZxM4HeOldJ7WjeEp-dOA4uHK65CYZhf1VnRmZ_U1rrT7-eV7JJNq_CHpW6hYa1c8XO7POJxDzzKbI0Gz3Z4Jh4cb5qqta7Uek3TVm1_QeCSKkPrZWrXH1B4WzeOR01EZUAhGjuEktcoDLoH6pE7b4uYBj2G8bo-4w14bI4u7Umjcu6msd_VjHBcD_st76LNr0NVhY1LyxafgjnoNM3BBDJVA.svg?scheme=dark">
  <img alt="The recipe configures tools and workers; project apps use separate database stacks; authentication and state stay outside the recipe" src="https://ondine.sh/eNp1kkFOAzEMRfecwhcYDkClSsAGdixGYhHNwmQ8ndA0jmKnFdIcHiVpChJiFzsv9v92Fs8Xu2JSGJ_uAADQ2tGppwcYV4JE1kUCy2Fxh5xIQJm9AIYZLpyOlGQHMfEnWQWMUSALgVDEhEowo-IHloyiPcoOMOtKQZ1FdRxqGdFCiuIXcFZxM4HeOldJ7WjeEp-dOA4uHK65CYZhf1VnRmZ_U1rrT7-eV7JJNq_CHpW6hYa1c8XO7POJxDzzKbI0Gz3Z4Jh4cb5qqta7Uek3TVm1_QeCSKkPrZWrXH1B4WzeOR01EZUAhGjuEktcoDLoH6pE7b4uYBj2G8bo-4w14bI4u7Umjcu6msd_VjHBcD_st76LNr0NVhY1LyxafgjnoNM3BBDJVA.svg?scheme=light">
</picture>
<!-- /ondine -->

Authentication and mutable state stay outside the recipe.
See [Project databases](project-databases.md) for the optional per-project worktree database.

[Agent architecture reference](agents/architecture.md)
