# Cloudflare container runner

Runs GitHub Actions jobs in [Cloudflare Containers](https://developers.cloudflare.com/containers/): one fresh container for each job, started 2-3 seconds after the job queues.
It is opt-in and off by default. [runner-up](runner-up.md) keeps serving everything else.

## Turn it on

Add a `cloudflare_runner` block to `.local/host.yml`.
`credentials_file` and `repos` are required.

```yaml
crewship:
  cloudflare_runner:
    credentials_file: /home/you/super.env   # CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID
    repos:
      - { repo: owner/name, label: cf-name }   # workflows use `runs-on: cf-name`
  #   max_instances: 4                       # most containers at one time
  #   poll_seconds: 60
```

`inspect` refuses a label that every runner has (`self-hosted`, `linux`, ...) or that looks GitHub-hosted, and a repository named twice.
`./ship.sh launch` installs the dispatcher and the Worker sources, makes the token between them, deploys the Worker, and starts `cf-runner-dispatch.service`.
A second apply changes nothing.
Deploying needs `node` and Docker on the host; the first image build is slow on a busy host.

## How it works

1. `cf-runner-dispatch.service` polls each repository for queued jobs whose `runs-on` has its label.
2. For each one it asks GitHub for a just-in-time runner named `cf-<job id>` (the host's `gh` login; the token never leaves the host) and posts only that runner config to the Worker.
3. The Worker starts one container. Its entrypoint runs the runner once; GitHub removes the runner after the job, and the container stops.

If the container does not start, the dispatcher deletes the runner it registered. A job still queued after 15 minutes gets a new runner, up to three tries.
At most `max_instances` jobs run at one time; the Worker's own limit is the same number.

## Deploying and changing it

`cf-runner.py deploy` runs a deploy only when the Worker source or its settings changed, and refuses while a dispatched job is in flight, because a deploy replaces running containers.
Credentials come from `credentials_file` and reach wrangler through its environment only.

- The Worker is always `crewship-cf-runner` on `standard-4` (4 vCPU, 12 GiB, 20 GB disk).
- The deploy runs `wrangler deploy`, then `wrangler secret put DISPATCH_TOKEN`. Until the secret exists, the Worker answers every request with 503.
- A refused deploy (a job in flight) makes the apply fail. Apply again when the jobs end.
- The dispatcher reads its config only when it starts, and an apply never restarts it. After you change `repos` or `poll_seconds`, run `systemctl --user restart cf-runner-dispatch.service`.

## Limits

- The dispatcher reads a run's jobs once. A run with no job for a configured label on that first read is ignored for good, so a labelled job that appears later (a `needs:` stage) waits for a runner that never comes. Put every labelled job in a run that has a labelled job in its first stage, or keep such workflows on runner-up.

- A container has at most 20 GB of disk. A Rust job whose target directory is larger fails with "No space left on device". Keep it on runner-up until Cloudflare raises the limit for the account.
- The disk is ephemeral, so compile caches start cold.
- Cost is what the containers use: about $0.40 an hour for `standard-4`, billed while the container runs.

## Roll back

Change `runs-on` back to the runner-up label. Removing the block does not stop anything: an apply skips the feature, so the dispatcher keeps running. Stop it with `systemctl --user disable --now cf-runner-dispatch.service`. The Worker stays deployed until you delete it with `wrangler delete`.
