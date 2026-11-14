"""D wrapper: preserve C search/static/semantic views, add complete-only runtime views."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.dont_write_bytecode = True
if __package__:
    from . import stage_b_reader as ti_read, reader as legacy_read, dynamic_view
else:
    import ti_read
    import legacy_read
    import dynamic_view


def main(argv=None, root=None, repository=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(root) if root else Path(__file__).resolve().parent
    repository = Path(repository) if repository else root.parent
    commands = ('show', 'coverage', 'trace', 'shared')
    if argv and argv[0] not in commands and argv[0] not in ('--help', '-h'):
        return ti_read.main(argv, root, repository)
    parser = argparse.ArgumentParser(description='D runtime views; all other C commands/search are unchanged. Static neighbors stays static.')
    parser.add_argument('command', choices=commands)
    parser.add_argument('id')
    parser.add_argument('--with', dest='other', help='Read every shared-function witness for one neighbor')
    parser.add_argument('--depth', type=int, default=2, help='Trace only: 0 means full per-instance graph; default 2')
    parser.add_argument('--instance', help='Trace only: one valid execution ID')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=8)
    parser.add_argument('--max-bytes', type=int, default=6000)
    args = parser.parse_args(argv)
    if args.offset < 0 or args.depth < 0:
        parser.error('Nonnegative offset/depth required')
    if args.other is not None and args.command != 'shared' or args.instance is not None and args.command != 'trace':
        parser.error('--with is for shared; --instance is for trace')
    if args.command == 'shared' and args.depth != 2:
        parser.error('Shared relation is fixed to depth <= 2 on both sides')
    try:
        with dynamic_view.connect(root) as db, legacy_read.connect(root) as evidence:
            if args.command == 'show':
                card = legacy_read.load_test(evidence, args.id)['card']
                card['dynamic'] = dynamic_view.metadata(db, args.id)
                rows = [card]
            elif args.command == 'coverage':
                rows = dynamic_view.coverage_rows(db, args.id)
            elif args.command == 'trace':
                rows = dynamic_view.trace_rows(root, db, args.id, args.depth, args.instance)
            else:
                rows = dynamic_view.shared_rows(db, evidence, args.id, args.other)
            result = legacy_read.page(rows, args.offset, args.limit, args.max_bytes)
        print(legacy_read.encoded(result))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)[:300]}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
