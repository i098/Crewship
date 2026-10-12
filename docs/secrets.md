# Shared credentials: super.env in Cloudflare Secrets Store

`~/super.env` on the primary VPS holds every shared fleet credential. That VPS stays the one place the file is edited. Cloudflare Secrets Store keeps a copy, and a new agent host fetches it through a private Worker. The fetched file carries its own usage notes as comments.

Never paste a value from this file into a repository, issue, PR, log, or chat. Compare copies by `sha256sum` only.

## What lives where

| Piece | Where | Notes |
| --- | --- | --- |
| Source of truth | `~/super.env` on the primary VPS, mode `600` | Edit here, then push. |
| The whole file | Account Secrets Store (`default_secrets_store`), secrets `super_env_<hash>_0`, `super_env_<hash>_1`, …, comment `super.env`, scope `workers` | The file's base64, cut into chunks of at most 65,536 characters. `<hash>` is the first 12 hex digits of the file's sha256. The comments hold retired credentials, so they stay a secret too. |
| Client id for the Worker's own check | Secret `FLEET_SECRETS_ACCESS_CLIENT_ID`, comment `super.env`, scope `workers` | A copy of that variable's last assignment, without one surrounding pair of matching quotes. |
| Fetch endpoint | Worker `fleet-secrets` on the custom domain `host` names in `scripts/stow-secrets.sh` | No `workers.dev` or preview URL. Answers with `Cache-Control: no-store`. |
| Gate | Cloudflare Access app `fleet-secrets`, one policy: Service Auth for service token `fleet-secrets-fetch` | The Worker also verifies the Access JWT: issuer, audience, expiry, signature, and the token's client id. Anything else gets `403`. |
| Fetch credential | `FLEET_SECRETS_ACCESS_CLIENT_ID`, `FLEET_SECRETS_ACCESS_CLIENT_SECRET` at the end of `~/super.env` | Expires one year after creation. |

`apps/fleet-secrets/split.jq` defines the split. The Worker joins its bindings `super_env_0`, `super_env_1`, … in order and decodes them, which gives the file byte for byte.

Limits: a secret holds at most 65,536 bytes, and an account holds at most 100 secrets during the Secrets Store beta. One chunk holds 49,152 bytes of the file, so the secret count grows by one per 48 KiB of file, not per variable. A push needs room for the old and the new chunks together, and makes that room itself when the store is full (see below).

## Push after editing super.env

On the VPS, from this repository:

```bash
scripts/stow-secrets.sh
```

It reads `CLOUDFLARE_ACCOUNT_ID` and the account token `CF_API_TOKEN_GLOBAL` from the file itself. It creates the chunks for the current file and updates `FLEET_SECRETS_ACCESS_CLIENT_ID`, then redeploys the Worker bound to them, then turns `workers.dev` and preview URLs off. It refuses to overwrite a same-named secret whose comment is not `super.env`. Running it twice leaves the same state.

A changed file gets new chunk names, so a push never changes a chunk that a running Worker reads. After the redeploy, the script waits 30 seconds for every edge to run the new Worker, then deletes every secret with comment `super.env` that the new Worker does not bind: older chunks and the secrets of the earlier one-secret-per-variable layout. It never deletes a secret with another comment.

If the store has no room for the new chunks (secret count plus chunks to create above 100), the script deletes just enough of those replaced `super.env` secrets before it creates the chunks, then continues as above. The running Worker then loses some bindings until the redeploy finishes, so `fetch-secrets.sh` can fail for a few seconds. This happens whenever the store lacks room, normally only once, on the move from the one-secret-per-variable layout. The fetch works again after the redeploy.

## Fetch on a new host

1. On the VPS, copy the two lines `FLEET_SECRETS_ACCESS_CLIENT_ID=…` and `FLEET_SECRETS_ACCESS_CLIENT_SECRET=…` from `~/super.env`. Copy them by hand, over SSH or a password manager; never through chat, a ticket, or a repository.
2. On the new host, write them to `~/.config/fleet-secrets.env` and restrict it:

   ```bash
   mkdir -p ~/.config && chmod 700 ~/.config
   install -m 600 /dev/null ~/.config/fleet-secrets.env
   "${EDITOR:-nano}" ~/.config/fleet-secrets.env
   ```

3. From a checkout of this repository, run:

   ```bash
   scripts/fetch-secrets.sh
   ```

   It writes `~/super.env` at mode `600` through a temp file and an atomic rename, then prints its sha256. It must equal `sha256sum ~/super.env` on the VPS.

The script reads the two values only from `~/.config/fleet-secrets.env`. It refuses that file unless it is mode `600`, and it never takes the values as arguments or environment variables. On any HTTP status other than `200`, the existing `~/super.env` stays unchanged. `FLEET_SECRETS_URL` overrides the URL.

A fetched copy is read-only in practice: edits made on it are overwritten by the next fetch. Make edits on the VPS and push.

## Revoke if a host is lost

1. Cloudflare dashboard → Zero Trust → Access → Service credentials → Service Tokens → `fleet-secrets-fetch` → Delete. Fetching stops immediately for every host.
2. Create a new service token, and replace the `token_id` in the `fleet-secrets` app's only policy.
3. Replace the two `FLEET_SECRETS_ACCESS_*` lines in `~/super.env` on the VPS with the new token's client id and secret, then run `scripts/stow-secrets.sh`. The Worker only accepts the client id stored in `FLEET_SECRETS_ACCESS_CLIENT_ID`.
4. Copy the new lines to the remaining hosts.

Revoking the fetch token does not revoke what the lost host already fetched. It holds every credential in the file, so treat each one as exposed, and tell the owner.

Renew the token the same way before it expires; the Access dashboard shows the expiry date.

## One-time setup, for rebuilding

Create these once per Cloudflare account, and again only if they are lost:

1. Access app `fleet-secrets`: self-hosted, on the Worker's custom domain, session 15 minutes, hidden from the App Launcher, no identity providers. Its only policy: decision Service Auth, include only service token `fleet-secrets-fetch`.
2. Run `scripts/stow-secrets.sh`. It reads the team domain and the app's Application Audience tag from the Access API on every push and binds them to the Worker.
3. Add the Worker custom domain only after the Access app exists.
