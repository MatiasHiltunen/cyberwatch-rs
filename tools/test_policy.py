"""Deliberately unsafe policy mutations must be rejected."""
from copy import deepcopy
from pathlib import Path
import unittest
import yaml
from policy_check import workload_errors, workflow_errors

ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.deployment = yaml.safe_load((ROOT / "deploy/base/deployment.yaml").read_text())

    def test_default_workload_and_digest_release_gate(self):
        self.assertEqual(workload_errors(self.deployment), [])
        self.assertTrue(workload_errors(self.deployment, release=True))
        self.deployment["spec"]["template"]["spec"]["containers"][0]["image"] = "ghcr.io/example/cyberwatch@sha256:" + "a" * 64
        self.assertEqual(workload_errors(self.deployment, release=True), [])

    def test_reject_sqlite_double_writer(self):
        for key, value in (("replicas", 2), ("strategy", {"type": "RollingUpdate"})):
            with self.subTest(key=key):
                changed = deepcopy(self.deployment)
                changed["spec"][key] = value
                self.assertTrue(workload_errors(changed))

    def test_reject_container_privilege_and_credentials(self):
        for field, value in (("privileged", True), ("readOnlyRootFilesystem", False), ("allowPrivilegeEscalation", True), ("capabilities", {"drop": ["ALL"], "add": ["NET_ADMIN"]})):
            with self.subTest(field=field):
                changed = deepcopy(self.deployment)
                changed["spec"]["template"]["spec"]["containers"][0]["securityContext"][field] = value
                self.assertTrue(workload_errors(changed))
        self.deployment["spec"]["template"]["spec"]["automountServiceAccountToken"] = True
        self.assertTrue(workload_errors(self.deployment))

    def test_reject_mutable_actions_and_elevated_pr_trigger(self):
        workflow = {"permissions": {"contents": "read"}, "jobs": {"test": {"steps": [{"uses": "actions/checkout@main"}]}}}
        self.assertTrue(workflow_errors(workflow))
        workflow["jobs"] = {}
        workflow["on"] = {"pull_request_target": {}}
        self.assertTrue(workflow_errors(workflow))

    def test_checked_in_workflows(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            with self.subTest(path=path.name):
                self.assertEqual(workflow_errors(yaml.safe_load(path.read_text())), [])


if __name__ == "__main__":
    unittest.main()
