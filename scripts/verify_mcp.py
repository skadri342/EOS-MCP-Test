#!/usr/bin/env python3
"""Offline MCP handshake/tool discovery using example inventory and a dummy secret."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = yaml.safe_load((ROOT / "config/eos-mcp.example.yml").read_text())
    config["inventory"] = str(ROOT / "inventory/example.yml")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.yml"
        path.write_text(yaml.safe_dump(config))
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                ["eos-mcp-server", "serve", "--config", str(path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True,
                env={**os.environ, "EOS_MCP_PASSWORD": "offline-test-placeholder"})
            def send(message, response=True):
                process.stdin.write(json.dumps(message) + "\n")
                process.stdin.flush()
                if not response:
                    return None
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    if not selector.select(timeout=15):
                        raise RuntimeError("MCP response timed out")
                line = process.stdout.readline()
                if not line:
                    errors.seek(0)
                    raise RuntimeError(errors.read(4096).decode(errors="replace"))
                result = json.loads(line)
                if "error" in result:
                    raise RuntimeError(result["error"])
                return result["result"]
            try:
                initialized = send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                               "clientInfo": {"name": "offline-test", "version": "1"}}})
                send({"jsonrpc": "2.0", "method": "notifications/initialized"}, response=False)
                result = send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                names = {tool["name"] for tool in result["tools"]}
                if not {"eos_run_show", "eos_list_inventory"} <= names:
                    raise RuntimeError("Missing expected tools")
                print(f'MCP {initialized["serverInfo"]["version"]}: initialized; {len(names)} tools discovered.')
                print("Offline only: no device tools called; example inventory and dummy password used.")
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    main()
