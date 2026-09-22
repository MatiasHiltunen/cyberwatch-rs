"""Verify the admin helper never plans subscription-wide or cross-environment roles."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'grant_pipeline_roles', Path(__file__).resolve().parents[1] / 'deploy/azure/grant_pipeline_roles.py')
roles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roles)


class RoleScopeTests(unittest.TestCase):
    def setUp(self):
        self.targets = {'subscription': 'fixture-subscription'}
        for environment in ('staging', 'prod'):
            self.targets[environment] = {'resourceGroup': 'rg-' + environment, 'vm': 'vm-' + environment,
                                         'storageAccount': 'storage' + environment, 'container': 'artifacts'}

    def azure(self, *args):
        if args == ('account', 'show'):
            return {'id': self.targets['subscription']}
        group, name = args[args.index('-g') + 1], args[args.index('-n') + 1]
        base = '/subscriptions/fixture-subscription/resourceGroups/' + group + '/providers/'
        if args[:2] == ('identity', 'show'):
            return {'id': base + 'Microsoft.ManagedIdentity/userAssignedIdentities/' + name,
                    'principalId': '11111111-1111-1111-1111-' + ('1' if group.endswith('staging') else '2') * 12}
        if args[:2] == ('vm', 'show'):
            return {'id': base + 'Microsoft.Compute/virtualMachines/' + name}
        if args[:3] == ('storage', 'account', 'show'):
            return {'id': base + 'Microsoft.Storage/storageAccounts/' + name}
        self.fail('Planning must not modify Azure: ' + str(args))

    def test_six_assignments_are_confined_to_each_environment(self):
        with patch.object(roles, 'az', side_effect=self.azure):
            entries = roles.plan(self.targets)
        self.assertEqual(len(entries), 6)
        for environment in ('staging', 'prod'):
            own = [entry for entry in entries if entry['environment'] == environment]
            self.assertEqual(len(own), 3)
            self.assertEqual(len({entry['principalId'] for entry in own}), 1)
            base = '/subscriptions/fixture-subscription/resourceGroups/rg-' + environment + '/providers/'
            self.assertEqual({entry['role']: entry['scope'] for entry in own}, {
                'Virtual Machine Contributor': base + 'Microsoft.Compute/virtualMachines/vm-' + environment,
                'Storage Blob Delegator': base + 'Microsoft.Storage/storageAccounts/storage' + environment,
                'Storage Blob Data Contributor': base + 'Microsoft.Storage/storageAccounts/storage' + environment
                                                + '/blobServices/default/containers/artifacts'})
        self.assertNotEqual(entries[0]['principalId'], entries[3]['principalId'])

    def test_an_incomplete_or_misresolved_environment_prevents_a_plan(self):
        self.targets['prod']['storageAccount'] = None
        with patch.object(roles, 'az', side_effect=self.azure), self.assertRaisesRegex(ValueError, 'bootstrap'):
            roles.plan(self.targets)
        self.targets['prod']['storageAccount'] = 'storageprod'

        def wrong_scope(*args):
            result = self.azure(*args)
            if args[:2] == ('identity', 'show'):
                result['id'] = result['id'].replace('rg-staging', 'rg-prod')
            return result

        with patch.object(roles, 'az', side_effect=wrong_scope), self.assertRaisesRegex(ValueError, 'scope'):
            roles.plan(self.targets)


if __name__ == '__main__':
    unittest.main()
