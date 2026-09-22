"""Plan/apply the existing Azure network and storage baseline; never bootstrap a VM.

Use a dedicated, externally protected IaC WIF service connection. A plan artifact
is review evidence, not a cryptographic signature or an Azure authorization grant.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'deploy/azure'
SUBSCRIPTION = 'afe8ae0d-d866-47a9-bc56-e1f4475e6cc6'
ENVIRONMENTS = {
    'staging': ('rg-cyberwatch-staging-swe', 'cyberwatch-staging',
                'cyberwatch-staging-afe8ae-20260922'),
    'prod': ('rg-cyberwatch-yamk-swe', 'cyberwatch-yamk',
             'cyberwatch-yamk-afe8ae-20260908'),
}
NETWORK_API = '2024-05-01'
STORAGE_API = '2023-05-01'
TEMPLATE = HERE / 'steady-state.bicep'
FILES = ('template.json', 'parameters.json', 'what-if.json')
MAX_JSON = 2 * 1024 * 1024


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    if path.is_symlink():
        raise ValueError('Refusing a symlink in the IaC artifact')
    path.write_bytes(encoded(value))


def read_json(path):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_JSON:
        raise ValueError('IaC evidence must be a bounded regular JSON file')
    return json.loads(path.read_bytes())


def az(*args):
    executable = shutil.which('az')
    if not executable:
        raise RuntimeError('Azure CLI is required')
    path = Path(executable)
    command = ([str(path.parent.parent / 'python.exe'), '-IBm', 'azure.cli']
               if path.suffix.lower() in {'.cmd', '.bat'} else [str(path)])
    result = subprocess.run(command + list(args) + ['--only-show-errors', '-o', 'json'],
                            capture_output=True, text=True, timeout=1200)
    if result.returncode:
        # No unfiltered provider response is uploaded as an artifact or CI log.
        raise RuntimeError('Azure IaC operation failed; inspect Azure activity/deployment logs with an authorized account')
    return json.loads(result.stdout) if result.stdout.strip() else None


def checkout_commit():
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    commit = result.stdout.strip()
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('Expected a full Git commit SHA')
    if os.environ.get('BUILD_SOURCEVERSION', commit) != commit:
        raise ValueError('Checkout differs from the pipeline source commit')
    # Source hashes are bound below too, but do not label dirty files as committed.
    paths = ['deploy/azure/steady-state.bicep', 'deploy/azure/targets.json', 'tools/ado_infra.py']
    status = subprocess.run(['git', 'status', '--porcelain', '--', *paths], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    if status.stdout.strip():
        raise ValueError('Commit the IaC template, targets and helper before planning')
    return commit


def require_apply_branch():
    if os.environ.get('BUILD_SOURCEBRANCH') != 'refs/heads/main':
        raise ValueError('Infrastructure apply requires a pipeline checkout of the protected main branch')


def target(environment):
    targets = read_json(HERE / 'targets.json')
    if environment not in ENVIRONMENTS or targets.get('subscription') != SUBSCRIPTION:
        raise ValueError('Unexpected IaC environment or subscription')
    value = targets[environment]
    group, vm, dns = ENVIRONMENTS[environment]
    if (value.get('resourceGroup') != group or value.get('vm') != vm
            or value.get('container') != 'artifacts'
            or value.get('fqdn') != dns + '.swedencentral.cloudapp.azure.com'
            or not isinstance(value.get('storageAccount'), str)
            or not re.fullmatch('[a-z0-9]{3,24}', value['storageAccount'])):
        raise ValueError('The fixed environment mapping is incomplete or changed; review bootstrap first')
    return dict(value, subscription=SUBSCRIPTION, dnsLabel=dns, environment=environment)


def resources(value):
    base = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{value['resourceGroup']}/providers/"
    prefix, storage = value['vm'], value['storageAccount']
    definitions = [
        ('Microsoft.Network/networkSecurityGroups', prefix + '-nsg', NETWORK_API),
        ('Microsoft.Network/virtualNetworks', prefix + '-vnet', NETWORK_API),
        ('Microsoft.Network/publicIPAddresses', prefix + '-ip', NETWORK_API),
        ('Microsoft.Network/networkInterfaces', prefix + '-nic', NETWORK_API),
        ('Microsoft.Compute/disks', prefix + '-data', '2024-03-02'),
        ('Microsoft.Storage/storageAccounts', storage, STORAGE_API),
        ('Microsoft.Storage/storageAccounts/blobServices', storage + '/default', STORAGE_API),
        ('Microsoft.Storage/storageAccounts/blobServices/containers', storage + '/default/artifacts', STORAGE_API),
        ('Microsoft.Storage/storageAccounts/managementPolicies', storage + '/default', STORAGE_API),
    ]
    result = {}
    for resource_type, name, api in definitions:
        type_parts, name_parts = resource_type.split('/'), name.split('/')
        suffix = type_parts[0] + '/' + '/'.join(part for pair in zip(type_parts[1:], name_parts) for part in pair)
        identifier = (base + suffix).lower()
        result[identifier] = {'type': resource_type, 'api': api}
    return result


def verify_existing(value):
    account = az('account', 'show')
    if account.get('id') != SUBSCRIPTION or account.get('state') != 'Enabled':
        raise ValueError('Select the enabled LapinAMK-Student-YAMKDevops-SANDBOX subscription first')
    group = az('group', 'show', '--name', value['resourceGroup'], '--subscription', SUBSCRIPTION)
    expected_group = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{value['resourceGroup']}".lower()
    if (group.get('id', '').lower() != expected_group or group.get('location') != 'swedencentral'
            or (group.get('tags') or {}).get('project') != 'Cyberwatch'):
        raise ValueError('Existing resource group identity, location or ownership tag differs')
    # The VM is read for provenance only; it is never written by this template.
    vm = az('vm', 'show', '--resource-group', value['resourceGroup'], '--name', value['vm'],
            '--subscription', SUBSCRIPTION)
    if vm.get('id', '').lower() != expected_group + '/providers/microsoft.compute/virtualmachines/' + value['vm']:
        raise ValueError('The existing VM does not match the selected environment')
    for identifier, definition in resources(value).items():
        current = az('rest', '--method', 'get', '--url',
                     'https://management.azure.com' + identifier + '?api-version=' + definition['api'])
        if current.get('id', '').lower() != identifier:
            raise ValueError('A required existing resource is missing or resolves outside the environment')


def parameters(value):
    return {'$schema': 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#',
            'contentVersion': '1.0.0.0', 'parameters': {
                'location': {'value': 'swedencentral'}, 'namePrefix': {'value': value['vm']},
                'dnsLabel': {'value': value['dnsLabel']},
                'storageAccountName': {'value': value['storageAccount']}}}


def compile_template(destination, value):
    az('bicep', 'build', '--file', str(TEMPLATE), '--outfile', str(destination))
    template = read_json(destination)
    declared = template.get('resources')
    expected = Counter(item['type'].lower() for item in resources(value).values())
    if (not isinstance(declared, list)
            or Counter(item.get('type', '').lower() for item in declared) != expected
            or any('resources' in item or 'condition' in item for item in declared)
            or template.get('outputs')):
        raise ValueError('Steady-state template resource types differ from the nine audited resources')
    write_json(destination, template)
    return template


def permitted_path(resource_type, path):
    # Fail closed on VM-like, address, DNS, disk size/createOption and encryption
    # changes. Bootstrap/migrations belong to a separately reviewed procedure.
    if path == 'tags' or path.startswith('tags.') or path.startswith('tags['):
        return True
    prefixes = {
        'microsoft.network/networksecuritygroups': ('properties.securityRules',),
        'microsoft.network/publicipaddresses': ('properties.idleTimeoutInMinutes',),
        'microsoft.storage/storageaccounts': (
            'properties.minimumTlsVersion', 'properties.supportsHttpsTrafficOnly',
            'properties.allowBlobPublicAccess', 'properties.allowCrossTenantReplication',
            'properties.publicNetworkAccess', 'properties.allowSharedKeyAccess'),
        'microsoft.storage/storageaccounts/blobservices/containers': ('properties.publicAccess',),
        'microsoft.storage/storageaccounts/managementpolicies': ('properties.policy',),
    }
    return any(path == prefix or path.startswith(prefix + '.') or path.startswith(prefix + '[')
               for prefix in prefixes.get(resource_type.lower(), ()))


def clean_delta(delta, resource_type, parent=''):
    if not isinstance(delta, dict) or not isinstance(delta.get('path'), str):
        raise ValueError('Unsupported what-if property delta')
    path = delta['path']
    full_path = path if not parent or path.startswith(parent) else parent + ('' if path.startswith('[') else '.') + path
    kind = delta.get('propertyChangeType')
    if kind not in {'Create', 'Delete', 'Modify', 'Array'} or not permitted_path(resource_type, full_path):
        raise ValueError('Replacement-sensitive or unreviewed property change: ' + full_path)
    allowed = {'path', 'propertyChangeType', 'before', 'after', 'children'}
    if set(delta) - allowed:
        raise ValueError('Unsupported what-if delta fields')
    cleaned = {'path': path, 'propertyChangeType': kind}
    # Only values for the explicitly nonsecret control-plane paths above survive.
    for key in ('before', 'after'):
        if key in delta:
            cleaned[key] = delta[key]
    if delta.get('children') is not None:
        if not isinstance(delta['children'], list):
            raise ValueError('Unsupported what-if nested delta')
        cleaned['children'] = sorted((clean_delta(item, resource_type, full_path) for item in delta['children']), key=encoded)
    return cleaned


def reviewed_changes(report, value):
    expected = resources(value)
    if (report.get('status') != 'Succeeded' or not isinstance(report.get('changes'), list)
            or report.get('error') or report.get('nextLink') or report.get('potentialChanges')):
        raise ValueError('ARM what-if did not produce a successful complete report')
    seen, result = set(), []
    for change in report['changes']:
        identifier = change.get('resourceId', '').lower()
        kind = change.get('changeType')
        if identifier not in expected or identifier in seen:
            raise ValueError('What-if contains an unexpected or duplicate resource ID')
        seen.add(identifier)
        if kind not in {'NoChange', 'Modify'} or change.get('unsupportedReason'):
            raise ValueError('Steady-state IaC refuses creates, deletes, ignored or unsupported resource changes')
        deltas = change.get('delta') or []
        if not isinstance(deltas, list) or (kind == 'Modify' and not deltas) or (kind == 'NoChange' and deltas):
            raise ValueError('What-if change has no reviewable property delta')
        result.append({'resourceId': identifier, 'changeType': kind,
                       'delta': sorted((clean_delta(item, expected[identifier]['type']) for item in deltas), key=encoded)})
    if seen != set(expected):
        raise ValueError('What-if omitted a required resource; do not silently recreate or ignore resources')
    return {'status': 'Succeeded', 'changes': sorted(result, key=lambda item: item['resourceId'])}


def what_if(value, artifact):
    report = az('deployment', 'group', 'what-if', '--subscription', SUBSCRIPTION,
                '--resource-group', value['resourceGroup'], '--mode', 'Incremental',
                '--template-file', str(artifact / 'template.json'),
                '--parameters', '@' + str(artifact / 'parameters.json'), '--no-pretty-print',
                '--exclude-change-types', 'Ignore')
    # Ignore refers to unmanaged resources outside this template (VM/identities).
    # Any omitted managed resource is caught by the complete nine-ID check above.
    return reviewed_changes(report, value)


def source_hashes():
    return {str(path.relative_to(ROOT)).replace('\\', '/'): digest(path.read_bytes())
            for path in (TEMPLATE, HERE / 'targets.json', Path(__file__).resolve())}


def plan(value, artifact, commit):
    if artifact.is_symlink() or (artifact.exists() and any(artifact.iterdir())):
        raise ValueError('Plan artifact directory must be new or empty')
    artifact.mkdir(parents=True, exist_ok=True)
    verify_existing(value)
    compile_template(artifact / 'template.json', value)
    write_json(artifact / 'parameters.json', parameters(value))
    changes = what_if(value, artifact)
    write_json(artifact / 'what-if.json', changes)
    manifest = {'schema': 1, 'commit': commit, 'environment': value['environment'],
                'subscription': SUBSCRIPTION, 'resourceGroup': value['resourceGroup'],
                'buildId': os.environ.get('BUILD_BUILDID', 'local'), 'mode': 'Incremental',
                'sources': source_hashes(),
                'files': {name: digest((artifact / name).read_bytes()) for name in FILES}}
    write_json(artifact / 'plan.json', manifest)
    print(json.dumps({'status': 'planned', 'commit': commit, 'environment': value['environment'],
                      'modifiedResources': sum(item['changeType'] == 'Modify' for item in changes['changes']),
                      'artifact': str(artifact)}, indent=2))


def validate_artifact(value, artifact, commit):
    if artifact.is_symlink() or not artifact.is_dir():
        raise ValueError('Expected an ordinary IaC artifact directory')
    manifest = read_json(artifact / 'plan.json')
    required = {'schema': 1, 'commit': commit, 'environment': value['environment'],
                'subscription': SUBSCRIPTION, 'resourceGroup': value['resourceGroup'], 'mode': 'Incremental'}
    if any(manifest.get(key) != item for key, item in required.items()):
        raise ValueError('Plan belongs to another environment, commit, subscription or mode')
    if manifest.get('sources') != source_hashes() or set(manifest.get('files', {})) != set(FILES):
        raise ValueError('Plan source hashes or artifact file set differs from the checkout')
    for name in FILES:
        read_json(artifact / name)
        if digest((artifact / name).read_bytes()) != manifest['files'][name]:
            raise ValueError('Plan artifact hash mismatch')
    if read_json(artifact / 'parameters.json') != parameters(value):
        raise ValueError('Plan parameters differ from the fixed selected environment')
    saved = read_json(artifact / 'what-if.json')
    if reviewed_changes(saved, value) != saved:
        raise ValueError('Plan changes are not the canonical reviewed report')
    # Hashes alone are not signatures. Recompile the same committed source so a
    # substituted template plus an edited manifest is rejected before Azure writes.
    with tempfile.TemporaryDirectory(prefix='cyberwatch-iac-') as directory:
        rebuilt = Path(directory) / 'template.json'
        compile_template(rebuilt, value)
        if digest(rebuilt.read_bytes()) != manifest['files']['template.json']:
            raise ValueError('Compiled template differs from the reviewed committed source; use the same Bicep version')
    return saved


def apply(value, artifact, commit):
    saved = validate_artifact(value, artifact, commit)
    verify_existing(value)
    current = what_if(value, artifact)
    if current != saved:
        raise ValueError('Infrastructure changed since review; create and approve a new plan')
    if not any(change['changeType'] == 'Modify' for change in current['changes']):
        print('Reviewed baseline is already current; no Azure deployment was submitted.')
        return
    result = az('deployment', 'group', 'create', '--subscription', SUBSCRIPTION,
                '--resource-group', value['resourceGroup'], '--mode', 'Incremental',
                '--name', 'cyberwatch-steady-' + commit[:12],
                '--template-file', str(artifact / 'template.json'),
                '--parameters', '@' + str(artifact / 'parameters.json'))
    if result.get('properties', {}).get('provisioningState') != 'Succeeded':
        raise RuntimeError('Azure did not confirm a successful infrastructure deployment')
    print(json.dumps({'status': 'applied', 'environment': value['environment'], 'commit': commit,
                      'deploymentId': result.get('id')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'apply'))
    parser.add_argument('--environment', required=True, choices=tuple(ENVIRONMENTS))
    parser.add_argument('--artifact', type=Path, required=True)
    args = parser.parse_args()
    value, commit = target(args.environment), checkout_commit()
    if args.operation == 'apply':
        require_apply_branch()
    (plan if args.operation == 'plan' else apply)(value, args.artifact.absolute(), commit)


if __name__ == '__main__':
    main()
