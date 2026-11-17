# EOS / CloudVision clock investigation

Read-only evidence collection for recurring **Device Clock Out of Sync** events.
Current scope: **TOR-F2-Leaf2** (affected), **TOR-F2-Leaf1** (healthy comparison),
and on-premises **CloudVision 2026.3.0.1** running as a VM. No devices have been
contacted and no root cause has been established.

Private repository: https://github.com/skadri342/EOS-MCP-Test

This workspace supplies an Ansible-style inventory, the official Arista EOS MCP
server, a fixed-command Python collector, and a CVP SSH access guide. Ansible is
not required or installed. The collector supports the flat groups in the example;
it does not implement general Ansible inventory plugins or Jinja/Vault expansion.
EOS MCP provides interactive EOS tools; CVP is accessed separately over restricted
SSH. Neither integration automatically reads CloudVision UI events.

## Start the dev container

Install Docker Desktop or OrbStack and start its Docker engine. Connect the host
to the management VPN if required. In VS Code, install **Dev Containers**, open
this directory, and choose **Dev Containers: Reopen in Container**. First build
needs internet access. Open a terminal in the container.

Alternatively, from the project directory on the host:

```sh
docker build -f .devcontainer/Dockerfile -t eos-clock-diag:local .
docker run -d --name eos-clock-diag --cap-drop=ALL \
  --security-opt=no-new-privileges \
  --mount "type=bind,source=$PWD,target=/workspaces/EOS-MCP-Test" \
  eos-clock-diag:local
docker exec -it eos-clock-diag bash
```

If that container already exists, use `docker start eos-clock-diag` followed by
`docker exec -it eos-clock-diag bash`. Stop it with `docker stop eos-clock-diag`.
The image uses Node 24, EOS MCP **0.13.1-beta**, and PyYAML **6.0.3**. Base image
and OS packages can update on rebuild. It runs as user `node`, drops Linux
capabilities, publishes no ports, and mounts no Docker socket. The project bind
mount remains writable and outbound networking is available; container isolation
does not enforce device permissions or a network destination firewall. Verify
management VPN routes and DNS work inside the container, not only on the host.

## Set up inventory and local credentials

Run inside the container:

```sh
umask 077
mkdir -p .secrets reports
chmod 700 .secrets reports
cp inventory/example.yml inventory/local.yml
cp config/eos-mcp.example.yml config/eos-mcp.local.yml
```

Edit `inventory/local.yml`: replace the example IPs, confirm usernames and eAPI
ports, and add each CVP node separately if clustered. `time_servers` is reference
data only. Keep ping and packet capture disabled initially. Do not add real
passwords to YAML. For different switch passwords, set a different
`mcp_password_env: EOS_MCP_LEAF2_PASSWORD` on each host and export each variable.

Ask the switch administrator to provide an existing, dedicated eAPI account
with command authorization for the baseline show commands in `scripts/collect.py`.
The administrator must confirm existing HTTPS eAPI access from this container's
network. Enabling eAPI or changing AAA is an administrator change outside this
collector. Do not use an administrator account to bypass a denied command.

Enter a switch password without putting it in shell history (Bash):

```bash
read -rsp 'EOS read-only password: ' EOS_MCP_PASSWORD; echo
export EOS_MCP_PASSWORD
```

Place the trusted network CA bundle in `.secrets/network-ca.pem`, if the default
trust store does not trust the switch certificates. Certificates must match the
DNS name/IP in inventory. Use:

```sh
export EOS_CA_FILE=/workspaces/EOS-MCP-Test/.secrets/network-ca.pem
```

Also uncomment `caFile` in `config/eos-mcp.local.yml` for MCP (it does not use
`EOS_CA_FILE`). If public/system trust works, neither CA override is needed.
The collector always verifies TLS. Do not disable verification to hide a CA or
hostname error.

For CVP, follow [the account guide](docs/cloudvision-access.md) before adding a
CVP target. Use a dedicated SSH key in `.secrets` and a fingerprint-verified
`.secrets/known_hosts`. Do not paste passwords or private keys into chat.
Ignored files are also excluded from the Docker build context. Keep operational
output local; a private GitHub repository is still not a credential store.

## Validate, then collect

The following performs no device connections:

