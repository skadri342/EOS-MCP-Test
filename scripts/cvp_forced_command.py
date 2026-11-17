#!/usr/bin/env python3
"""Admin-reviewed SSH forced-command dispatcher; no arbitrary shell commands.

Install only if Arista approves this mechanism for your CVP release. This file is
not automatically installed by the container or collector.
"""
import os
import subprocess
import sys

COMMANDS = {
    "clockdiag:clock": ["/usr/bin/date", "-u", "+%Y-%m-%dT%H:%M:%S.%NZ"],
    "clockdiag:uptime": ["/usr/bin/uptime"],
    "clockdiag:timedatectl": ["/usr/bin/timedatectl", "status"],
    "clockdiag:tracking": ["/usr/bin/chronyc", "-n", "tracking"],
    "clockdiag:sources": ["/usr/bin/chronyc", "-n", "sources", "-v"],
    "clockdiag:sourcestats": ["/usr/bin/chronyc", "-n", "sourcestats", "-v"],
    "clockdiag:ntpq": ["/usr/sbin/ntpq", "-pn"],
    "clockdiag:os": ["/usr/bin/cat", "/etc/os-release"],
}


def main():
    command = COMMANDS.get(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    if command is None:
        print("Denied: use an approved clockdiag command ID.", file=sys.stderr)
        return 126
    try:
        return subprocess.run(command, timeout=15, check=False, cwd="/",
                              env={"PATH": "/usr/bin:/usr/sbin:/bin", "LC_ALL": "C"}).returncode
    except (OSError, subprocess.TimeoutExpired):
        print("Command unavailable, denied, or timed out.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
