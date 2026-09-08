import unittest
from pathlib import Path
import json
import subprocess
import tempfile
from unittest.mock import patch
from deploy import main, validate_inputs


class DeployScopeTests(unittest.TestCase):
    def test_valid_immutable_scoped_release(self):
        validate_inputs("ghcr.io/team/cyberwatch@sha256:" + "a" * 64, "cyberwatch-yamk282", "team/cyberwatch")

    def test_reject_mutable_external_or_injected_targets(self):
        digest = "ghcr.io/team/cyberwatch@sha256:" + "a" * 64
        cases = [("ghcr.io/team/cyberwatch:latest", "cyberwatch-yamk282", "team/cyberwatch"),
                 (digest, "default", "team/cyberwatch"),
                 (digest, "cyberwatch-a;echo hi", "team/cyberwatch"),
                 (digest, "cyberwatch-yamk282", "other/repository")]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    validate_inputs(*case)

    def invoke(self, output, run):
        previous = "ghcr.io/team/cyberwatch@sha256:" + "a" * 64
        candidate = "ghcr.io/team/cyberwatch@sha256:" + "b" * 64
        deployment = {"spec": {"replicas": 1, "strategy": {"type": "Recreate"}, "template": {"spec": {"containers": [{"name": "cyberwatch", "image": previous}]}}}}
        argv = ["deploy.py", "--image", candidate, "--namespace", "cyberwatch-yamk282",
                "--repository", "team/cyberwatch", "--output", str(output)]
        with patch("sys.argv", argv), patch("deploy.subprocess.run", side_effect=run), patch("deploy.subprocess.check_output", return_value=json.dumps(deployment)):
            main()

    def test_rejected_provenance_cannot_touch_cluster(self):
        calls = []
        def reject(command, **kwargs):
            calls.append(command)
            raise subprocess.CalledProcessError(1, command)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(Path(directory) / "result.json", reject)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:3], ["gh", "attestation", "verify"])
        self.assertIn("--source-ref", calls[0])
        self.assertIn("refs/heads/main", calls[0])
        self.assertIn("--deny-self-hosted-runners", calls[0])

    def test_failed_rollout_restores_previous_digest_and_stays_failed(self):
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
            # Verification, baseline health, set candidate, failed rollout,
            # restore previous image, confirm recovered readiness.
            if len(calls) == 4:
                raise subprocess.CalledProcessError(1, command)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(output, runner)
            result = json.loads(output.read_text())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["rollback"], "restored-previous-image")
        self.assertEqual(calls[4][-1], "cyberwatch=ghcr.io/team/cyberwatch@sha256:" + "a" * 64)
        self.assertEqual(len(calls), 6)


if __name__ == "__main__":
    unittest.main()
