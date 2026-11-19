# Google Workspace CLI

The `agents` profile installs `gws`, the [Google Workspace CLI](https://github.com/googleworkspace/cli), to `~/.local/bin/gws` ([Dependencies](dependencies.md#latest-releases)). It has one command for Drive, Gmail, Calendar, Sheets, Docs, Chat and more. Apply does not sign in any account. This page shows how an operator signs in one or more Google accounts on a headless host.

`gws` has no built-in OAuth client, so you supply one from a Google Cloud project. It also has no account switch: one config directory holds one login, and `GOOGLE_WORKSPACE_CLI_CONFIG_DIR` selects the directory.

Keep passwords, the client secret, refresh tokens and credentials files out of git, logs and command arguments.

## 1. One OAuth client for all accounts

Do this once, in the [Google Cloud console](https://console.cloud.google.com/), signed in as the account that will own the project. It needs no billing and no paid API.

1. Create a project with no organization, for example `gws cli`.
2. In **APIs & Services > Library**, enable the Gmail, Google Drive, Google Calendar, Google Docs and Google Sheets APIs.
3. In **Google Auth Platform > Branding**, create the app: an app name, a support email, audience **External**, and a contact email. The app starts in testing mode.
4. In **Audience > Test users**, add every account that will sign in. In testing mode, only test users can grant consent, and their refresh tokens expire after 7 days (see [Token lifetime](#token-lifetime)).
5. In **Clients**, create an OAuth client of type **Desktop app**. Copy the client ID and secret now: the console shows the secret only once.

`gws auth setup` automates the project steps with `gcloud`. Without `gcloud`, use the console steps above.

A Google Workspace account signs in only when its admin allows the unverified app. When the admin blocks it, consent stops with "Access blocked" and only the admin can allow it.

## 2. Sign in on a computer with a browser

The consent flow redirects to `http://localhost:<port>` on the computer that runs `gws auth login`, so run it where the browser runs. Use one config directory per account, each with the client from step 1:

```bash
label=work   # one label per account
export GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws/$label
export GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file   # no OS keyring prompt over SSH
mkdir -p -m 700 "$GOOGLE_WORKSPACE_CLI_CONFIG_DIR"
# Save the Desktop client JSON as $GOOGLE_WORKSPACE_CLI_CONFIG_DIR/client_secret.json (mode 600).
gws auth login --scopes https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/calendar,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/spreadsheets
```

Open the printed URL in a browser profile that is signed in to that account, pick the account, and accept the "Google hasn't verified this app" warning and the scopes. Testing mode allows about 25 scopes; the `recommended` preset asks for more and fails, so name the scopes. `gws auth login -s gmail,drive,calendar,docs,sheets` opens an interactive picker for the same services instead; it also preselects Cloud Platform, which these services do not need.

## 3. Carry each login to the headless host

On the computer with the browser, export the login and copy it to the host through stdin, so no plain copy stays on disk:

```bash
GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws/$label GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file \
  gws auth export --unmasked \
  | ssh <host> "umask 077; mkdir -p ~/.config/gws/$label && cat > ~/.config/gws/$label/credentials.json"
```

The export is an `authorized_user` JSON: the client ID and secret plus the refresh token. On the host, save a small wrapper per account as `~/.local/bin/gws-<label>` (mode 700):

```bash
#!/bin/sh
export GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file
export GOOGLE_WORKSPACE_CLI_CONFIG_DIR="$HOME/.config/gws/<label>"
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE="$GOOGLE_WORKSPACE_CLI_CONFIG_DIR/credentials.json"
exec bun "$HOME/code-factory/tools/mail-read-notice/read.ts" "$@"
```

The wrapper runs `gws` unchanged; only Gmail calls that return mail content (`messages` or `threads` `get`/`list`, and `messages attachments get`) are buffered, other calls stream straight through. After such a call succeeds, it texts the owner one line through `fm-imessage` (without waiting for the bridge): the agent (`MAIL_READ_AGENT`), the mail sender ("unknown sender" when the output has no headers, such as `format=raw` or attachments), and the purpose (`MAIL_READ_PURPOSE`, "not given" when unset). The text never holds the subject, body, a link or any sender word with a digit. Do not put a code in the agent or purpose. A failed text does not fail the read. `MAIL_READ_SEND` replaces the send command.

Check each account with read-only calls:

```bash
gws-<label> gmail users getProfile --params '{"userId": "me"}'   # prints that account's address
gws-<label> drive files list --params '{"pageSize": 1}'
```

## Token lifetime

Google expires refresh tokens of an External app in testing mode 7 days after consent. When a wrapper starts to fail with `invalid_grant`, repeat steps 2 and 3 for that account. To stop the weekly renewal, publish the app (**Audience > Publish app**); Google may then require verification for the Gmail and Drive scopes.

To revoke a login, remove the account's config directory on both computers and remove the app at <https://myaccount.google.com/connections> for that account.
