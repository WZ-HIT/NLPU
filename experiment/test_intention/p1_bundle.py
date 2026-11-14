"""Build v3 search views from immutable v2 evidence, without AST/model generation."""
import argparse
import json
from pathlib import Path
import shutil

from . import search_view as search
from .compact import OUTPUT

FORMAT = 'compact-intention-v3'
README = '''# Existing tests: short search with evidence lookup

Use PR title/body and public base only. These records describe existing behavior;
they do not say that a test must change. Model interpretations remain distinct
from saved static candidates. Missing semantics do not imply irrelevance.

    python3 test-intentions/read.py search --query symbol
    python3 test-intentions/read.py search --query old_api --query mock --mode and
    python3 test-intentions/read.py search --query tests/example.py --search-field path
    python3 test-intentions/read.py search --query symbol --cursor 'NEXT_CURSOR'
    python3 test-intentions/read.py match 'TEST_ID' --ref '/facts/calls/0/expression'
    python3 test-intentions/read.py show 'TEST_ID'
    python3 test-intentions/read.py scenarios 'TEST_ID'
    python3 test-intentions/read.py detail 'TEST_ID' --field summary
    python3 test-intentions/read.py facts 'TEST_ID' --field assertions
    python3 test-intentions/read.py contexts 'TEST_ID'
    python3 test-intentions/read.py source 'TEST_ID'

Repeated --query clauses use literal case-insensitive OR by default; --mode and
requires every clause somewhere in the selected fields. Default searches all
tests, including STATIC_FALLBACK. Empty query browses all tests. Optional --file
is an exact path; file membership and neighbors must not gate the candidate set.
Existing facts, semantic values, identities, paths, owners and direct saved
dependencies are searchable; field-contract.json lists fields and missing states.
No new source facts or relationship expansion were generated in this version.

search returns a short goal, status, score and one faithful match with field,
ref and raw character offsets. More fields may match. Use match with that ID/ref
for the original value and its full associated scenario or static fact; use
source to verify relevant original code. Truncated summaries are marked.

Search defaults to deterministic field-bm25-v1 ordering; --sort id or tfidf are
available. Relevance does not establish update necessity. Search continuation
uses next_cursor with identical query/options. Changed evidence/index/reader or
query rejects stale cursors. --offset remains for show/match and evidence views.
Each page defaults to 6000 UTF-8 bytes and 8 units, capped at 12000 bytes and 25
units. Exceptionally long records are numbered JSON text fragments; collect all
before interpretation. matched_test_count counts tests; returned_unit_count
counts records/fragments; returned_complete_test_count excludes fragments.

Do not dump binary databases, manifests, whole graphs or all summaries. Start
with search and read specific evidence. All base tests remain independently
searchable. Do not add a production-localization stage.
'''


def verify_parent(root):
    manifest = json.loads((root/'manifest.json').read_text())
    if manifest['representation_format'] != 'compact-intention-v2':
        raise ValueError('Expected immutable v2 parent')
    expected = set(manifest['files']) | {'manifest.json'}
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != expected or any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('Parent inventory changed')
    for name, digest in manifest['files'].items():
        if search.sha(root/name) != digest:
            raise ValueError('Parent hash changed: '+name)
    return manifest


def export(source, destination):
    parent = verify_parent(source)
    if destination.exists():
        raise ValueError('Refusing to overwrite a bundle')
    shutil.copytree(source, destination)
    (destination/'manifest.json').unlink()
    for src, name in (('reader.py', 'read.py'), ('search_view.py', 'search_view.py')):
        shutil.copyfile(Path(__file__).with_name(src), destination/name)
    coverage = search.build_index(destination/'.evidence.sqlite3', destination/'.search.sqlite3')
    if search.sha(source/'.evidence.sqlite3') != search.sha(destination/'.evidence.sqlite3'):
        raise ValueError('Evidence changed')
    contract = {'version': search.VERSION, 'fields': list(search.FIELDS), 'weights': search.WEIGHTS,
                'matching': 'Unicode casefold literal substrings; explicit OR/AND',
                'facts': 'saved values only; line/status/admin keys excluded from matching',
                'missing': {'GENERATED': 'semantic interpretation saved; individual fields may be empty',
                            'STATIC_FALLBACK': 'semantic description missing, saved static facts still searchable',
                            'empty_or_missing': 'no indexed nonempty text; does not mean irrelevant or absent behavior'},
                'not_saved': ['full import table', 'full inheritance graph', 'resource lifetime'],
                'owner': 'deterministically split existing qualified ID; no runtime resolution',
                'coverage': coverage}
    (destination/'field-contract.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2)+'\n')
    (destination/'README.md').write_text(README)
    (destination/'.rgignore').write_text('.evidence.sqlite3\n.search.sqlite3\nread.py\nsearch_view.py\nmanifest.json\n')
    manifest = dict(parent, representation_format=FORMAT, search_version=search.VERSION,
                    parent_manifest_sha256=search.sha(source/'manifest.json'),
                    parent_evidence_sha256=search.sha(source/'.evidence.sqlite3'))
    manifest['files'] = {p.relative_to(destination).as_posix(): search.sha(p)
                         for p in sorted(destination.rglob('*')) if p.is_file()}
    (destination/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return {'base_sha': parent['base_sha'], 'coverage': coverage,
            'manifest_sha256': search.sha(destination/'manifest.json'),
            'bytes': sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=OUTPUT/'representations')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = []
    for source in sorted(args.source.iterdir()):
        if (source/'manifest.json').is_file():
            result = export(source, args.output/'representations'/source.name)
            results.append(result)
            print(json.dumps({'base': source.name, 'tests': result['coverage']['tests']}), flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'bundles.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
