# CloudVision 2026.3.0.1 access

There are two different access planes: a **CloudVision application viewer** and a
**Linux account on the CVP VM**. A UI role does not create a Unix user or make a
shell read-only. A normal non-root shell can still write files and run processes.
Do not provide the agent with the appliance's root, cvpadmin, or unrestricted
support credentials.

## Create application access if you want a human to view/export events

With a CVP administrator, open the release's user/role management page (the exact
menu wording should be confirmed in your installation). Create a dedicated local
application user, or an identity-provider group mapping if authentication is
centralized. Assign the built-in viewer/read-only role **only if its effective
permissions** allow device inventory, device telemetry and events and deny
configuration changes, change execution and user/role administration. If the
built-in role does not fit, have the administrator create a role with that scope.

Log in as that account and check that it can view both leaves and the clock event
details, but cannot edit configuration or execute a change. Export the last 24
hours of events for TOR-F2-Leaf2, plus a healthy leaf comparison, to `reports/`.
Include open/clear timestamps, detail/threshold text, device identifiers, and
timezone. This project does not use application credentials or automate the UI.

## Provision restricted SSH access through your CVP administrator

**Version-dependent prerequisite:** have the administrator confirm the supported
way to provision a dedicated Linux account on the **2026.3.0.1 appliance** using
the release's deployment/security guide or TAC. Public documentation could not
be verified here. Do not paste generic `useradd`, sudoers or sshd modifications
onto a managed CVP appliance based on this guide. If a custom account/dispatcher
is unsupported, use administrator-run collection or an approved support bundle
instead; EOS-only collection can proceed independently.

1. In the dev container, generate a key used only for this investigation:

   ```sh
   umask 077
   mkdir -p .secrets
   chmod 700 .secrets
   ssh-keygen -t ed25519 -f .secrets/cvp_ed25519 -C cvp-clock-investigation
   ```

   Prefer a passphrase for interactive/manual use. The unattended collector uses
   `BatchMode=yes` and disables SSH-agent access; it therefore requires a locally
   readable key without a passphrase. If unattended use is needed, use a temporary,
   narrowly restricted key with a short lifetime and remove it after diagnosis.
   Keep its private file mode 600. Share only the `.pub` content with your admin.

2. Ask the administrator to provision a dedicated account such as `clockdiag`
   through the confirmed supported mechanism, with no administrator/sudo rights,
   no password-based SSH login, and no unnecessary privileged group memberships.
   It needs only the permissions required to execute the approved read commands.
   Do not grant broad journal, container-runtime or service-management access.

3. If custom dispatchers are supported, have the administrator review
   `scripts/cvp_forced_command.py`. Verify Python 3 and the command paths on that
   appliance. `chronyc` and `ntpq` are alternatives; unavailable commands may fail.
   The administrator installs it at an administrator-owned location such as
   `/usr/local/libexec/cvp-clockdiag.py`, with no write access for `clockdiag`.
   No packages should be installed on CVP for this collector.

4. Have the administrator restrict the dedicated public key to the dispatcher.
   An OpenSSH authorized-key entry has this form (replace the public key):

   ```text
   restrict,command="/usr/bin/python3 -I /usr/local/libexec/cvp-clockdiag.py" ssh-ed25519 AAAA... cvp-clock-investigation
   ```

   The administrator must verify that the appliance supports `restrict` and
   forced commands and that key storage, parent directories, dispatcher and
   Python import locations cannot be replaced by this account. Disable all
   alternate unrestricted authentication paths for the account. Consider a
   `from="<approved client source IP/CIDR>"` key restriction using the source
   address the CVP VM actually sees (VPN/NAT can change it). Do not set its shell
   to `nologin` without testing: sshd commonly needs a valid shell to execute a
   forced command. These controls constrain this SSH entry path; they do not
   turn Linux into a read-only filesystem or restrict other accounts.

5. Obtain the SSH host key/fingerprint from your administrator over a trusted
   channel. The admin can read existing host public keys locally; no new host key
   is needed. Store the verified host-key line in `.secrets/known_hosts`.
   `ssh-keyscan` alone does not authenticate a server; if used to obtain candidate
   keys, compare SHA256 fingerprints independently before accepting them. Use
   `[hostname]:port` syntax for non-default ports. Never turn host checking off.

6. Put the management address, account name, key path, known-hosts path and
   optional `ansible_port` into `inventory/local.yml`. Run a CVP-only dry run:

   ```sh
   python scripts/collect.py --inventory inventory/local.yml --target cvp1
   ```

   Then run the same command with `--execute`. It requests only these IDs:
   `clockdiag:clock`, `clockdiag:uptime`, `clockdiag:timedatectl`,
   `clockdiag:tracking`, `clockdiag:sources`, `clockdiag:sourcestats`,
   `clockdiag:ntpq`, and `clockdiag:os`.

7. Have the administrator verify a known benign, unlisted request such as `id`
   is rejected when authenticated with that key. Verify interactive shell,
   forwarding and SFTP/SCP are denied. A typo in the restriction must not leave
   an unrestricted account. Revoke the investigation key/account when finished.

Only the CVP administrator provisions this account or modifies appliance files.
The collector never installs the dispatcher, modifies accounts, invokes sudo or
changes time. Keep the initial collection unprivileged even if some commands fail.

## If a restricted SSH account is not supported

Have an existing authorized administrator run these read-only checks on the VM
and save sanitized output under `reports/`. Do this on every node if clustered:

```sh
date -u '+%Y-%m-%dT%H:%M:%S.%NZ'
uptime
timedatectl status
chronyc -n tracking
chronyc -n sources -v
chronyc -n sourcestats -v
# If this release uses ntpd rather than chrony:
ntpq -pn
```

Use installed commands only; missing utilities are not a reason to install new
software on the appliance. An administrator can separately obtain relevant
time-service, VM suspend/resume and CVP telemetry logs using supported tools.
