---
name: credentials
description: "Use for an API key or secret: when you need one, when you think one is absent, or before you give any process a key from a secrets file. Where secrets live and how to pass only one."
---

# Credentials: where to look, how to pass one

Never print a secret value, paste one into chat, or commit one.
Chat is journalled, so a secret typed there is burned.
Refer to a secret by variable name only.

## Search every secrets file before you say a key is absent

A host often has more than one secrets file, for example one for infrastructure keys and one for model keys.
List the candidates before you conclude "no key here":

    find "$HOME" -maxdepth 3 -name "*.env" -not -path "*/node_modules/*" 2>/dev/null

Check variable names only, never values:

    cut -d= -f1 "$SECRETS_FILE" | sort

A search of one file is not a search of the host.
Never tell the owner a key is missing, or contradict them about their own host, on a partial search.
A browser session can also give the access you need: check it before you ask for a credential.

## Never source a whole secrets file into a process that runs code

`set -a; . "$SECRETS_FILE"` is the reflex, and it is the wrong one.
It puts every variable in the file, such as cloud tokens, app private keys and payment keys, into the process.
If that process can run code for a model or a browser tab (a shell, an editor, a dev server, a sandbox), one prompt-injected turn can run `env` and read all of them.
The blast radius is every secret in the file, not the feature you enable.

Extract only the variable needed:

    KEY="$(sed -n 's/^PROVIDER_API_KEY=//p' "$SECRETS_FILE" | head -1 | tr -d "\"'")"
    export PROVIDER_API_KEY="$KEY"

Then verify the running process, not the script that started it:

    PID=$(pgrep -f "<the server>" | head -1)
    tr '\0' '\n' < /proc/$PID/environ | grep -ciE "^(CLOUDFLARE|AWS|SLACK|STRIPE|GITHUB)"   # want 0
    tr '\0' '\n' < /proc/$PID/environ | grep -c "="                                         # want small

## Storing a new secret

Write it to the secrets file at mode 600 and refer to it by name.
Never put it in a repo, a brief, a log, a commit or a chat message.
Never rotate a credential yourself: report the exposure to the owner.
