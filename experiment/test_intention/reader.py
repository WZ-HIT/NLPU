"""Read-only, bounded views over base-derived intentions. Python stdlib only."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def page(rows, offset=0, limit=8, max_bytes=6000):
    """Never silently discard a large record: return marked JSON text fragments."""
    max_bytes = max(4096, min(max_bytes, 12000))
    limit = max(1, min(limit, 25))
    pieces = []
    for number, row in enumerate(rows):
        text = encoded(row)
        if len(text.encode()) <= 2400:
            pieces.append(row)
        else:
            chunks = [text[i:i+300] for i in range(0, len(text), 300)]
            pieces.extend({'record': number, 'fragment': i, 'fragments': len(chunks),
                           'format': 'json-text-fragment', 'text': chunk}
                          for i, chunk in enumerate(chunks))
    selected = []
    for item in pieces[offset:offset+limit]:
        trial = {'items': [*selected, item], 'offset': offset, 'next_offset': offset+len(selected)+1,
                 'page_units': 'records or explicitly marked fragments', 'total_units': len(pieces)}
        if len(encoded(trial).encode())+1 > max_bytes:
            break
        selected.append(item)
    next_offset = offset+len(selected)
    return {'items': selected, 'offset': offset,
            'next_offset': next_offset if next_offset < len(pieces) else None,
            'page_units': 'records or explicitly marked fragments', 'total_units': len(pieces)}


def connect(root):
    db = root / '.evidence.sqlite3'
    if db.is_symlink() or not db.is_file():
        raise ValueError('Evidence database missing or unsafe')
    return sqlite3.connect(db.resolve().as_uri()+'?mode=ro&immutable=1', uri=True)


def load_test(db, identity):
    record = db.execute('SELECT card,intention,facts,context_refs,uncertainty,location FROM tests WHERE id=?', (identity,)).fetchone()
    if record is None:
        raise ValueError('Unknown source test ID')
    return dict(zip(('card','intention','facts','context_refs','uncertainty','location'), map(json.loads,record)))


def query_rows(db, args, repository):
    if args.command in {'search', 'files'}:
        queries = [q.casefold() for q in args.query]
        if args.command == 'files':
            rows = [json.loads(r[0]) for r in db.execute('SELECT metadata FROM files ORDER BY path')]
            return [r for r in rows if not queries or any(q in encoded(r).casefold() for q in queries)]
        rows = db.execute('SELECT id,path,card,intention FROM tests ORDER BY id')
        return [json.loads(card) for identity,path,card,text in rows
                if (not args.file or path == args.file) and
                (not queries or any(q in (identity+' '+text).casefold() for q in queries))]
    record = load_test(db, args.id)
    if args.command == 'show':
        return [record['card']]
    if args.command == 'scenarios':
        return (record['intention'] or {}).get('scenarios', [])
    if args.command == 'detail':
        if args.field == 'uncertainties':
            return [{'uncertainties':record['uncertainty']}]
        value = (record['intention'] or {}).get(args.field)
        if value is None:
            return [{'field':args.field,'status':'NOT_GENERATED'}]
        return [{'field':args.field,'value':value}]
    if args.command == 'facts':
        value = record['facts'].get(args.field, [])
        return [{'section':args.field,'fact':item} for item in value]
    if args.command == 'contexts':
        return [json.loads(db.execute('SELECT metadata FROM contexts WHERE id=?',(ref,)).fetchone()[0])
                for ref in record['context_refs']]
    if args.command == 'relations':
        return [{'source':s,'target':t,'relation':r,'depth':d,'basis':'static candidate, not runtime proof'}
                for s,t,r,d in db.execute('SELECT source,target,relation,depth FROM edges WHERE source=? ORDER BY target,relation,depth',(args.id,))]
    if args.command == 'neighbors':
        return [{'id':i,'shared_dependency':dep,'basis':'shared static dependency, not proof of joint update'}
                for i,dep in db.execute('SELECT DISTINCT b.source,a.target FROM edges a JOIN edges b ON a.target=b.target JOIN tests t ON t.id=b.source WHERE a.source=? AND a.depth=1 AND b.depth=1 AND b.source!=? ORDER BY b.source,a.target',(args.id,args.id))]
    if args.command == 'source':
        location = record['location']
        if args.ref:
            if args.ref not in record['context_refs']:
                raise ValueError('Source reference is not associated with this test')
            location = json.loads(db.execute('SELECT metadata FROM contexts WHERE id=?',(args.ref,)).fetchone()[0])
        relative = Path(location['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe source path')
        source = repository/relative
        if source.is_symlink() or not source.resolve().is_relative_to(repository.resolve()):
            raise ValueError('Unsafe source path')
        lines = source.read_text().splitlines()
        return [{'path':relative.as_posix(),'line':i+1,'source':lines[i]}
                for i in range(max(0,location['start_line']-1),min(len(lines),location['end_line']))]
    raise ValueError('Unknown view')


def main(argv=None, root=None, repository=None):
    parser = argparse.ArgumentParser(description='Read paged existing-test intentions. All tests remain searchable.')
    parser.add_argument('command',choices=('files','search','match','maintenance','show','scenarios','detail','facts','contexts','relations','neighbors','source'))
    parser.add_argument('id',nargs='?')
    parser.add_argument('--query',action='append',default=[],help='Literal case-insensitive query; repeat for OR. Searches complete semantic fields, not just previews.')
    parser.add_argument('--file',help='Optional exact test file restriction; default searches all files.')
    parser.add_argument('--field',default='summary')
    parser.add_argument('--ref',help='A context ID previously returned for this test.')
    parser.add_argument('--offset',type=int,default=0)
    parser.add_argument('--limit',type=int,default=8)
    parser.add_argument('--max-bytes',type=int,default=6000)
    parser.add_argument('--mode',choices=('or','and'),default='or',help='Combine literal query clauses (v3).')
    parser.add_argument('--sort',choices=('field-bm25-v1','tfidf','id'),default='field-bm25-v1')
    parser.add_argument('--search-field',action='append',default=[],help='Exact searchable field from field-contract.json (v3).')
    parser.add_argument('--cursor',help='Opaque continuation from the same v3 search.')
    args=parser.parse_args(argv)
    root=Path(root) if root else Path(__file__).resolve().parent
    repository=Path(repository) if repository else root.parent
    if args.offset<0:
        parser.error('offset must be nonnegative')
    if args.command not in {'search','files'} and not args.id:
        parser.error('This view needs an exact test ID')
    try:
        with connect(root) as db:
            maintenance = (root/'.maintenance.sqlite3').is_file()
            if maintenance and (args.command in {'search','match','maintenance'} or
                                (args.command=='source' and (args.ref or '').startswith('maintenance:'))):
                sys.dont_write_bytecode = True
                if __package__:
                    from . import maintenance_view
                else:
                    import maintenance_view
                if args.command=='search':
                    result=maintenance_view.search_page(root,db,args,page)
                elif args.command=='match':
                    result=page([maintenance_view.lookup(root,db,args.id,args.ref or '')],args.offset,args.limit,args.max_bytes)
                else:
                    rows = (maintenance_view.source(root,args.id,args.ref,repository) if args.command=='source' else
                            maintenance_view.view(root,args.id,'all' if args.field=='summary' else args.field))
                    result=page(rows,args.offset,args.limit,args.max_bytes)
            elif args.command in {'search','match'} and (root/'.search.sqlite3').is_file():
                sys.dont_write_bytecode = True
                if __package__:
                    from . import search_view
                else:
                    import search_view
                if args.command == 'search':
                    result=search_view.search(root,db,args,page)
                else:
                    result=page([search_view.lookup(db,args.id,args.ref or '')],args.offset,args.limit,args.max_bytes)
            else:
                if args.command in {'match','maintenance'} or args.cursor or args.search_field or args.mode != 'or':
                    raise ValueError('This option requires a v3 search index')
                rows=query_rows(db,args,repository)
                result=page(rows,args.offset,args.limit,args.max_bytes)
        print(encoded(result))
    except (ValueError,OSError,sqlite3.Error) as exc:
        print(encoded({'error':type(exc).__name__,'message':str(exc)[:300]}))
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
