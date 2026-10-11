# Security and export boundary

This repository is an allowlisted reconstruction recipe, not a copy of a home directory. Keeping the repository private does not make credentials safe to commit.

## Never export

- SSH private keys, GitHub tokens, Tailscale node identity or auth keys.
- OMP, Claude, Codex, or other provider authentication stores.
- Browser profiles, cookies, password stores, desktop login sessions, or VNC passwords.
- Agent transcripts, fleet task history, private project working trees, database files, or Docker volumes.
- `.env` files, Terraform state, runtime sockets, PID files, and caches.

A service unit can carry an inline API credential. Never copy such a unit verbatim. Recreated services must load credentials from a private runtime environment file, never from tracked unit contents.

## On a new host

Authenticate each CLI interactively under the account that will run it. Do not copy an old host's credential database to make a tool appear configured. GitHub repository access, model subscriptions, organization permissions, and tailnet membership are separate prerequisites; installing a binary does not grant them.

Two exceptions move state between the operator's own hosts:

- Shared fleet credentials in `super.env`: a new host fetches them from Cloudflare Secrets Store with `scripts/fetch-secrets.sh`. See [Shared credentials](secrets.md).
- Each Firstmate home's `data/` and `config/`: they move host to host over SSH (`rsync -a`, owner-only), never through Git, a registry, or an image, and only for the cutover and rollback syncs of [Moving the agents to a new host](agent-host-move.md).

Keep local credential files outside the checkout, in owner-only directories with mode `0700`; files should have mode `0600`. Services should use `EnvironmentFile=` or Docker secrets. Do not put tokens into shell command arguments or public URLs.

The persistent desktop browser uses exactly one profile, `~/.vnc-chrome-profile`. Never clone, trim, archive into Git, or replace it. Log in on the destination device. The browser pruner excludes persistent profiles, attached browsers, and headed browsers.

## Remote access

Keep application and desktop listeners on loopback unless a reviewed deployment explicitly needs another binding. Reach them through SSH port forwarding or a configured private network. Do not publish a Docker socket or mount the host socket into an agent container; it grants host-level control.

Loopback is shared by local accounts. The optional desktop therefore requires an operator-created private VNC credential in addition to SSH transport. It never offers unauthenticated RFB access. Its service will not kill another desktop to claim an occupied display.

Tailscale installation, authentication, and SSH authorization are separate steps. Join the tailnet interactively, then use `tailscale set --ssh=true` only if Tailscale SSH is wanted. The tailnet must also authorize the connection in its SSH policy. Do not use `tailscale up --reset` to change one setting on an existing machine.

This export does not rewrite the current host's firewall, SSH policy, account membership, or credentials. Review those changes separately before applying a new-host profile.

### SSH to a Mac

Agents can reach an operator Mac with `ssh mac`. They use it to open links in the operator's browser and to control Mac apps. Crewship configures the host side. You configure the Mac side by hand, one time. Keep the Mac's name, address, and login out of this repository.

#### Host side: what apply does

Set the Mac's address and login in `.local/host.yml` only, never in `config/default.yml`:

```yaml
crewship:
  mac_ssh:
    host: <Mac tailnet name or IP>
    user: <Mac login>
```

When `mac_ssh` is not set, apply skips this step. When it is set, apply does three things as the Crewship account:

- It generates `~/.ssh/id_ed25519_mac` with `ssh-keygen` (from `openssh-client`) if the file does not exist. It never replaces an existing key. Do not copy this key to another host; each host gets its own.
- It writes a `Host mac` entry between `crewship Host mac` markers at the top of `~/.ssh/config`, with `IdentitiesOnly yes` and `ConnectTimeout 5`. It does not change other entries.
- It writes a line for the Mac's `~/.ssh/authorized_keys` to `~/.ssh/id_ed25519_mac.authorized_keys` and prints it. The line is restricted with `from="<this host's tailnet IP>"`, so the key works only from this host. If the host is not on the tailnet yet, the line has a placeholder. Join the tailnet and run apply again to get the address.

Apply does not change the Mac.

#### Mac side: one-time setup

1. Install Tailscale on the Mac and on the host, and sign in to the same tailnet on both. Use the Mac's tailnet name or tailnet IP as `mac_ssh.host`.
2. On the Mac, open System Settings > General > Sharing, and turn on Remote Login.
3. Append the line from the host to the Mac's `~/.ssh/authorized_keys`. Copy the output of `cat ~/.ssh/id_ed25519_mac.authorized_keys` on the host. On the Mac, run:

   ```bash
   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   printf '%s\n' '<the line from the host>' >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```

The line holds only a public key. Do not put the private key `~/.ssh/id_ed25519_mac` on the Mac.

