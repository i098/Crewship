---
name: kvz-fleet
description: "Use when joining Mac minis or other Macs to a kvz fleet (a kvz Kubernetes cluster), or when setting up Macs as CI runners with kvz."
---

# kvz fleet: join Macs

kvz is Kubernetes that runs natively on macOS (Apple Silicon, macOS 26 or later).
This skill wraps the upstream kvz agent guide. It does not replace it.
Read the upstream docs for every detail.

## Rules
- Use 1 server, or 3 servers for high availability. NEVER use exactly 2 servers.
- NEVER print, log, echo, or commit a join token or kubeconfig content.
- NEVER paste a join token or kubeconfig into a chat, issue, PR, or status line.
- Check each step before you start the next step.
- Work over SSH, as the macOS user that runs kvz. That user must be an administrator.
- Use exactly 1 server, or 3 or more servers for high availability. NEVER use exactly 2 servers.

## Steps

1. Plan. Pick one Mac as the first server. Make the rest agents.
2. Check every Mac. `uname -m` is `arm64`. `sw_vers -productVersion` is 26 or later. At least 20 GB is free. Host names are unique.
3. Keep every Mac awake and logged in. Run `sudo pmset -a sleep 0 disksleep 0 displaysleep 0 autorestart 1`. kvz needs the GUI login session.
4. Open the network ports. Servers need TCP 6443 and 6444. Every Mac needs TCP 10250 and 6446. HA servers also need TCP 2380.
5. Install on every Mac with `brew install kvz-platform/tap/kvz`. Run `kvz version`. The version must match on every Mac.
6. Install the first server with `kvz install server`, or `kvz install server --cluster-init` for HA. Wait until `kvz kubectl get nodes` shows Ready.
7. Read the join token from `~/.kvz/join-token` into a shell variable. Do not print it.
8. Add more servers, one at a time, only for HA. Wait for Ready before the next one.
9. Join each Mac as an agent with `kvz install agent --server <SERVER_URL> --token <TOKEN>`.
10. Verify on a server with `kvz kubectl get nodes -o wide`. Every Mac must show Ready.
11. If a step fails, read `~/.kvz/logs/kvz-server.log` or `kvz-agent.log`. Do not paste the log without removing tokens first.

## Upstream docs

Read the raw Markdown. It is always the current version.

- [Fleet setup](https://raw.githubusercontent.com/kvz-platform/kvz/main/docs/fleet.md): full guide for several Macs, with network, HA, and troubleshooting.
- [Getting started](https://raw.githubusercontent.com/kvz-platform/kvz/main/docs/getting-started.md): one Mac, first pods, running as a service.
- [Operations](https://raw.githubusercontent.com/kvz-platform/kvz/main/docs/operations.md): every command and flag, file paths, backups, uninstall.
- [Runtimes](https://raw.githubusercontent.com/kvz-platform/kvz/main/docs/runtimes.md): Linux, macOS VM, and native macOS pods.
- [Kubernetes features](https://raw.githubusercontent.com/kvz-platform/kvz/main/docs/kubernetes-features.md): supported features and known limits.
- [Full documentation in one file](https://kvz.systems/llms-full.txt): every document above, in one file.

## Reporting a problem

Report bugs at the upstream issue tracker. Include `kvz version`, `sw_vers -productVersion`, the Mac count and roles, and the relevant log lines. Remove join tokens and kubeconfig content first.
Report a security issue privately, never in a public issue.
