import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ado_infra as infra


class InfrastructureGuards(unittest.TestCase):
    def setUp(self):
        self.value = {'environment': 'prod', 'subscription': infra.SUBSCRIPTION,
                      'resourceGroup': 'rg-cyberwatch-yamk-swe', 'vm': 'cyberwatch-yamk',
                      'dnsLabel': 'cyberwatch-yamk-afe8ae-20260908',
                      'storageAccount': 'cywqqv6z273n7dfk', 'container': 'artifacts'}
        self.commit = 'a' * 40

    def report(self, modified=False):
        result = {'status': 'Succeeded', 'changes': [
            {'resourceId': identifier, 'changeType': 'NoChange', 'delta': []}
            for identifier in infra.resources(self.value)]}
        if modified:
            result['changes'][0].update(changeType='Modify', delta=[
                {'path': 'tags.course', 'propertyChangeType': 'Modify',
                 'before': 'old', 'after': 'YAMK282-YAMK283'}])
        return infra.reviewed_changes(result, self.value)

    def artifact(self, directory):
        for name, content in [('template.json', {'resources': []}),
                              ('parameters.json', infra.parameters(self.value)),
                              ('what-if.json', self.report())]:
            infra.write_json(directory / name, content)
        manifest = {'schema': 1, 'commit': self.commit, 'environment': 'prod',
                    'subscription': infra.SUBSCRIPTION, 'resourceGroup': self.value['resourceGroup'],
                    'mode': 'Incremental', 'sources': infra.source_hashes(),
                    'files': {name: infra.digest((directory / name).read_bytes()) for name in infra.FILES}}
        infra.write_json(directory / 'plan.json', manifest)
        return manifest

    def test_resource_ids_are_exact_and_exclude_vm_identity_and_rbac_writes(self):
        selected = infra.resources(self.value)
        base = f"/subscriptions/{infra.SUBSCRIPTION}/resourcegroups/rg-cyberwatch-yamk-swe/providers/"
        self.assertEqual(len(selected), 8)
        self.assertEqual(len(infra.resources(self.value, include_bootstrap=True)), 9)
        self.assertTrue(all(identifier.startswith(base) for identifier in selected))
        self.assertIn(base + 'microsoft.storage/storageaccounts/cywqqv6z273n7dfk/blobservices/default/containers/artifacts', selected)
        self.assertFalse(any('virtualmachines/' in identifier or 'networkinterfaces/' in identifier or 'managedidentit' in identifier
                             or 'roleassignment' in identifier for identifier in selected))

    def test_apply_cannot_assume_local_or_feature_checkout_is_main(self):
        for branch in (None, 'refs/heads/feature', 'refs/tags/v1.0.0'):
            values = {} if branch is None else {'BUILD_SOURCEBRANCH': branch}
            with self.subTest(branch=branch), patch.dict(os.environ, values, clear=True):
                with self.assertRaisesRegex(ValueError, 'protected main'):
                    infra.require_apply_branch()
        with patch.dict(os.environ, {'BUILD_SOURCEBRANCH': 'refs/heads/main'}, clear=True):
            infra.require_apply_branch()

    def test_create_delete_incomplete_and_unknown_resources_are_rejected(self):
        for kind in ('Create', 'Delete', 'Ignore', 'Deploy', 'Unsupported'):
            report = self.report()
            report['changes'][0]['changeType'] = kind
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                infra.reviewed_changes(report, self.value)
        report = self.report()
        report['changes'].pop()
        with self.assertRaisesRegex(ValueError, 'omitted'):
            infra.reviewed_changes(report, self.value)
        report = self.report()
        report['changes'][0]['resourceId'] = '/subscriptions/other/resourceGroups/other/providers/Unknown/resources/name'
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            infra.reviewed_changes(report, self.value)

    def test_replacement_sensitive_changes_are_rejected(self):
        for resource_type, path in [
            ('Microsoft.Compute/disks', 'properties.diskSizeGB'),
            ('Microsoft.Compute/disks', 'properties.creationData.createOption'),
            ('Microsoft.Network/publicIPAddresses', 'properties.dnsSettings.domainNameLabel'),
            ('Microsoft.Network/virtualNetworks', 'properties.addressSpace.addressPrefixes'),
            ('Microsoft.Storage/storageAccounts', 'location'),
            ('Microsoft.Storage/storageAccounts', 'properties.encryption.keySource'),
        ]:
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'Replacement-sensitive'):
                infra.clean_delta({'path': path, 'propertyChangeType': 'Modify', 'before': 'old', 'after': 'new'}, resource_type)

    def disk_report(self):
        report = self.report()
        change = next(item for item in report['changes'] if '/disks/' in item['resourceId'])
        change.update(changeType='Modify',
                      before={'sku': {'name': 'StandardSSD_LRS'}, 'properties': {
                          'diskSizeGB': 4, 'diskIOPSReadWrite': 500, 'diskMBpsReadWrite': 100}},
                      after={'sku': {'name': 'StandardSSD_LRS'}, 'properties': {'diskSizeGB': 4}},
                      delta=[{'path': 'properties.diskIOPSReadWrite', 'propertyChangeType': 'Delete',
                              'before': 500, 'after': None, 'children': None}])
        return report, change

    def test_known_computed_disk_default_is_visible_but_not_a_write(self):
        report, _change = self.disk_report()
        normalized = infra.reviewed_changes(report, self.value)
        disk = next(item for item in normalized['changes'] if '/disks/' in item['resourceId'])
        self.assertEqual(disk['changeType'], 'NoChange')
        self.assertEqual(disk['delta'][0]['reason'], 'standard-ssd-computed-performance')
        self.assertEqual(infra.reviewed_changes(normalized, self.value), normalized)

    def test_computed_disk_exception_does_not_hide_real_changes_or_other_skus(self):
        for mutation in ('sku', 'capacity', 'performance', 'delta', 'unexpected-default'):
            report, change = self.disk_report()
            if mutation == 'sku':
                change['after']['sku']['name'] = 'UltraSSD_LRS'
            elif mutation == 'capacity':
                change['after']['properties']['diskSizeGB'] = 8
            elif mutation == 'performance':
                change['after']['properties']['diskIOPSReadWrite'] = 1000
            elif mutation == 'delta':
                change['delta'][0].update(propertyChangeType='Modify', after=1000)
            else:
                change['before']['properties']['diskIOPSReadWrite'] = 600
                change['delta'][0]['before'] = 600
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'Replacement-sensitive'):
                infra.reviewed_changes(report, self.value)

    def test_azure_noeffect_does_not_hide_a_real_writable_change(self):
        report = self.report()
        item = next(item for item in report['changes'] if '/networksecuritygroups/' in item['resourceId'])
        item['delta'] = [{'path': 'provider.readonly', 'propertyChangeType': 'NoEffect',
                          'before': None, 'after': {'unpublished': 'discard'}, 'children': None}]
        normalized = infra.reviewed_changes(report, self.value)
        self.assertNotIn(b'unpublished', infra.encoded(normalized))
        item['changeType'] = 'Modify'
        item['delta'].append({'path': 'tags.course', 'propertyChangeType': 'Modify', 'before': 'old', 'after': 'new'})
        normalized = infra.reviewed_changes(report, self.value)
        self.assertEqual(next(item for item in normalized['changes'] if '/networksecuritygroups/' in item['resourceId'])['changeType'], 'Modify')

    def test_sanitized_review_preserves_nonsecret_values_but_not_full_resource_payload(self):
        raw = self.report(modified=True)
        raw['changes'][0]['before'] = {'unrelatedSensitiveProperty': 'do-not-publish'}
        raw['changes'][0]['after'] = {'unrelatedSensitiveProperty': 'do-not-publish'}
        report = infra.reviewed_changes(raw, self.value)
        self.assertNotIn(b'do-not-publish', infra.encoded(report))
        self.assertIn(b'YAMK282-YAMK283', infra.encoded(report))
        nested = infra.clean_delta({'path': 'properties.securityRules', 'propertyChangeType': 'Array',
                                   'children': [{'path': '[0].properties.access', 'propertyChangeType': 'Modify',
                                                 'before': 'Allow', 'after': 'Deny'}]},
                                  'Microsoft.Network/networkSecurityGroups')
        self.assertEqual(nested['children'][0]['after'], 'Deny')

    def test_wrong_account_fails_before_any_resource_write(self):
        with patch.object(infra, 'az', return_value={'id': 'another', 'state': 'Enabled'}) as az:
            with self.assertRaisesRegex(ValueError, 'subscription'):
                infra.verify_existing(self.value)
            self.assertEqual(az.call_args_list[0].args, ('account', 'show'))
            self.assertEqual(az.call_count, 1)

    def test_missing_existing_resource_aborts_preflight(self):
        group = f"/subscriptions/{infra.SUBSCRIPTION}/resourceGroups/{self.value['resourceGroup']}"
        responses = [
            {'id': infra.SUBSCRIPTION, 'state': 'Enabled'},
            {'id': group, 'location': 'swedencentral', 'tags': {'project': 'Cyberwatch'}},
            {'id': group + '/providers/Microsoft.Compute/virtualMachines/' + self.value['vm']},
            RuntimeError('Not found'),
        ]
        with patch.object(infra, 'az', side_effect=responses) as az:
            with self.assertRaisesRegex(RuntimeError, 'Not found'):
                infra.verify_existing(self.value)
            self.assertEqual(az.call_count, 4)
            self.assertFalse(any('create' in call.args for call in az.call_args_list))

    def test_artifact_tampering_and_cross_environment_reuse_fail(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.artifact(directory)
            changed = dict(self.value, environment='staging')
            with self.assertRaisesRegex(ValueError, 'another environment'):
                infra.validate_artifact(changed, directory, self.commit)
            (directory / 'template.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                infra.validate_artifact(self.value, directory, self.commit)

    def test_altering_template_and_manifest_together_still_requires_committed_template(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.artifact(directory)
            def compile_original(path, _value):
                infra.write_json(path, {'resources': ['actual committed template']})
            with patch.object(infra, 'compile_template', side_effect=compile_original):
                with self.assertRaisesRegex(ValueError, 'Compiled template differs'):
                    infra.validate_artifact(self.value, directory, self.commit)

    def test_drift_or_missing_resource_blocks_apply_before_deployment(self):
        saved = self.report(modified=True)
        drift = copy.deepcopy(saved)
        next(item for item in drift['changes'] if item['changeType'] == 'Modify')['delta'][0]['before'] = 'changed after approval'
        with patch.object(infra, 'validate_artifact', return_value=saved), \
                patch.object(infra, 'verify_existing'), patch.object(infra, 'what_if', return_value=drift), \
                patch.object(infra, 'az') as az:
            with self.assertRaisesRegex(ValueError, 'changed since review'):
                infra.apply(self.value, Path('/fixture'), self.commit)
            az.assert_not_called()
        with patch.object(infra, 'validate_artifact', return_value=saved), \
                patch.object(infra, 'verify_existing', side_effect=ValueError('missing resource')), \
                patch.object(infra, 'what_if') as what_if, patch.object(infra, 'az') as az:
            with self.assertRaisesRegex(ValueError, 'missing resource'):
                infra.apply(self.value, Path('/fixture'), self.commit)
            what_if.assert_not_called()
            az.assert_not_called()

    def test_unchanged_plan_does_not_submit_deployment(self):
        saved = self.report()
        with patch.object(infra, 'validate_artifact', return_value=saved), \
                patch.object(infra, 'verify_existing'), patch.object(infra, 'what_if', return_value=saved), \
                patch.object(infra, 'az') as az:
            infra.apply(self.value, Path('/fixture'), self.commit)
            az.assert_not_called()

    def test_approved_matching_plan_deploys_incrementally_to_fixed_scope(self):
        saved = self.report(modified=True)
        with patch.object(infra, 'validate_artifact', return_value=saved), \
                patch.object(infra, 'verify_existing'), patch.object(infra, 'what_if', return_value=saved), \
                patch.object(infra, 'az', return_value={'id': 'receipt', 'properties': {'provisioningState': 'Succeeded'}}) as az:
            infra.apply(self.value, Path('/fixture'), self.commit)
            args = az.call_args.args
            self.assertEqual(args[:3], ('deployment', 'group', 'create'))
            self.assertEqual(args[args.index('--subscription') + 1], infra.SUBSCRIPTION)
            self.assertEqual(args[args.index('--mode') + 1], 'Incremental')
            self.assertEqual(args[args.index('--resource-group') + 1], self.value['resourceGroup'])


if __name__ == '__main__':
    unittest.main()
