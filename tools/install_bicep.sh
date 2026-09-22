#!/usr/bin/env bash
set -euo pipefail
version=${1:?Supply the reviewed Bicep version, including v}
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 2
# An already-installed version makes `az bicep install` return before changing
# this setting. Explicitly prevent CI from selecting another binary on PATH.
az config set bicep.use_binary_from_path=false
az bicep install --version "$version"
actual=$(az bicep version)
[[ "$actual" == "Bicep CLI version ${version#v} ("* ]] || {
  echo 'Azure CLI did not select the reviewed Bicep compiler.' >&2
  exit 1
}
printf '%s\n' "$actual"
