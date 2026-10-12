# Chat clients

The `chat` profile installs two terminal chat clients. It is on by default and off in the container image. Each client runs in its own Herdr tab.

For a shared message board on GitHub, see the optional [GitHub board](github-board.md).

| Client | Command | Source |
| --- | --- | --- |
| [Concord](https://github.com/chojs23/concord) (Discord) | `concord` | The latest release, `concord-<arch>-unknown-linux-gnu.tar.xz` |
| [slk](https://github.com/gammons/slk) (Slack) | `slk` | The latest release, `slk_<version>_linux_<arch>.tar.gz` |

Every apply installs the latest release of each client. It verifies each download against the SHA-256 that GitHub publishes for the release asset, and links the command into `~/.local/bin`. Apply also installs the shared libraries that the Concord binary needs: `libegl1`, `libpipewire-0.3-0t64`, `libva2` and `libva-drm2`. Every host already gets `libasound2t64` with the headless browser libraries. Apply does not install `xdg-desktop-portal`, because Concord uses it only for screen capture.

Apply does not replace a command that you installed by hand. A hand-installed `~/.local/bin/slk` stops apply with `unmanaged command exists`. Remove it, then run apply again. A hand-installed Concord in `~/.cargo/bin` does not stop apply, but it stays on disk: remove it, so that only the managed `~/.local/bin/concord` is left.

## Configuration

Apply writes each config file one time, when the file does not exist:

| File | Source | Setting |
| --- | --- | --- |
| `~/.config/concord/config.toml` | [`blueprint/config/concord.toml`](../blueprint/config/concord.toml) | `[display] image_protocol = "kitty"` |
| `~/.config/slk/config.toml` | [`blueprint/config/slk.toml`](../blueprint/config/slk.toml) | `[appearance] image_protocol = "kitty"` |

After that, the client owns the file, and apply does not change it. slk adds a `[workspaces.<name>]` block for each workspace that you sign in to. These blocks belong to the operator and stay out of this repository. To get the recipe settings again, remove the file and run apply.

The `kitty` setting sends images as kitty graphics. WezTerm, kitty and Ghostty show them. For images over mosh, see [Over mosh](herdr.md#over-mosh).

## Start the clients

Open a Herdr tab for each client, and start `concord` or `slk` in it. The Herdr server keeps the tabs and the clients when you detach.

## Sign in

The logins are not part of the recipe. Do not put a chat token in this repository, in `.local/host.yml`, or in a unit file. A new host needs a new sign-in; do not copy a login from an old host.

- **Concord** keeps its own login. Sign in on its login screen. Concord saves the login in the system keychain when one is available, and otherwise in `~/.local/state/concord/`.
- **slk** reads the login from the Slack desktop app on the same machine: run `slk --add-workspace` and select the workspaces. A server does not have the Slack desktop app. On a server, the saved login in `~/.local/share/slk/tokens/` comes from the operator's own signed-in Slack session in a browser. That procedure stays with the operator and is not in this repository.
