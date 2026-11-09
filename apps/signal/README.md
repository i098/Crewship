# Signal bridge

Send a secret from your phone to the host in a Signal "Note to Self".
The host saves it in the secrets file.
No iMessage, chat transcript, log or repository sees the value.

## What it does

`signal_bridge.py` runs `signal-cli jsonRpc` as a linked device of your own Signal account.
It acts on one kind of message only: a Note to Self from that account, in this exact form:

```text
secret NAME=value
```

`NAME` matches `[A-Z][A-Z0-9_]*`.
`value` is one line, without a line break.
Every other message is dropped unread: other chats, groups, and a note in any other form.

For a valid note the bridge:

1. Writes `export NAME='value'` to the secrets file (`~/super.env` by default), with correct shell quoting.
   It writes a temporary file in the same directory, then renames it over the secrets file, mode 600.
   A line that already sets `NAME` is replaced.
   Every other byte of the file stays as it was.
   A symlinked secrets file stays a symlink.
2. Replies in Note to Self with `saved NAME`.

The value is never in stdout, stderr, the journal, an exception text or a reply.
The bridge logs key names and error classes only.
Never run `signal-cli` with `--verbose` for this account: that level logs message text.

## Enable it

Set `signal` in `.local/host.yml`.
It is off when absent, and the playbook installs nothing for it.

```yaml
crewship:
  signal:
    account: "+15551234567"        # the number of your Signal account
    secrets_file: /home/you/super.env   # optional; the default is ~/super.env
```

`./ship.sh launch` installs the latest `signal-cli` release (checksum verified), `~/.local/bin/fm-signal`, and the `fm-signal.service` user unit.
The `signal-cli` native build exists for Linux x86_64 only.
The unit waits until the account is linked.

## Link your phone (one step on the phone)

On the host, run:

```bash
signal-cli link -n crewship
```

It prints a QR code in the terminal.
On the phone: open Signal, go to **Settings > Linked devices > Link new device**, and scan the QR code.
Then restart the bridge:

```bash
systemctl --user restart fm-signal
```

The bridge uses your existing Signal account.
It needs no new phone number and no paid service.

## Send a secret

In Signal, open **Note to Self** and send:

```text
secret GITHUB_TOKEN=ghp_example
```

The bridge replies `saved GITHUB_TOKEN`.
Delete your note on the phone afterward.

## Limits

- signal-cli has no command that deletes a received message from its local store.
  It keeps no decrypted message body.
  It caches the encrypted envelope of a message and removes it once it has handled the message.
  The bridge therefore cannot delete anything more, and the note stays in Note to Self on your phone until you delete it.
- A value must be one line.
  A value that an editor spread over several lines in the secrets file is not replaced correctly.
- The bridge reads and replaces the secrets file as a whole.
  Another program that writes the file at the same moment can lose its change.
- A phone with number privacy may hide the account number in a message.
  Such a message is ignored.
  Use the account's ACI as `account` in that case.
- `scripts/fetch-secrets.sh` replaces `~/super.env` from the fleet-secrets Worker and drops a value the Worker lacks.
  Run `scripts/stow-secrets.sh` after a save when the Worker holds your secrets.

## Tests

`tests/test_signal_bridge.py` uses fixtures and a fake `signal-cli`.
It never touches a real account or a real secrets file.
