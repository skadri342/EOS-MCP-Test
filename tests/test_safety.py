"""Exercise trust boundaries without contacting devices."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


collect = module("collect", "collect.py")
forced = module("forced", "cvp_forced_command.py")


class SafetyTests(unittest.TestCase):
    def test_example_dry_run_never_contacts_network(self):
        with patch.object(collect, "eos_read") as eos, patch.object(collect, "cvp_read") as cvp:
            with patch("sys.argv", ["collect", "--inventory", str(ROOT / "inventory/example.yml"),
                                    "--target", "TOR-F2-Leaf2", "--target", "cvp1"]):
                self.assertEqual(collect.main(), 0)
            eos.assert_not_called()
            cvp.assert_not_called()

    def test_execute_refuses_example_addresses(self):
        with patch("sys.argv", ["collect", "--inventory", str(ROOT / "inventory/example.yml"),
                                "--target", "TOR-F2-Leaf2", "--execute"]):
            with self.assertRaises(SystemExit):
                collect.main()

    def test_duplicate_yaml_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.yml"
            path.write_text("all: {}\nall: {}\n")
            with self.assertRaises(ValueError):
                collect.load_inventory(path)

    def test_shell_injection_denied(self):
        with patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "clockdiag:clock; id"}):
            with patch.object(forced.subprocess, "run") as run:
                self.assertEqual(forced.main(), 126)
                run.assert_not_called()

    def test_eos_arbitrary_command_denied(self):
        with self.assertRaises(ValueError):
            collect.eos_read({}, "configure terminal")

    def test_cv_arbitrary_command_denied(self):
        with self.assertRaises(ValueError):
            collect.cvp_read({}, "sudo date -s tomorrow")

    def test_fixed_dispatch_no_shell(self):
        with patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "clockdiag:tracking"}):
            with patch.object(forced.subprocess, "run") as run:
                run.return_value.returncode = 0
                self.assertEqual(forced.main(), 0)
                self.assertEqual(run.call_args.args[0], ["/usr/bin/chronyc", "-n", "tracking"])
                self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_eapi_uses_fixed_text_command_and_preserves_result(self):
        host = {"ansible_host": "leaf.example", "_user": "clockdiag",
                "mcp_password_env": "EOS_MCP_PASSWORD"}
        with patch.dict(os.environ, {"EOS_MCP_PASSWORD": "test-only-not-a-real-secret"}):
            with patch.object(collect.urllib.request, "build_opener") as build:
                build.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "result": [{"output": "synchronized"}]}).encode()
                result = collect.eos_read(host, "show ntp status")
                self.assertEqual(result, {"status": "ok", "output": [{"output": "synchronized"}]})
                request = build.return_value.open.call_args.args[0]
                payload = json.loads(request.data)
                self.assertEqual(payload["params"]["cmds"], ["show ntp status"])
                self.assertEqual(payload["params"]["format"], "text")
                self.assertEqual(request.full_url, "https://leaf.example:443/command-api")

    def test_eapi_denied_read_never_connects(self):
        with patch.object(collect.urllib.request, "build_opener") as build:
            with self.assertRaises(ValueError):
                collect.eos_read({"mcp_read_allowed": False}, "show clock")
            build.assert_not_called()

    def test_eapi_insecure_tls_never_connects(self):
        with patch.object(collect.urllib.request, "build_opener") as build:
            with self.assertRaises(ValueError):
                collect.eos_read({"mcp_validate_certs": False}, "show clock")
            build.assert_not_called()

    def test_failed_command_is_retained_and_following_commands_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(collect, "ROOT", Path(directory)), patch.object(collect, "is_example_address", return_value=False):
                with patch.object(collect, "eos_read", side_effect=[ValueError("test failure")] +
                                  [{"status": "ok", "output": "sample"}] * (len(collect.EOS_COMMANDS) - 1)):
                    with patch("sys.argv", ["collect", "--inventory", str(ROOT / "inventory/example.yml"),
                                            "--target", "TOR-F2-Leaf2", "--execute"]):
                        self.assertEqual(collect.main(), 2)
                report = next((Path(directory) / "reports").glob("*/*.json"))
                records = json.loads(report.read_text())["records"]
                self.assertEqual(len(records), len(collect.EOS_COMMANDS))
                self.assertEqual(records[0]["status"], "collection_error")
                self.assertTrue(all(r["status"] == "ok" for r in records[1:]))


if __name__ == "__main__":
    unittest.main()
