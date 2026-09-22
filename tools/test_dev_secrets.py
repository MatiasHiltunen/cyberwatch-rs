import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import dev_secrets


class SecretTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Linux permission boundary")
    def test_private_file_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = dev_secrets.private_directory(Path(temp))
            path = dev_secrets.stage(directory, "keyvault-admin-token", "a" * 48)
            dev_secrets.stage(directory, "keyvault-admin-token", "b" * 48)
            self.assertEqual(path.read_text(), "b" * 48)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual([p.name for p in directory.iterdir()], [path.name])

    @unittest.skipUnless(os.name == "posix", "Linux symlink boundary")
    def test_symlink_cannot_overwrite_another_file(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = dev_secrets.private_directory(Path(temp))
            victim = Path(temp) / "victim"
            victim.write_text("unchanged")
            (directory / "keyvault-admin-token").symlink_to(victim)
            with self.assertRaises(ValueError):
                dev_secrets.stage(directory, "keyvault-admin-token", "a" * 48)
            self.assertEqual(victim.read_text(), "unchanged")

    def test_failed_cli_output_is_not_disclosed(self):
        result = subprocess.CompletedProcess([], 1, "sensitive-value", "sensitive-error")
        with patch("dev_secrets.subprocess.run", return_value=result):
            with self.assertRaises(ValueError) as error:
                dev_secrets.az_json(["keyvault", "show"])
        self.assertNotIn("sensitive", str(error.exception))

    def test_explicit_vault_subscription_and_version(self):
        with patch("dev_secrets.az_json", side_effect=["/subscriptions/123/resourceGroups/dev/providers/Microsoft.KeyVault/vaults/dev-vault", "a" * 48]) as command:
            self.assertEqual(dev_secrets.fetch("dev-vault", "admin-dev", "123", "b" * 32), "a" * 48)
        self.assertIn("--version", command.call_args.args[0])
        self.assertIn("value", command.call_args.args[0])

    def test_wrong_subscription_prevents_secret_read(self):
        with patch("dev_secrets.az_json", return_value="/subscriptions/other/vaults/v") as command:
            with self.assertRaises(ValueError):
                dev_secrets.fetch("dev-vault", "admin-dev", "123", None)
        self.assertEqual(command.call_count, 1)

    def test_invalid_token_cannot_replace_working_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "token"
            path.write_text("a" * 48)
            with self.assertRaises(ValueError):
                dev_secrets.stage(Path(temp), "token", "too-short")
            self.assertEqual(path.read_text(), "a" * 48)

    def test_cli_failure_exits_without_secret_output(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, patch("dev_secrets.private_directory", return_value=Path(temp)), patch("dev_secrets.fetch", side_effect=ValueError("sensitive-value")), patch("sys.argv", ["dev_secrets.py", "keyvault", "--vault", "dev-vault", "--secret", "admin-dev", "--subscription", "123"]), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as error:
                dev_secrets.main()
            self.assertEqual(list(Path(temp).iterdir()), [])
        self.assertNotIn("sensitive-value", str(error.exception) + output.getvalue())


if __name__ == "__main__":
    unittest.main()