```sh
python -m unittest discover -s tests -v
python scripts/verify_mcp.py
eos-mcp-server validate-inventory --inventory inventory/example.yml --inventory-only --json
python scripts/collect.py --inventory inventory/local.yml \
  --target TOR-F2-Leaf2 --target TOR-F2-Leaf1 --target cvp1
```

Review the printed plan. Once credentials and trust are set up, collect a
single baseline (leave off `--target cvp1` until its restricted account is ready):

```sh
python scripts/collect.py --inventory inventory/local.yml \
  --target TOR-F2-Leaf2 --target TOR-F2-Leaf1 --target cvp1 --execute
```

For an intermittent problem, sample every five minutes for about 24 hours:

```sh
python scripts/collect.py --inventory inventory/local.yml \
  --target TOR-F2-Leaf2 --target TOR-F2-Leaf1 --target cvp1 \
  --execute --samples 289 --interval 300
```

Keep that terminal/container running, or run inside `tmux` installed separately.
For a shorter, closer look, use `--samples 121 --interval 60` (about two hours).
These are requested start intervals: slow commands can lengthen them. Sampling
can miss brief incidents; correlate with retained CVP events and switch logs.
Devices and commands are queried sequentially. Per-command UTC start/end times
and durations are recorded so comparisons do not assume simultaneous reads.

Evidence is saved under `reports/<UTC timestamp>/`. Exit status 2 means at least
one command failed or was unsupported; inspect the individual records. A CVP
node running chrony will often lack `ntpq`; a denied command or missing binary
is a collection gap, not proof that NTP is broken. Generic exception types are
recorded without credential-bearing request details. Do not share raw reports
without review. Ctrl-C preserves completed host samples.

## Use an AI agent with EOS MCP

The EOS MCP server is installed in this container. For a Codex instance running
inside the same container, merge `config/codex.example.toml` into the trusted
project's `.codex/config.toml`, export the required password variables in the
environment that launches that client, and reconnect/restart its MCP session.
Add every per-host secret variable name to `env_vars` if using separate passwords.
The template does not install Codex or configure an already-running desktop app.
Use your approved Codex CLI/IDE installation and authentication workflow.

A host-based MCP client must launch the server in the container, for example
with command `docker` and arguments:

```json
["exec", "-i", "-e", "EOS_MCP_PASSWORD", "eos-clock-diag",
 "eos-mcp-server", "serve", "--config",
 "/workspaces/EOS-MCP-Test/config/eos-mcp.local.yml"]
```

For Codex, also set `env_vars = ["EOS_MCP_PASSWORD"]` in that MCP entry. Add
additional `-e VARIABLE_NAME` arguments and forwarded names for per-host secrets.
The Docker executable must be on the host client's PATH and its process must
inherit the exported variables. No `-t` flag: MCP stdio requires a clean stream.
This host launch needs Docker access granted by the client's execution policy.

After the server is attached, ask the agent:

> Read AGENTS.md and docs/troubleshooting.md. Investigate recurring Device Clock
> Out of Sync on TOR-F2-Leaf2 versus TOR-F2-Leaf1. Use only those EOS inventory
> targets and the explicitly named CVP targets. Start with inventory permissions,
> clock/NTP status and associations. Use the fixed SSH collector for CVP. Compare
> with the event UTC timeline I supply. Report evidence, missing data and ranked
> hypotheses. Do not change configuration, restart services or step clocks.

The current chat does not yet expose EOS MCP tools; adding a config file alone
does not attach a server to an existing session. An agent with shell access can
also run the collector and interpret its JSON without MCP. Live investigation
still requires network reachability and authorized accounts. Autonomous evidence
collection is feasible; findings need evidence and remediation remains a separate
change. The upstream MCP project is beta and best-effort, not Arista TAC supported.

## Troubleshooting and sources

Read [the investigation runbook](docs/troubleshooting.md) and
[CVP account setup](docs/cloudvision-access.md).

- [Arista EOS MCP server](https://github.com/aristanetworks/eos-mcp-server): inventory, permissions, TLS and CLI.
- [Codex MCP configuration](https://developers.openai.com/codex/mcp): client configuration and environment forwarding.
- [Arista CloudVision manual](https://www.arista.com/en/cg-cv): consult documentation matching **2026.3.0.1** and your TAC support channel for appliance account procedures.

The upstream MCP README and registry version were checked during setup. Arista's
public CloudVision pages returned a browser challenge in this environment, so
the release-specific SSH account procedure and event threshold remain unverified.
