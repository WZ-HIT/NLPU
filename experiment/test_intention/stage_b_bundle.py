"""Versioned additive B publication; does not mutate A or invoke a model."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

from . import search_view as search, sensitivity_view

ROOT = Path('/data2/wangzuohit/NLPU-experiments/test-intention')
OUTPUT = ROOT/'stage-b-20261109-v1'
PARENT = ROOT/'stage-a-codex-20261104-v1/publication-v1/representations'
BASELINES = Path('/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/batch/baselines')
FORMAT = 'compact-intention-v6'
GUIDE = '''

## Source sensitivity navigation (optional; saved facts only)

    python3 test-intentions/read.py sensitive 'TEST_ID'
    python3 test-intentions/read.py sensitive 'TEST_ID' --offset NEXT_OFFSET
    python3 test-intentions/read.py point 'TEST_ID' --ref '/facts/calls/0'

The default show/search cards are unchanged. sensitive lists bounded previews of
calls, assigned values, assertions, conditions, mocks, decorators, annotations,
imports, inheritance and associated-definition calls. String/configuration values
remain inside their original expressions; there is no new inferred relation or
constructor classifier. point expands exactly one associated fact with its saved
source location, file hash and uncertainty. Follow next_offset for fragments.

Original P1 facts identify a start line, not an exact multiline syntax span.
Normalized expressions can differ from source formatting; point shows the anchor
line and the original fact, and source TEST_ID reads the whole method when needed.
P2 facts preserve their existing UTF-8 column span. Scope may be associated context
rather than this method; the source path and saved scope disclose that distinction.
Neither association, inheritance nor a call proves runtime execution or a need to
update. No new facts, semantic generation, ranking weights or relation expansion
are introduced. Missing facts and truncated extraction remain unknown, not negative
evidence. Every listed point can be expanded by its own ref; changed base source
is rejected. These commands use the same 6,000/12,000 byte paging limits.
'''


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def checked(root):
    if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('Unsafe bundle path')
    manifest = json.loads((root/'manifest.json').read_text())
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(manifest['files'])|{'manifest.json'}:
        raise ValueError('Bundle inventory changed')
    for name, digest in manifest['files'].items():
        if search.sha(root/name)!=digest:
            raise ValueError('Bundle changed: '+name)
    return manifest


def export(source, destination):
    manifest = checked(source)
    if manifest['representation_format']!='compact-intention-v5':
        raise ValueError('Expected completed A v5 material')
    if destination.exists():
        raise ValueError('Refusing overwrite')
    shutil.copytree(source,destination)
    shutil.copyfile(source/'read.py',destination/'legacy_read.py')
    shutil.copyfile(Path(__file__).with_name('stage_b_reader.py'),destination/'read.py')
    shutil.copyfile(Path(sensitivity_view.__file__),destination/'sensitivity_view.py')
    (destination/'README.md').write_text((source/'README.md').read_text()+GUIDE)
    (destination/'.rgignore').write_text((source/'.rgignore').read_text()+'legacy_read.py\nsensitivity_view.py\n')
    contract = json.loads((source/'field-contract.json').read_text())
    contract['sensitivity'] = {'version':sensitivity_view.VERSION,'new_extraction':False,
        'direct':sensitivity_view.DIRECT,'associated':sensitivity_view.ASSOCIATED,
        'search_and_default_cards':'unchanged','reference':'original fact JSON pointer',
        'direct_source_extent':'start line only; multiline extent unknown'}
    write(destination/'field-contract.json',contract)
    preserved = {name:digest for name,digest in manifest['files'].items()
                 if name not in {'read.py','README.md','.rgignore','field-contract.json'}}
    if any(search.sha(destination/name)!=digest for name,digest in preserved.items()):
        raise ValueError('Existing evidence/card/index/ranking changed')
    new = dict(manifest,representation_format=FORMAT,sensitivity_version=sensitivity_view.VERSION,
               stage_b_parent_manifest_sha256=search.sha(source/'manifest.json'))
    new['files']={p.relative_to(destination).as_posix():search.sha(p)
                  for p in sorted(destination.rglob('*')) if p.is_file() and p.name!='manifest.json'}
    write(destination/'manifest.json',new)
    checked(destination)
    return {'base_sha':manifest['base_sha'],'test_count':manifest['test_count'],
            'manifest_sha256':search.sha(destination/'manifest.json'),
            'parent_manifest_sha256':search.sha(source/'manifest.json'),
            'preserved_files':len(preserved),'new_extraction':False,'search_index_unchanged':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args()
    if (args.output/'bundles.json').exists():
        raise ValueError('Publication already sealed')
    rows=[]
    for source in sorted(PARENT.iterdir()):
        rows.append(export(source,args.output/'representations'/source.name))
        print(json.dumps(rows[-1]),flush=True)
    write(args.output/'bundles.json',{'format':FORMAT,'bases':rows,'model_calls':0})


if __name__=='__main__':
    main()
