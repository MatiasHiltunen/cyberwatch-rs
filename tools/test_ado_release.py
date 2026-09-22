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
            self.assertEqual(calls.call_args.args[0], ['systemctl', 'start', 'cyberwatch.service'])

    def test_schema_change_stops_service_for_manual_recovery(self):
        with patch.object(updater, 'schema_fingerprint', side_effect=['old', 'new']), \
                patch.object(updater, 'call') as calls, patch.object(updater, 'atomic_config') as config, \
                patch.object(updater, 'wait_ready', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'manual recovery required'):
                updater.activate('sha256:'+'b'*64, 'CYBERWATCH_IMAGE=sha256:'+'a'*64+'\n', Path('/fixture.db'))
            self.assertEqual(config.call_count, 1)
            self.assertEqual(calls.call_args.args[0], ['systemctl', 'stop', 'cyberwatch.service'])


if __name__ == '__main__':
    unittest.main()