##### Optional: browser remote debugging without a prompt

With remote debugging turned on in `chrome://inspect`, a Chromium browser shows an "Allow remote debugging?" prompt for each new CDP connection. Only a person can click it. A browser started with `--remote-debugging-port` serves CDP on 127.0.0.1 with no prompt. Dia, a non-Google Chromium browser, allows the flag on its main profile.

[`dia-debug/dia-debug`](../dia-debug/dia-debug) runs every 15 seconds from a user LaunchAgent. When the browser runs without the flag and started less than 90 seconds ago (from the Dock, a link, login, or a self-update), the script quits it with SIGTERM and opens it again with the flag. SIGTERM is Chromium's graceful quit, so the browser restores the session. The script tries one time per browser process, so it never takes away a window that is in use. `dia-debug --now` relaunches the browser at any age. Another non-Google Chromium browser works after you change `BUNDLE` at the top of the script.

To install, run this on the Mac from a copy of this repository:

```bash
mkdir -p ~/.local/bin ~/Library/LaunchAgents
cp dia-debug/dia-debug ~/.local/bin/
cp dia-debug/local.dia-debug.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.dia-debug.plist
~/.local/bin/dia-debug --now
```

To verify, run `curl -s http://127.0.0.1:9222/json/version` on the Mac. On the host, run `ssh -N -L 19222:127.0.0.1:9222 mac`. Then connect to the `webSocketDebuggerUrl` from `curl -s http://127.0.0.1:19222/json/version`, with port 9222 changed to 19222.

To remove, run this on the Mac, then quit and open the browser again:

```bash
launchctl bootout gui/$(id -u)/local.dia-debug
rm ~/.local/bin/dia-debug ~/Library/LaunchAgents/local.dia-debug.plist
```

Risk: any local process on the Mac can control the signed-in browser without a prompt. The port is bound to 127.0.0.1 only.

#### Optional: app control

Skip this part if agents only open links. To let an SSH session focus apps and type with `osascript` and System Events, give two permissions to `/usr/libexec/sshd-keygen-wrapper`. Every SSH session on the Mac runs under this program.

1. Open System Settings > Privacy & Security > Accessibility. Click `+`, press Command-Shift-G, type `/usr/libexec/sshd-keygen-wrapper`, and add it. Turn it on.
2. Do the same in Privacy & Security > Full Disk Access.

Screen Recording is a separate permission. Without it, `screencapture` over SSH fails. Add the same program in Privacy & Security > Screen Recording only if agents must take screenshots.

#### Verify

On the host, as the Crewship account:

```bash
ssh mac true && echo ok
```

The first connection asks you to accept the Mac's host key. Compare the fingerprint with the output of `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the Mac. To test app control, run `ssh mac "osascript -e 'tell application \"System Events\" to get name of first application process whose frontmost is true'"`. It prints the name of the app in front.

#### Safe use

The person at the Mac uses the same screen and keyboard. Keystrokes go to the app that is in front at that moment.

- Focus an app by its bundle identifier: `ssh mac open -b com.apple.Safari`. Do not rely on `tell application "…" to activate`; it can fail and leave another app in front. To find a bundle identifier, run `osascript -e 'id of app "Safari"'` on the Mac.
- Before each keystroke, read the bundle identifier of the app in front, and stop if it is not the expected app: `ssh mac "osascript -e 'tell application \"System Events\" to get bundle identifier of first application process whose frontmost is true'"`. Typing takes focus away from the person at the Mac, and text can go into the wrong window.
- To open a link, use `ssh mac open '<url>'`. It does not need app control.

#### Host move

A new host gets its own key; never copy `~/.ssh/id_ed25519_mac` from the old host.

1. Run apply on the new host with the same `mac_ssh` values. It generates a new key and writes the new line.
2. Add the new line to the Mac's `~/.ssh/authorized_keys`: at the Mac, as in step 3 of the setup, or from a host that already has access: `ssh mac 'cat >> ~/.ssh/authorized_keys' < new-host.authorized_keys`, where `new-host.authorized_keys` is a copy of the new host's line file. The line is public, so you can copy it with `scp`.
3. Run `ssh mac true` on the new host.
4. At cutover, remove the old host's line from the Mac's `~/.ssh/authorized_keys`. Each line ends with the comment `<user>@<hostname>`, the project name and the word `mac`; the hostname identifies the host. A key made before the Crewship rename carries the earlier project name. Keep the old line until the new host works.

### From a Mac to the host

The other direction, from the operator's Mac to the host, is also a manual setup on the Mac. Apply does not change it. Every host gets `mosh` (`mosh-server`) in the base packages.

Add a `Host` alias for the host to `~/.ssh/config` on the Mac. Set `User` to the host's Crewship account, so `ssh <alias>` and `mosh <alias>` log in as that account without `user@`:

```text
Host <alias>
  HostName <host tailnet name or IP>
  User <Crewship account>
