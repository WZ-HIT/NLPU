"""D input reader under actual readonly sandbox; no provider connection/credential."""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import runpy
import sqlite3
import sys


def inside(method,planning):
    sys.dont_write_bytecode=True;sys.path.insert(0,'/run/sdd-public')
    from probe import probe
    result=probe(method,planning);assert result['pass'],result
    assert not Path('/run/secrets/deepseek-api-key').exists()
    assert not Path('/workspace/test-traces').exists()
    assert not Path('/data2/wangzuohit/NLPU-experiments/test-intention').exists()
    root=Path('/workspace/test-intentions');sys.path.insert(0,str(root))
    main=runpy.run_path(str(root/'read.py'))['main']
    def call(argv):
        stream=io.StringIO()
        with redirect_stdout(stream):code=main(argv,root=root,repository=Path('/workspace'))
        assert code==0,stream.getvalue()
        assert len(stream.getvalue().encode())<=6000
        return json.loads(stream.getvalue())
    with sqlite3.connect((root/'.dynamic.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        identity=db.execute("SELECT id FROM methods WHERE status='complete' AND shallow_count>0 ORDER BY id LIMIT 1").fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM coverage c JOIN methods m ON c.test_id=m.id WHERE m.status!='complete'").fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM methods WHERE status!='complete' AND graph IS NOT NULL").fetchone()[0]==0
    assert call(['search','--query',identity,'--limit','1'])['items'][0]['id']==identity
    for command in ['show','source','coverage','trace','shared']:
        value=call([command,identity,'--limit','1'])
        if command!='shared':assert value['items']
    assert not (root/'__pycache__').exists()
    try:(root/'forbidden-write').write_text('bad')
    except OSError:pass
    else:raise AssertionError('D material writable')
    result.update(group='D',reader_checks=6,complete_only=True,readonly=True,
                  network='none',model_requests=0,model_credentials=False)
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--inside',action='store_true')
    parser.add_argument('--group');parser.add_argument('--method');parser.add_argument('--planning')
    args=parser.parse_args();inside(args.method,args.planning)
