"""Archive expired records. Read-only by default; explicit modes initialize, complete or apply."""
import argparse
import json
import sys
from pathlib import Path
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from database import configuration
from settings import settings
from retention import archive_url, initialize, run, mark_completed, reflect, source_lock, TABLES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--initialize', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--complete', nargs=2, metavar=('TABLE', 'KEY'))
    parser.add_argument('--completed-at', help='Actual completion/expiry time, ISO format in Asia/Taipei')
    parser.add_argument('--note', default='')
    parser.add_argument('--actor', default='operator')
    parser.add_argument('--table', action='append', choices=TABLES)
    parser.add_argument('--batch-size', type=int, default=500)
    parser.add_argument('--max-batches', type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000 or not 1 <= args.max_batches <= 100:
        parser.error('Batch size must be 1..1000, max batches 1..100')
    data, url, _ = configuration(ROOT)
    if args.apply and settings(ROOT).get('AMS_ARCHIVE_ENABLED', '0') != '1':
        raise SystemExit('Archive cleanup is disabled until initialization and verification are complete (AMS_ARCHIVE_ENABLED=1). No rows deleted.')
    source = create_engine(url, hide_parameters=True, connect_args={'connect_timeout': 10})
    target = create_engine(archive_url(url, ROOT), hide_parameters=True, connect_args={'connect_timeout': 10})
    try:
        if args.initialize:
            initialize(source, target)
            print(json.dumps({'initialized': target.url.database}))
        elif args.complete:
            if not args.completed_at or not args.note:
                parser.error('--complete requires --completed-at and --note')
            with source.begin() as c:
                source_lock(c, url.database)
                mark_completed(c, reflect(c), *args.complete, args.completed_at, args.note, args.actor, ROOT, data)
            print(json.dumps({'completed': args.complete}))
        else:
            for report in run(source, target, ROOT, data, args.apply, args.batch_size, args.max_batches, args.table):
                print(json.dumps(report, ensure_ascii=False))
    finally:
        source.dispose()
        target.dispose()


if __name__ == '__main__':
    main()
