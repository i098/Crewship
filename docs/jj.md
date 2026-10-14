# Jujutsu

The opt-in `jj` profile installs [Jujutsu](https://github.com/jj-vcs/jj) for agents. The installer takes the latest release, verifies its digest, and puts the binary at `~/.local/bin/jj`.

## Enable

Set this in `.local/host.yml`, then run `./ship.sh`:

```yaml
crewship:
  profiles:
    jj: true
```

## Colocate with git

Run this in each agent repository:

```sh
jj git init --colocate
jj config set --repo user.name "$(git config user.name)"
jj config set --repo user.email "$(git config user.email)"
jj metaedit --update-author
```

Never run `jj undo` or `jj op restore`. All workspaces share one operation log, so these commands change the work of other agents.
