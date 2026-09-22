import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ado_release

spec = importlib.util.spec_from_file_location('update_runtime', Path(__file__).resolve().parents[1] / 'deploy/azure/update_runtime.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class PromotionTests(unittest.TestCase):
    def fixture(self):
        build = {'sourceVersion': 'a'*40, 'sourceBranch': 'refs/heads/main', 'status': 'completed',
                 'result': 'succeeded', 'definition': {'id': 12}, 'repository': {'id': ado_release.REPOSITORY}}
        timeline = {'records': [{'type': 'Stage', 'identifier': 'DeployStaging', 'state': 'completed', 'result': 'succeeded'}]}
        return build, timeline

    def test_same_commit_staged_success_is_required(self):
        build, timeline = self.fixture()
        self.assertTrue(ado_release.staged_candidate(build, timeline, 'a'*40, 12))
        self.assertFalse(ado_release.staged_candidate(build, timeline, 'b'*40, 12))
        self.assertFalse(ado_release.staged_candidate(build, timeline, 'a'*40, 13))
        for state in ('skipped', 'failed', 'canceled'):
            timeline['records'][0]['result'] = state
            self.assertFalse(ado_release.staged_candidate(build, timeline, 'a'*40, 12))

    def test_another_repository_or_branch_cannot_supply_release(self):
        for field, value in [('repository', {'id': 'other'}), ('sourceBranch', 'refs/heads/feature')]:
            build, timeline = self.fixture()
            build[field] = value
            self.assertFalse(ado_release.staged_candidate(build, timeline, 'a'*40, 12))

    def test_tampered_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = b'fixture image'
            manifest = {'schema': 1, 'commit': 'a'*40, 'archive': 'image.tar', 'platform': 'linux/arm64',
                        'image': 'cyberwatch-release:'+'a'*40, 'imageConfigId': 'sha256:'+'b'*64,
                        'archiveSha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
            (root/'release.json').write_text(json.dumps(manifest))
            (root/'image.tar').write_bytes(data)
            ado_release.validate_release(root, 'a'*40)
            (root/'image.tar').write_bytes(b'tampered data')
            with self.assertRaises(ValueError):
                ado_release.validate_release(root, 'a'*40)
            with self.assertRaises(ValueError):
                ado_release.validate_release(root, 'c'*40)

    def test_vm_rejects_external_or_wrong_artifact_url(self):
        payload = {'commit': 'a'*40, 'image': 'cyberwatch-release:'+'a'*40, 'imageConfigId': 'sha256:'+'b'*64,
                   'archiveSha256': 'c'*64, 'bytes': 100, 'platform': 'linux/arm64',
                   'url': 'https://example.blob.core.windows.net/artifacts/releases/'+'a'*40+'/'+'c'*64+'.tar?sig=fixture'}
        updater.validate_payload(payload)
        for url in ('http://example.blob.core.windows.net/fixture', 'https://evil.example/file?sig=x',
                    'https://example.blob.core.windows.net/wrong/path?sig=x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                updater.validate_payload(dict(payload, url=url))

    def test_readiness_failure_restores_previous_image_and_stays_failed(self):
        previous = 'CYBERWATCH_IMAGE=sha256:'+'a'*64+'\n'
        with patch.object(updater, 'schema_fingerprint', return_value='unchanged'), \
                patch.object(updater, 'call') as calls, patch.object(updater, 'atomic_config') as config, \
                patch.object(updater, 'wait_ready', side_effect=[RuntimeError('failed'), None]):
            with self.assertRaisesRegex(RuntimeError, 'previous image restored'):
                updater.activate('sha256:'+'b'*64, previous, Path('/fixture.db'))
            self.assertEqual(config.call_args.args[0], previous)
            self.assertEqual(calls.call_args.args[0], ['systemctl', 'start', 'cyberwatch-health.timer'])

    def test_schema_change_stops_service_for_manual_recovery(self):
        with patch.object(updater, 'schema_fingerprint', side_effect=['old', 'new']), \
                patch.object(updater, 'call') as calls, patch.object(updater, 'atomic_config') as config, \
                patch.object(updater, 'wait_ready', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'manual recovery required'):
                updater.activate('sha256:'+'b'*64, 'CYBERWATCH_IMAGE=sha256:'+'a'*64+'\n', Path('/fixture.db'))
            self.assertEqual(config.call_count, 1)
            self.assertEqual(calls.call_args.args[0], ['systemctl', 'stop', 'cyberwatch.service'])
            self.assertNotIn(['systemctl', 'start', 'cyberwatch-health.timer'],
                             [invocation.args[0] for invocation in calls.call_args_list])

    def test_health_worker_is_quiesced_until_candidate_is_verified(self):
        state = {'timer': True, 'worker': True, 'ready': False}

        def systemctl(args):
            if args == ['systemctl', 'stop', 'cyberwatch-health.timer']:
                state['timer'] = False
            elif args == ['systemctl', 'stop', 'cyberwatch-health.service']:
                self.assertFalse(state['timer'], 'Stop new timer activations before draining the worker')
                state['worker'] = False
            elif args[-1] == 'cyberwatch.service':
                self.assertFalse(state['timer'])
                self.assertFalse(state['worker'], 'An in-flight health worker can restart the application')
            elif args == ['systemctl', 'start', 'cyberwatch-health.timer']:
                self.assertTrue(state['ready'], 'Only a verified runtime may resume health monitoring')
                state['timer'] = True

        def ready(_image):
            state['ready'] = True

        with patch.object(updater, 'schema_fingerprint', return_value='unchanged'), \
                patch.object(updater, 'call', side_effect=systemctl), \
                patch.object(updater, 'atomic_config'), patch.object(updater, 'wait_ready', side_effect=ready):
            updater.activate('sha256:'+'b'*64, 'CYBERWATCH_IMAGE=sha256:'+'a'*64+'\n', Path('/fixture.db'))
        self.assertTrue(state['timer'])

    def test_failed_rollback_does_not_resume_health_monitoring(self):
        with patch.object(updater, 'schema_fingerprint', return_value='unchanged'), \
                patch.object(updater, 'call') as calls, patch.object(updater, 'atomic_config'), \
                patch.object(updater, 'wait_ready', side_effect=RuntimeError('Runtime did not become ready')):
            with self.assertRaisesRegex(RuntimeError, 'Runtime did not become ready'):
                updater.activate('sha256:'+'b'*64, 'CYBERWATCH_IMAGE=sha256:'+'a'*64+'\n', Path('/fixture.db'))
            self.assertNotIn(['systemctl', 'start', 'cyberwatch-health.timer'],
                             [invocation.args[0] for invocation in calls.call_args_list])

    def test_crashing_candidate_cannot_leave_rollback_start_limited(self):
        previous = 'CYBERWATCH_IMAGE=sha256:'+'a'*64+'\n'
        candidate = 'sha256:'+'b'*64
        rate_limited = False
        restored_healthy = False

        def systemctl(args):
            nonlocal rate_limited
            if args == ['systemctl', 'reset-failed', 'cyberwatch.service']:
                rate_limited = False
            if args == ['systemctl', 'start', 'cyberwatch.service'] and rate_limited:
                raise RuntimeError('Start request repeated too quickly')

        def readiness(image):
            nonlocal rate_limited, restored_healthy
            if image == candidate:
                # Restart=always exhausts StartLimitBurst while a crashing image
                # is repeatedly restarted during the readiness wait.
                rate_limited = True
                raise RuntimeError('Candidate did not become ready')
            self.assertEqual(image, previous.strip().split('=', 1)[1])
            self.assertFalse(rate_limited)
            restored_healthy = True

        with patch.object(updater, 'schema_fingerprint', return_value='unchanged'), \
                patch.object(updater, 'call', side_effect=systemctl), \
                patch.object(updater, 'atomic_config') as config, \
                patch.object(updater, 'wait_ready', side_effect=readiness):
            with self.assertRaisesRegex(RuntimeError, 'previous image restored and healthy'):
                updater.activate(candidate, previous, Path('/fixture.db'))
            self.assertEqual(config.call_args.args[0], previous)
            self.assertTrue(restored_healthy)


if __name__ == '__main__':
    unittest.main()
