# Recurring Device Clock Out of Sync

Scope: TOR-F2-Leaf2 versus TOR-F2-Leaf1, CVP 2026.3.0.1 VM. More than 30 reported
events in 24 hours is a symptom. Similar intended configurations do not establish
identical effective NTP state, source address, path, ACL policy or clock behavior.

## 1. Establish what CloudVision measured

Export the affected device's event details for an explicit 24-hour interval. Use
UTC throughout. Record the event threshold, measured difference if shown, first
and last seen, open/clear transitions, durations and device serial number. Confirm
the 30+ count is distinct incidents rather than notifications for an open event.
Do not assume an undocumented threshold or that the event directly reports an
NTP daemon's offset. Check whether CVP describes device-vs-server time, telemetry
timestamps, or a specific synchronization property in this release.

Look at intervals: regular cadence can suggest poll-related behavior, peer
selection changes or a recurring process; irregular bursts can suggest loss,
CPU pressure, VM scheduling or telemetry backlog. Correlate device onboarding,
software changes, reboot/uptime, interface flaps and maintenance. Account for
timestamp uncertainty if the source clock itself was wrong.

## 2. Collect both leaves while an event is active

Start with the fixed baseline in `scripts/collect.py`:

```text
show clock
show ntp status
show ntp associations
show version
show system resources
show interfaces counters errors
show logging threshold informational 200
```

Some output/syntax varies with EOS version; keep failures visible and use the
documented equivalent for that release. The bounded 200-message log is only a
snapshot; it may not contain the last 24 hours or the incident. Obtain retained
syslog through the site's normal read-only access when needed.

Compare these observations, checking the units printed by each command:

| Evidence | What to look for |
| --- | --- |
| Selected peer | Usually `*` marks the selected synchronization peer. Are both leaves selecting the same healthy source? Other selection markers vary by implementation. |
| Synchronization / stratum | Unsynchronized state, missing selected peer, or stratum 16. A low stratum alone does not prove accurate time. |
| Reach | Usually an octal 8-poll shift register: `377` means responses to the last eight polls. Repeated drops indicate missing replies; `0` on a newly started association needs context. |
| Offset, jitter, delay / dispersion | Sudden jumps, steadily growing error, unstable delay or unsuitable peer quality. Verify ms versus seconds before comparing with CVP. |
| RefID, source, when / poll | Different upstreams, stale last response, peer selection changes or a long poll interval. |
| Uptime, EOS build and resources | A reboot, distinct software/hardware, CPU/memory pressure or agent restarts near the event. |

Compare actual leaf UTC time with its collection start/end bracket, the healthy
leaf and the CVP nodes. The collector's clock is another reference to verify;
Docker commonly shares the host kernel clock, and the host can also be wrong.
Network latency bounds confidence in a simple remote clock comparison.
Timezone display differences are not by themselves clock drift; compare UTC.

## 3. Compare effective time configuration and network path

Have a read-authorized operator retrieve the relevant NTP configuration sections,
management VRF/interface configuration, routes to the selected time servers,
DNS resolution (if names are used), applied ACLs and relevant control-plane
policing counters on both switches. Use version-correct `show` commands. Inspect
effective running configuration, not just the CVP studio/template intent.

The MCP configuration tool retrieves running configuration using privileged
mode, and this account may intentionally deny it. Do not expand account privileges
just to collect a full configuration. Ask the administrator for sanitized NTP,
VRF, source-interface and relevant ACL excerpts instead. Avoid full configs
containing password hashes, SNMP communities or other secrets.

Check particularly:

- The NTP VRF and source interface/IP actually used by **each leaf**. Confirm a
  route and return route for that source in that VRF. Per-device IP differences
  often explain why otherwise identical templates behave differently.
- UDP/123 requests **and replies** through firewalls/ACLs, NAT state, rate limits
  and time-server client ACLs. A healthy ICMP ping would not prove NTP works.
  Validate permitted source ports against the actual client/server behavior.
- NTP authentication/key IDs and server access policy, plus DNS answer changes.
  Compare metadata locally; do not export key material.
- Management-link errors, drops, congestion and control-plane policer drops.
  Counter changes near the event are stronger evidence than lifetime totals.
- Time-server health and peer quality at the same time as the alert, rather than
  only checking whether one server is reachable afterwards.

Ping and packet capture require separate authorization and are disabled in the
example inventory. If approved later, test a few probes using the actual NTP VRF
and source, then consider a short, filtered control-plane capture for the peer's
UDP/123 traffic. Confirm requests/replies and any NTP denial/rate-limit responses.
Do not leave debug/capture running or treat lack of a partial capture as proof
that no packets arrived.

## 4. Check the CVP VM's independent time reference

Use the restricted SSH collector or administrator-run commands in
`cloudvision-access.md` on **each CVP node**, not only a VIP or one cluster member.
Check UTC, selected peer, reach, offset, root dispersion and synchronization state.
For chrony, inspect `tracking`, `sources` and `sourcestats`; a large remaining
correction, stale reference time or non-normal leap status warrants investigation.
Do not run chrony clock-setting commands such as `makestep`.

Ask the virtualization administrator to check hypervisor time, VM pauses,
suspend/resume, snapshots/restores, CPU contention and guest time-sync settings
around event times. Hypervisor guest synchronization and guest NTP can interact;
follow the Arista/hypervisor recommendations for this appliance rather than
disabling either speculatively. One leaf alerting does not rule out a CVP issue,
especially with different telemetry paths, timing or cluster node placement.

## 5. If clocks remain correct, investigate the measurement path

Correlate event timestamps with telemetry freshness, streaming reconnects,
buffering, delays, device-agent health and CVP ingest/processing health. Use
supported CVP diagnostics, retained logs and existing read access; do not restart
TerminAttr or CVP services as a troubleshooting shortcut. Check the exact EOS,
TerminAttr and CVP build combination against release notes or TAC-known issues.
Persistent healthy NTP snapshots alone do not prove a telemetry defect.

## Evidence patterns and next steps

| Pattern during the event | Leading investigation |
| --- | --- |
| Only Leaf2 loses reach or peer selection, Leaf1/CVP remain stable | Leaf2 NTP source/VRF, server ACL/authentication, path loss/policers, then local daemon/resource behavior. |
| Leaf2 remains synchronized but selects a drifting peer | That upstream time source and why selection differs from Leaf1. |
| CVP node jumps/drifts while both leaves agree | CVP guest synchronization, hypervisor behavior and per-node time health. |
| All measured clocks stay correct, event aligns with stale telemetry | Measurement semantics, timestamp handling, ingestion and version-specific defects. |
| Large offset immediately after reboot or VM restore | Startup synchronization and recovery timeline; confirm it converges rather than assuming ongoing loss. |

These are hypotheses until supported by incident-time evidence. Record the
affected serial/build, peer addresses (sanitized when shared), event UTC timeline,
NTP samples and relevant counter/log deltas. After identifying a cause, propose a
specific configuration/software/infrastructure fix through the site's change
process. Validate over at least another comparable 24-hour window, including
event count and stable NTP state; do not mute the alert as a substitute for a fix.
