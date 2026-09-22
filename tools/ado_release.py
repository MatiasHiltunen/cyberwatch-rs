"""Build an immutable ARM64 artifact and promote only a staging-tested commit.

Azure authentication is supplied by AzureCLI@2 through workload identity federation.
Azure DevOps authentication is the job-scoped System.AccessToken, never a saved PAT.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ORG = 'https://dev.azure.com/DevOpsYAMKOpenDemo'
PROJECT = '01ad21b7-bfab-4043-bda1-f8a29e8ce4ec'
REPOSITORY = '369a248b-ba7a-4623-b4e8-a63a01c2b6cc'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'Release lookup redirects are forbidden', headers, fp)


def run(args, *, private=False):
    result = subprocess.run(args, capture_output=True, text=True, timeout=900)
    if result.returncode:
        raise RuntimeError('Command failed; sensitive output withheld' if private else result.stderr[-2000:])
    return result.stdout.strip()


def az(*args):
    # Neither command arguments containing SAS nor captured Azure responses are logged.
    return json.loads(run(['az', *args, '--only-show-errors', '-o', 'json'], private=True) or 'null')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def commit():
    value = run(['git', 'rev-parse', 'HEAD'])
    if not re.fullmatch(r'[a-f0-9]{40}', value):
        raise ValueError('Expected a full Git commit')
    if os.environ.get('BUILD_SOURCEVERSION', value) != value:
        raise ValueError('Checkout does not match the pipeline commit')
    return value


def package(output):
    revision = commit()
    image = 'cyberwatch-release:' + revision
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'image.tar'
    run(['docker', 'image', 'save', '--output', str(archive), image])
    with tarfile.open(archive) as stream:
        entries = json.load(stream.extractfile('manifest.json'))
        if len(entries) != 1 or entries[0].get('RepoTags') != [image]:
            raise ValueError('Release must contain exactly the expected image tag')
        config = stream.extractfile(entries[0]['Config']).read()
        parsed = json.loads(config)
        if parsed.get('architecture') != 'arm64' or parsed.get('os') != 'linux':
            raise ValueError('Azure release must be Linux ARM64')
    manifest = {'schema': 1, 'commit': revision, 'image': image, 'platform': 'linux/arm64',
                'imageConfigId': 'sha256:' + hashlib.sha256(config).hexdigest(),
                'archive': archive.name, 'bytes': archive.stat().st_size,
                'archiveSha256': sha(archive), 'buildId': os.environ.get('BUILD_BUILDID', 'local')}
    (output / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest))


def validate_release(directory, revision):
    manifest = json.loads((directory / 'release.json').read_text(encoding='utf-8'))
    if (manifest.get('schema') != 1 or manifest.get('commit') != revision
            or manifest.get('archive') != 'image.tar' or manifest.get('platform') != 'linux/arm64'
            or manifest.get('image') != 'cyberwatch-release:' + revision
            or not re.fullmatch(r'sha256:[a-f0-9]{64}', manifest.get('imageConfigId', ''))
            or not re.fullmatch(r'[a-f0-9]{64}', manifest.get('archiveSha256', ''))):
        raise ValueError('Release metadata does not match the selected commit/platform')
    archive = directory / 'image.tar'
    if (archive.is_symlink() or not archive.is_file() or not 0 < archive.stat().st_size < 1024**3
            or archive.stat().st_size != manifest.get('bytes') or sha(archive) != manifest['archiveSha256']):
        raise ValueError('Release archive is missing, modified or oversized')
    return manifest


def ado_get(path):
    token = os.environ.get('SYSTEM_ACCESSTOKEN')
    if not token:
        raise RuntimeError('The job-scoped System.AccessToken is required')
    url = f'{ORG}/{PROJECT}/_apis/{path}'
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token,
                                                 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, ValueError):
        raise RuntimeError('Azure DevOps release lookup failed; response withheld') from None


def staged_candidate(build, timeline, revision, definition):
    """A successful main build alone is insufficient: staging must actually have run."""
    return (build.get('sourceVersion') == revision and build.get('sourceBranch') == 'refs/heads/main'
            and build.get('status') == 'completed' and build.get('result') == 'succeeded'
            and str(build.get('definition', {}).get('id')) == str(definition)
            and build.get('repository', {}).get('id') == REPOSITORY
            and any(record.get('type') == 'Stage' and record.get('identifier') == 'DeployStaging'
                    and record.get('state') == 'completed' and record.get('result') == 'succeeded'
                    for record in timeline.get('records', [])))


def resolve():
    if not re.fullmatch(r'refs/tags/v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', os.environ.get('BUILD_SOURCEBRANCH', '')):
        raise ValueError('Production requires a version tag such as v0.4.2')
    revision = commit()
    definition = os.environ['SYSTEM_DEFINITIONID']
    if not definition.isdigit():
        raise ValueError('Invalid pipeline definition ID')
    query = urllib.parse.urlencode({'definitions': definition, 'branchName': 'refs/heads/main',
                                   'statusFilter': 'completed', 'resultFilter': 'succeeded',
                                   'queryOrder': 'finishTimeDescending', '$top': 100, 'api-version': '7.1'})
    for build in ado_get('build/builds?' + query)['value']:
        if build.get('sourceVersion') != revision:
            continue
        build_id = int(build['id'])
        timeline = ado_get(f'build/builds/{build_id}/timeline?api-version=7.1')
        if staged_candidate(build, timeline, revision, definition):
            print(f'Promoting staging-tested commit {revision} from build {build_id}')
            print(f'##vso[task.setvariable variable=validatedBuildId;isOutput=true]{build_id}')
            return
    raise RuntimeError('No successful staging deployment of this exact commit among the last 100 successful main builds')


def deploy(environment, directory):
    revision = commit()
    branch = os.environ.get('BUILD_SOURCEBRANCH', '')
    if environment == 'staging' and branch != 'refs/heads/main':
        raise ValueError('Staging deployment requires main')
    if environment == 'prod' and not re.fullmatch(r'refs/tags/v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', branch):
        raise ValueError('Production deployment requires a version tag')
    release = validate_release(directory, revision)
    targets = json.loads((ROOT / 'deploy/azure/targets.json').read_text())
    target = targets[environment]
    subscription = targets['subscription']
    if az('account', 'show')['id'] != subscription:
        raise ValueError('Service connection targets the wrong subscription')
    for key in ('resourceGroup', 'vm', 'storageAccount', 'container', 'fqdn'):
        if not isinstance(target.get(key), str) or not re.fullmatch(r'[a-zA-Z0-9.-]+', target[key]):
            raise ValueError('Environment bootstrap is incomplete: ' + key)
    account, container = target['storageAccount'], target['container']
    blob = f'releases/{revision}/{release["archiveSha256"]}.tar'
    common = ['--account-name', account, '--container-name', container, '--name', blob, '--auth-mode', 'login']
    if not az('storage', 'blob', 'exists', *common)['exists']:
        az('storage', 'blob', 'upload', *common, '--file', str(directory / 'image.tar'), '--overwrite', 'false')
    expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%MZ')
    sas = az('storage', 'blob', 'generate-sas', *common, '--as-user', '--permissions', 'r', '--expiry', expiry, '--https-only')
    url = f'https://{account}.blob.core.windows.net/{container}/{blob}?{sas}'
    # The VM script consumes the SAS from its private stdin configuration, not
    # curl/process arguments, a repository file or pipeline output.
    payload = dict(release, url=url)
    updater = (ROOT / 'deploy/azure/update_runtime.py').read_text(encoding='utf-8')
    script = "#!/bin/bash\nset -euo pipefail\numask 077\n" + \
        "work=$(mktemp -d /opt/cyberwatch-update.XXXXXX)\ntrap 'rm -rf \"$work\"' EXIT\n" + \
        "cat > \"$work/update.py\" <<'CYBERWATCH_PY'\n" + updater + "\nCYBERWATCH_PY\n" + \
        "python3 \"$work/update.py\" <<'CYBERWATCH_INPUT'\n" + json.dumps(payload) + "\nCYBERWATCH_INPUT\n"
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'update.sh'
        path.write_text(script, encoding='utf-8', newline='\n')
        path.chmod(0o600)
        response = az('vm', 'run-command', 'invoke', '-g', target['resourceGroup'], '-n', target['vm'],
                      '--command-id', 'RunShellScript', '--scripts', '@' + str(path))
    messages = '\n'.join(item.get('message', '') for item in response.get('value', []))
    expected = 'CYBERWATCH_DEPLOY_OK ' + revision + ' ' + release['imageConfigId']
    if expected not in messages:
        # Do not dump Run Command output: it can contain OS diagnostics.
        raise RuntimeError('VM update did not pass readiness; inspect the private VM deployment log and rollback state')
    print(json.dumps({'status': 'passed', 'environment': environment, 'commit': revision,
                      'imageConfigId': release['imageConfigId'], 'sourceBuildId': release['buildId']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('package').add_argument('--output', type=Path, required=True)
    commands.add_parser('resolve')
    deployment = commands.add_parser('deploy')
    deployment.add_argument('--environment', choices=['staging', 'prod'], required=True)
    deployment.add_argument('--artifact', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'package':
        package(args.output)
    elif args.action == 'resolve':
        resolve()
    else:
        deploy(args.environment, args.artifact)


if __name__ == '__main__':
    main()
