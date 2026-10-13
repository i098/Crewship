---
name: slack-relay
description: Use when the operator wants important Slack messages texted to his phone, asks why a Slack relay text came or did not come, or wants to change who or what the relay keeps. Read-only; never writes to Slack.
---

# Relay important Slack messages to iMessage

`slack_relay.py` watches the cache database of the `slk` TUI and texts the operator the messages that matter. It drops the rest. A running `slk` keeps that cache current for every workspace it has configured, so the relay needs no Slack token and no new Slack client.

## Rules

- Read-only. The script opens the cache with `mode=ro` and never calls Slack. Do not add a post, a reaction, a read mark, an edit or a join, in any workspace. Do not open a workspace that the operator marked read-only in a mode that could write.
- The `slk` TUI must stay running (for example in a tmux pane). When it is stopped, the cache gets no new messages and the relay has nothing to send.
- Texts go out only with `fm-imessage`: at most one text per 60 s, one short line per kept message: who, where (DM, #channel, thread), and the message itself or a tight quote, plus the action in a few words when he must act. A text never holds a Slack link: he reads Slack in the `slk` tab on the same host. A burst becomes one text. The lines above the cap of 8 wait for the next window.
- A message is decided once. Its key (`workspace/channel/ts`) goes into the log, and an edit does not make it new.
- Messages from before the first run, or older than 6 h, are never sent.

## How it filters

Each cycle (every 15 s) reads the unseen messages of other people, with these facts for each: workspace, channel, type (DM, group, channel), sender, bot or not, whether it mentions the operator, whether it is in a thread he is in. One `omp -p` call (default `anthropic/claude-haiku-5-5`, at most 150 messages and 120 000 characters, so far under 100k tokens) answers keep or drop with a reason for each.

- Keep: DMs to him, @mentions, threads he is in, decisions, deadlines, asks of him, incidents, and teammates about his work.
- Drop: chatter, bots, announcements.
- A message the model skips is kept only when it is a human DM or a mention. A failed or unparsable call changes nothing: the messages stay unseen and the next cycle retries, with a backoff up to 5 min.

Every decision is one line in `~/.local/state/crewship/slack-relay/log.jsonl`: time, key, workspace, channel, ts, sender, `kept` or `dropped`, and the reason. To see why a text did or did not come, read that file.

## Config

`~/.config/crewship/slack-relay/config.json` (private to the host; the repo holds no names or ids):

```json
{
  "self": {"T0000000": "U0000000"},
  "operator_name": "the operator",
  "teammates": ["Name One", "Name Two"],
  "workspaces": {"T0000000": {"name": "Workspace"}}
}
```

`self` is required: the operator's own user id in each workspace (his messages are skipped). Find it as the user id that is the author of one of his own messages in the slk cache. A workspace without `self` is not relayed. `workspaces` gives the model a display name for each workspace. Optional keys and defaults: `db` (`~/.local/share/slk/cache.db`), `model`, `notify` (`["fm-imessage", "--"]`), `interval` 15, `window` 60, `lookback` 21600, `max_batch` 150, `max_chars` 120000, `text_chars` 700, `max_lines` 8.

## Install (opt-in)

```bash
install -m755 slack_relay.py ~/.local/bin/slack_relay.py
mkdir -p ~/.config/systemd/user && cp slack-relay.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now slack-relay.service
```

Both files sit next to this one. Write the config first. `slack_relay.py once` runs one cycle by hand. `slack_relay.py replay WORKSPACE CHANNEL TS` runs one cached message through the filter and texts it with a `[test]` prefix; it does not mark the message as seen.
