#!/usr/bin/env bash
# Run inside the pinned baseline container, never in a Scrapy workspace.
# Inputs: /inputs/uv.tar.gz, /inputs/build-requirements.in.
# Output: dedicated /output bind mount; /tmp and HOME must be private.
# resolve requires network; build must run in a fresh --network=none container.
set -euo pipefail
python - <<'PY'
import hashlib, sys, tarfile
assert sys.version_info[:3] == (3, 11, 15)
with open('/inputs/uv.tar.gz', 'rb') as stream:
    assert hashlib.file_digest(stream, 'sha256').hexdigest() == '173d95a0c32d18c896c46ba6fafbf3cf9c14ab74b033f81b76c883ef492a976b'
with tarfile.open('/inputs/uv.tar.gz') as archive:
    archive.extractall('/tmp/uv-runtime', filter='data')
PY
export PATH=/tmp/uv-runtime/uv-x86_64-unknown-linux-gnu:/usr/local/bin:/usr/bin:/bin
export UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_DOWNLOADS=never UV_NO_CONFIG=1
export PIP_CONFIG_FILE=/dev/null PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
test "$(uv --version | cut -d ' ' -f 1-2)" = 'uv 0.12.10'
uv --version
case "${1:-}" in
  resolve)
    test ! -e /output/source.tar.gz
    git init -q /tmp/spec-kit-source
    git -C /tmp/spec-kit-source fetch --depth=1 --no-tags https://github.com/github/spec-kit.git cb610277fdea781fcfa83d20522c2db37c94068d
    git -C /tmp/spec-kit-source checkout -q --detach FETCH_HEAD
    test "$(git -C /tmp/spec-kit-source rev-parse HEAD)" = cb610277fdea781fcfa83d20522c2db37c94068d
    test "$(git -C /tmp/spec-kit-source rev-list --count HEAD)" = 1
    test -z "$(git -C /tmp/spec-kit-source status --porcelain)"
    test ! -e /tmp/spec-kit-source/.gitmodules
    python - <<'PY'
import pathlib, tomllib
project = tomllib.loads(pathlib.Path('/tmp/spec-kit-source/pyproject.toml').read_text())
assert project['project']['version'] == '1.0.4'
assert project['build-system'] == {'requires': ['hatchling'], 'build-backend': 'hatchling.build'}
assert len(project['project']['dependencies']) == 9
PY
    git -C /tmp/spec-kit-source archive --format=tar.gz --prefix=source/ --output=/output/source.tar.gz HEAD
    uv pip compile /inputs/build-requirements.in --python /usr/local/bin/python --default-index https://pypi.org/simple --generate-hashes --no-build --output-file /output/build-requirements.txt
    uv pip compile /tmp/spec-kit-source/pyproject.toml --python /usr/local/bin/python --default-index https://pypi.org/simple --generate-hashes --no-build --output-file /output/runtime-requirements.txt
    mkdir /output/wheels
    python -m pip download --require-hashes --only-binary=:all: --index-url https://pypi.org/simple --dest /output/wheels -r /output/build-requirements.txt -r /output/runtime-requirements.txt
    ;;
  build)
    test ! -e /output/dist
    python - <<'PY'
import tarfile
with tarfile.open('/output/source.tar.gz') as archive:
    archive.extractall('/tmp/build-source', filter='data')
PY
    uv venv --python /usr/local/bin/python /tmp/build-env
    uv pip sync /output/build-requirements.txt --python /tmp/build-env/bin/python --no-index --find-links /output/wheels --require-hashes --no-build
    export SOURCE_DATE_EPOCH=315532800 PYTHONHASHSEED=0 TZ=UTC
    cd /tmp/build-source/source
    /tmp/build-env/bin/python -m hatchling build -t wheel -d /output/dist
    /tmp/build-env/bin/python -m hatchling build -t wheel -d /tmp/rebuild
    cmp /output/dist/specify_cli-1.0.4-py3-none-any.whl /tmp/rebuild/specify_cli-1.0.4-py3-none-any.whl
    printf 'specify-cli==1.0.4\n' | uv pip compile - --python /usr/local/bin/python --no-index --find-links /output/dist --find-links /output/wheels --generate-hashes --no-build --output-file /output/install-requirements.txt
    python - <<'PY'
import email, hashlib, json, pathlib, zipfile
root = pathlib.Path('/output')
wheel = root / 'dist/specify_cli-1.0.4-py3-none-any.whl'
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    metadata = email.message_from_bytes(archive.read('specify_cli-1.0.4.dist-info/METADATA'))
    assert metadata['Name'] == 'specify-cli' and metadata['Version'] == '1.0.4'
    for part in ('templates/', 'commands/', 'scripts/bash/', 'extensions/', 'workflows/', 'presets/', 'bundles/'):
        assert any(name.startswith('specify_cli/core_pack/' + part) for name in names), part
    print('Spec Kit wheel metadata and bundled assets: PASS')
artifacts = []
for path in sorted(root.rglob('*')):
    if path.is_file():
        artifacts.append({'path': str(path.relative_to(root)), 'size_bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
record = {'source_commit': 'cb610277fdea781fcfa83d20522c2db37c94068d', 'python': '3.11.15', 'uv': '0.12.10', 'source_date_epoch': 315532800, 'offline_build': True, 'repeat_build_identical': True, 'runtime_execution': 'not performed', 'artifacts': artifacts}
(root / 'artifact-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
print('Offline repeat build identical; artifact inventory generated.')
PY
    ;;
  *) printf 'Usage: bash resolve-and-build.sh {resolve|build}\n' >&2; exit 2 ;;
esac
