param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('what-if','infra','bundle','install','credentials')]
    [string]$Action,
    [string]$SubscriptionId = 'afe8ae0d-d866-47a9-bc56-e1f4475e6cc6',
    [string]$ResourceGroup = 'rg-cyberwatch-yamk-swe',
    [string]$Location = 'swedencentral',
    [string]$NamePrefix = 'cyberwatch-yamk',
    [string]$DnsLabel = 'cyberwatch-yamk-afe8ae-20260908',
    [string]$Image = 'cyberwatch-size-optimized:local',
    [string]$ImageArchive = '',
    [string]$ImageConfigId = '',
    [string]$SecretsDir = '',
    [string]$OrgTags = ''
)
$ErrorActionPreference = 'Stop'
$arguments = @((Join-Path $PSScriptRoot 'deploy.py'), $Action,
    '--subscription-id', $SubscriptionId, '--resource-group', $ResourceGroup,
    '--location', $Location, '--name-prefix', $NamePrefix, '--dns-label', $DnsLabel,
    '--image', $Image)
if ($SecretsDir) { $arguments += @('--secrets-dir', $SecretsDir) }
if ($OrgTags) { $arguments += @('--org-tags', $OrgTags) }
if ($ImageArchive) { $arguments += @('--image-archive', $ImageArchive) }
if ($ImageConfigId) { $arguments += @('--image-config-id', $ImageConfigId) }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "Azure deployment step failed with exit code $LASTEXITCODE" }