```

mosh reads the alias too, because it starts its session over `ssh`. Then:

```bash
ssh <alias>
mosh <alias> -- herdr-patch
```

[Over mosh](herdr.md#over-mosh) explains `herdr-patch`. Keep the alias, the host's address and the account name out of this repository.

## Host hardening

Every apply on a host that starts services (not the container worker image) installs [Koncreet](https://github.com/jimididit/koncreet) as `/usr/local/bin/koncreet` and renders `/etc/koncreet.conf` once, but nothing runs it. Koncreet is optional: when its release lookup, checksum, or download fails, apply prints a warning, skips it, and finishes the rest; a release installed earlier stays in place. It is a first-hour hardening toolkit: a sudo user with SSH keys, sysctl, swap, a journald cap, time sync, a ufw default-deny firewall, fail2ban on SSH, unattended security updates, and finally SSH with password and root login turned off.

Upstream supports Debian 12/13 and Ubuntu 22.04/24.04 only. `patches/koncreet/ubuntu-26.04.patch` adds Ubuntu 26.04: it opens the OS gate and doctor, and restores the last fallback Koncreet uses to find your SSH client address for the fail2ban whitelist: 26.04 keeps no utmp, so `who -m` prints nothing, and the patch asks logind instead. The same change is the `ubuntu-26.04` branch of the [undeemed/koncreet](https://github.com/undeemed/koncreet/tree/ubuntu-26.04) fork; regenerate the patch from there with `git diff main...ubuntu-26.04`. Apply layers the patch on each new release and prints which case it hit: applied; skipped because the release already supports 26.04; or skipped because it no longer applies, in which case Koncreet installs as released and refuses to run on 26.04 until the patch is refreshed. The patch never fails the apply.

`/etc/koncreet.conf` makes the account that ran `./ship.sh launch` the sudo user, installs the SSH keys it logs in with, and keeps SSH open (Koncreet always allows the ports sshd listens on). With the `tailscale` profile it also opens 41641/udp for Tailscale's direct connections. When apply ran as root, or as the Crewship account (which runs the agents and must not gain sudo), no sudo user is set: `user=` and `pubkey_file=` stay commented out until you fill in the operator's login. Apply never overwrites it; edit it there.

Run it once, by hand, from an SSH session you keep open until the last step works:

1. With the `tailscale` profile: `sudo ufw allow in on tailscale0`, so the tailnet stays reachable once ufw denies incoming traffic. Koncreet keeps existing ufw rules.
2. `sudo koncreet doctor`
3. `sudo koncreet --dry-run apply -c /etc/koncreet.conf`, and read the plan.
4. `sudo koncreet apply -c /etc/koncreet.conf`
5. Open a new SSH session as that user and run `sudo true`. Only when it works: `sudo koncreet ssh apply`. Test one more new session before you close the first. Not `sudo -v`: once the account is in the `sudo` group, `sudo -v` asks for a password even when sudoers grants it NOPASSWD, and a cloud account has none.

If something goes wrong (from upstream's README):

| Problem | Fix |
|---------|-----|
| Can't SSH after harden | `sudo koncreet ssh undo` |
| Locked out by ufw | Console: `sudo ufw disable` |
| Banned by fail2ban | `sudo koncreet fail2ban unban YOUR.IP` |
| Undo baseline drop-ins | `sudo koncreet baseline undo` (keeps users/swap/timezone) |
| Need the new user password | `cat /root/USER.koncreet-password` (as root - save it before `ssh apply`) |
| Forced password change fails | `chage -d $(date -I) USER` then reconnect with your key |
| Too many authentication failures | `ssh -o IdentitiesOnly=yes -i ~/.ssh/your_key user@host` |

Logs: `/var/log/koncreet.log`. Backups: `*.koncreet.bak`. The provider's console, and `tailscale ssh` where Tailscale SSH is enabled, reach the host when sshd does not.

## Updates

See [Dependencies](dependencies.md) for tool release selection, download verification, and exceptions.
Checksums prove a download is the published artifact; they do not establish that a publisher is trustworthy.
Review added tools and installer behavior before adding them.
Ubuntu security updates remain an operating-system responsibility rather than freezing an entire vulnerable package index forever.

Back up project repositories and application data separately, using encrypted storage and an application-aware restore procedure. A successful environment bootstrap is not evidence that a database backup is recoverable.
