"""Print the exact resource-scoped RBAC plan; --apply requires an authorized Azure admin.

Run only after the named identities and staging resources have been provisioned.
This tool never grants subscription-wide access or creates application credentials.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
ROLES = {
    'Virtual Machine Contributor': '9980e02c-c2be-4d73-94e8-173b1dc7cf3c',
    'Storage Blob Data Contributor': 'ba92f5b4-2d11-453d-a403-e96b0029c9fe',
    'Storage Blob Delegator': 'db58b8e5-c6ad-4a2a-8342-4190687cbf4a',
    'Network Contributor': '4d97b98b-1d4f-4787-a291-c67834d212e7',
    'Storage Account Contributor': '17d1049b-9a84-46fb-8f53-869881c3d3ab',
}


def az(*args):
    found = shutil.which('az')
    if not found:
        raise RuntimeError('Azure CLI is required')
    executable = Path(found)
    if executable.suffix.lower() == '.cmd':
        command = [str(executable.parent.parent / 'python.exe'), '-IBm', 'azure.cli']
    else:
        command = [str(executable)]
    result = subprocess.run(command + list(args) + ['--only-show-errors', '-o', 'json'],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('Azure operation failed; check the signed-in admin account and bootstrap prerequisites')
    return json.loads(result.stdout) if result.stdout.strip() else None


def plan(targets, purpose='application'):
    if purpose not in ('application', 'infrastructure', 'all'):
        raise ValueError('Unknown identity purpose')
    subscription = targets['subscription']
    if az('account', 'show')['id'] != subscription:
        raise ValueError('Select the explicitly configured subscription first')
    entries = []
    # Resolve and validate BOTH environments before writing any role assignment.
    for environment in ('staging', 'prod'):
        target = targets[environment]
        group = target['resourceGroup']
        if not isinstance(target['storageAccount'], str) or not re.fullmatch(r'[a-z0-9]{3,24}', target['storageAccount']):
            raise ValueError('Complete staging bootstrap and record its actual storageAccount first')
        base = f'/subscriptions/{subscription}/resourceGroups/{group}'
        vm = az('vm', 'show', '-g', group, '-n', target['vm'])['id']
        storage = az('storage', 'account', 'show', '-g', group, '-n', target['storageAccount'])['id']
        if (vm.lower() != (base + '/providers/Microsoft.Compute/virtualMachines/' + target['vm']).lower()
                or storage.lower() != (base + '/providers/Microsoft.Storage/storageAccounts/' + target['storageAccount']).lower()):
            raise ValueError('Resolved resource scope differs from the approved target')
        purposes = ('application', 'infrastructure') if purpose == 'all' else (purpose,)
        for selected in purposes:
            prefix = 'ado' if selected == 'application' else 'iac'
            identity_name = 'id-cyberwatch-' + prefix + '-' + environment
            identity = az('identity', 'show', '-g', group, '-n', identity_name)
            expected_identity = base + '/providers/Microsoft.ManagedIdentity/userAssignedIdentities/' + identity_name
            if identity['id'].lower() != expected_identity.lower():
                raise ValueError('Identity scope differs from the approved environment')
            if not re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}', identity.get('principalId', '')):
                raise ValueError('The managed identity has no valid principal ID')
            scopes = ({'Virtual Machine Contributor': vm,
                       'Storage Blob Data Contributor': storage + '/blobServices/default/containers/' + target['container'],
                       'Storage Blob Delegator': storage} if selected == 'application' else
                      {'Virtual Machine Contributor': base, 'Network Contributor': base, 'Storage Account Contributor': base})
            for name, scope in scopes.items():
                entries.append({'environment': environment, 'purpose': selected, 'identity': identity_name,
                                'principalId': identity['principalId'], 'role': name, 'roleId': ROLES[name], 'scope': scope})
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--purpose', choices=('application', 'infrastructure', 'all'), default='application')
    parser.add_argument('--apply', action='store_true', help='Create exactly the printed assignments using the current admin account')
    args = parser.parse_args()
    entries = plan(json.loads((ROOT / 'targets.json').read_text()), args.purpose)
    print(json.dumps(entries, indent=2))
    if args.apply:
        for entry in entries:
            existing = az('role', 'assignment', 'list', '--scope', entry['scope'])
            if any(role['principalId'] == entry['principalId'] and role['roleDefinitionId'].lower().endswith('/' + entry['roleId']) for role in existing):
                continue
            az('role', 'assignment', 'create', '--assignee-object-id', entry['principalId'],
               '--assignee-principal-type', 'ServicePrincipal', '--role', entry['roleId'], '--scope', entry['scope'])
        print(f'All {len(entries)} resource-scoped role assignments are present.')


if __name__ == '__main__':
    main()
