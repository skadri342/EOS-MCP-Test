#!/usr/bin/env python3
"""Explicit-target, fixed-command clock evidence collector. Dry run by default."""
import argparse
import base64
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
EOS_COMMANDS = (
    "show clock", "show ntp status", "show ntp associations", "show version",
    "show system resources", "show interfaces counters errors",
    "show logging threshold informational 200",
)
CVP_COMMANDS = tuple("clockdiag:" + x for x in
                     ("clock", "uptime", "timedatectl", "tracking", "sources",
                      "sourcestats", "ntpq", "os"))
MAX_BYTES = 1048576


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError("Duplicate YAML key")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def utc():
    return datetime.now(timezone.utc).isoformat()


def load_inventory(path):
    """Intentionally narrow subset: all.children.{eos,cvp,time_servers}."""
    data = yaml.load(Path(path).read_text(), Loader=UniqueLoader)
    if not isinstance(data, dict) or set(data) != {"all"}:
        raise ValueError("Expected all as the only inventory root")
    root = data["all"]
    if not isinstance(root, dict) or set(root) - {"vars", "children"}:
        raise ValueError("Collector supports root vars/children only")
    hosts = {}
    for group, spec in root.get("children", {}).items():
        if group not in {"eos", "cvp", "time_servers"} or set(spec) - {"vars", "hosts"}:
            raise ValueError("Collector supports flat eos/cvp/time_servers groups only")
        for name, host_vars in (spec.get("hosts") or {}).items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in hosts:
                raise ValueError("Invalid or duplicate host name")
            values = {**root.get("vars", {}), **spec.get("vars", {}), **(host_vars or {})}
            if "ansible_password" in values:
                raise ValueError("Use password environment references, not inventory passwords")
            if "ansible_host" not in values:
                raise ValueError("Missing ansible_host")
            address = values["ansible_host"]
            if not isinstance(address, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", address) or address.startswith("-"):
                raise ValueError("Invalid host address")
            user = values.get("mcp_user", values.get("ansible_user", ""))
            if group != "time_servers" and (not isinstance(user, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", user)):
                raise ValueError("Invalid username")
            values["_user"] = user
            values["_group"] = group
            hosts[name] = values
    return hosts


def eos_read(host, command):
    if command not in EOS_COMMANDS:
        raise ValueError("Command denied")
    if host.get("mcp_read_allowed", True) is not True:
        raise ValueError("Read access denied")
    if host.get("mcp_validate_certs", True) is not True or host.get("ansible_httpapi_validate_certs", True) is not True:
        raise ValueError("Collector requires verified TLS; install the network CA")
    env_name = host.get("mcp_password_env", "")
    if not re.fullmatch(r"EOS_MCP_[A-Z0-9_]+", env_name) or not os.environ.get(env_name):
        raise ValueError("Required EOS_MCP_ password variable is missing")
    password = os.environ[env_name]
    context = ssl.create_default_context(cafile=os.environ.get("EOS_CA_FILE") or None)
    address = host["ansible_host"]
    if ":" in address:
        address = "[" + address + "]"
    port = int(host.get("ansible_httpapi_port", 443))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid eAPI port")
    payload = {"jsonrpc": "2.0", "method": "runCmds", "id": 1,
               "params": {"version": 1, "cmds": [command], "format": "text"}}
    request = urllib.request.Request(
        f"https://{address}:{port}/command-api", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Basic " +
                 base64.b64encode(f'{host["_user"]}:{password}'.encode()).decode()})
    # No proxies or redirects: never forward device credentials elsewhere.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=context))
    with opener.open(request, timeout=15) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Response exceeds size limit")
    data = json.loads(raw)
    if data.get("id") != 1 or data.get("jsonrpc") != "2.0":
        raise ValueError("Invalid eAPI response envelope")
    if "error" in data:
        return {"status": "command_error", "output": data["error"]}
    if not isinstance(data.get("result"), list):
        raise ValueError("Missing eAPI result")
    return {"status": "ok", "output": data["result"]}


def local_secret_path(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to((ROOT / ".secrets").resolve()) or not path.is_file():
        raise ValueError("SSH key and known_hosts must be existing files under .secrets")
    return path


def cvp_read(host, command):
    if command not in CVP_COMMANDS:
        raise ValueError("Command denied")
    identity = local_secret_path(host["ansible_ssh_private_key_file"])
    known_hosts = local_secret_path(host["known_hosts_file"])
    port = int(host.get("ansible_port", 22))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid SSH port")
    argv = ["ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", "IdentityAgent=none", "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", f"UserKnownHostsFile={known_hosts}", "-o", "ConnectTimeout=10",
            "-i", str(identity), "-p", str(port), "-l", host["_user"], host["ansible_host"], command]
    # Dispatcher commands are fixed and short. Kill on timeout or excess output.
    import selectors
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = bytearray()
    deadline = time.monotonic() + 25
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    raise TimeoutError("SSH command timed out")
                for key, _ in selector.select(timeout=0.25):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > MAX_BYTES:
                            raise ValueError("SSH output exceeds size limit")
        code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
    return {"status": "ok" if code == 0 else "command_error", "exit_code": code,
            "output": output.decode(errors="replace")}


def is_example_address(address):
    try:
        ip = ipaddress.ip_address(address)
        return any(ip in ipaddress.ip_network(n) for n in
                   ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32"))
    except ValueError:
        return address.endswith(".example")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default="inventory/local.yml")
    parser.add_argument("--target", action="append", required=True, help="Explicit inventory host; repeat as needed")
    parser.add_argument("--execute", action="store_true", help="Contact targets; default only prints plan")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval", type=int, default=300, help="Seconds between sample starts")
    args = parser.parse_args()
    if not 1 <= args.samples <= 289 or not 60 <= args.interval <= 3600:
        parser.error("samples must be 1..289; interval must be 60..3600 seconds")
    hosts = load_inventory(args.inventory)
    selected = {}
    for target in dict.fromkeys(args.target):
        host = hosts.get(target)
        if host is None or host["_group"] not in {"eos", "cvp"}:
            parser.error("Every target must name an EOS or CVP inventory host")
        if host.get("mcp_read_allowed", True) is not True:
            parser.error("Target denies read access")
        if args.execute and is_example_address(host["ansible_host"]):
            parser.error("Replace documentation addresses before executing")
        selected[target] = host
    if not args.execute:
        for name, host in selected.items():
            print(name + ": " + ", ".join(EOS_COMMANDS if host["_group"] == "eos" else CVP_COMMANDS))
        print("DRY RUN: no connections made. Use --execute only after local account/TLS setup.")
        return 0
    os.umask(0o077)
    directory = ROOT / "reports" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory.mkdir(parents=True, mode=0o700)
    errors = 0
    try:
        for sample in range(args.samples):
            started = time.monotonic()
            for name, host in selected.items():
                records = []
                commands = EOS_COMMANDS if host["_group"] == "eos" else CVP_COMMANDS
                reader = eos_read if host["_group"] == "eos" else cvp_read
                for command in commands:
                    record = {"command": command, "started_utc": utc()}
                    tick = time.monotonic()
                    try:
                        record.update(reader(host, command))
                    except Exception as exc:
                        # Never serialize exceptions/requests containing authentication data.
                        record.update(status="collection_error", error_type=type(exc).__name__)
                    record.update(finished_utc=utc(), duration_seconds=round(time.monotonic() - tick, 3))
                    errors += record["status"] != "ok"
                    records.append(record)
                path = directory / f"{sample + 1:03d}-{name}.json"
                path.write_text(json.dumps({"host": name, "sample": sample + 1, "records": records}, indent=2) + "\n")
                print(f"Saved {path.relative_to(ROOT)}", flush=True)
            if sample + 1 < args.samples:
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
    finally:
        (directory / "README.md").write_text(
            "# Private clock evidence\n\nCompare each command's UTC time bracket, NTP status, reach, "
            "offset and selected peer against the healthy leaf and every CVP node.\n\n"
            "Unsupported or denied commands are evidence gaps. Do not treat them as an unhealthy device. "
            "Offsets/units depend on the command. No root cause is inferred automatically. "
            "Device output may contain sensitive operational information; review before sharing.\n")
    print(f"Command failures/gaps: {errors}. Evidence: {directory.relative_to(ROOT)}")
    return 2 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Collection interrupted; completed host samples remain in reports/.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Collection stopped ({type(exc).__name__}); check inventory and setup.", file=sys.stderr)
        sys.exit(1)
