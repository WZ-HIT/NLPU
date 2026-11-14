"""v6 additive reader. Unchanged commands delegate to the sealed A reader."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

# A read must not add __pycache__ files to a hash-pinned bundle, even on the host.
sys.dont_write_bytecode = True

if __package__:
    from . import reader as legacy_read, sensitivity_view
else:
    import legacy_read
    import sensitivity_view


def main(argv=None, root=None, repository=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(root) if root else Path(__file__).resolve().parent
    repository = Path(repository) if repository else root.parent
    if not argv or argv[0] not in ('sensitive', 'point'):
        return legacy_read.main(argv, root, repository)
    parser = argparse.ArgumentParser(description='Saved source sensitivity facts; no update prediction')
    parser.add_argument('command', choices=('sensitive', 'point'))
    parser.add_argument('id')
    parser.add_argument('--ref')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=8)
    parser.add_argument('--max-bytes', type=int, default=6000)
    args = parser.parse_args(argv)
    if args.offset < 0 or (args.command=='point' and not args.ref):
        parser.error('Nonnegative offset and point --ref required')
    try:
        with legacy_read.connect(root) as db:
            if args.command=='sensitive':
                rows, coverage = sensitivity_view.points(root, db, args.id)
                rows = [{'id': args.id, 'version': sensitivity_view.VERSION, 'coverage': coverage,
                         'basis': 'Saved syntax and associated context, not execution or update necessity'},
                        *map(sensitivity_view.short, rows)]
            else:
                rows = sensitivity_view.expand(root, db, args.id, args.ref, repository)
            result = legacy_read.page(rows, args.offset, args.limit, args.max_bytes)
        print(legacy_read.encoded(result))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)[:300]}))
        return 1


if __name__=='__main__':
    sys.exit(main())
