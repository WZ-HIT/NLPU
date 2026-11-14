"""Read-only progress for the three testcase cohorts; no prepare or evaluator."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

from .core import BatchError
from .orchestrator import Ledger, _latest, target_key
from .prepare import BENCH, ROOT
from .rounds import compile_round

CONFIGS = ('scrapy-30pr-testcase-v1', 'scrapy-next30-testcase-v1', 'scrapy-remaining38-testcase-v1')


def snapshot(compiled: dict, *, bench: Path) -> dict:
    run = bench / 'batch/runs' / compiled['prepared_id']
    path = run / 'prepared-round.json'
    targets = compiled['targets']
    result = {'experiment_id': compiled['config']['experiment_id'], 'round_id': compiled['prepared_id'],
              'total': len(targets), 'sealed': 0, 'failed': 0, 'running': 0, 'pending': len(targets),
              'active': [], 'message': '尚未开始或尚未冻结'}
    if not path.exists():
        audits = len(list((run / 'tasks').glob('*/isolation-audit.json')))
        ready = 0
        for report in (run / 'tasks').glob('*/preflight-summary.json'):
            try:
                ready += json.loads(report.read_text()).get('runtime_preflight_status') == 'READY'
            except (OSError, ValueError):
                pass
        result['message'] = f'准备中（待冻结）：隔离报告 {audits}，预检 READY {ready}' if run.exists() else '尚未开始'
        return result
    if path.is_symlink():
        raise BatchError('PROGRESS_SOURCE_UNSAFE', 'Prepared manifest is symlinked')
    manifest = json.loads(path.read_text())
    if (manifest.get('prepared_id') != compiled['prepared_id']
            or manifest.get('experiment_id') != compiled['config']['experiment_id']
            or manifest.get('inputs', {}).get('user_config') != compiled['config_ref']
            or manifest.get('target_count') != len(targets)
            or [target_key(t) for t in manifest.get('targets', [])] != [target_key(t) for t in targets]):
        raise BatchError('PROGRESS_MANIFEST_MISMATCH', 'Prepared target identity differs from config')
    events = Ledger(run / 'ledger.jsonl', compiled['prepared_id'], bench / 'schemas/batch-ledger-event-v1.schema.json').read()
    latest = _latest(events)
    keys = {target_key(t) for t in targets}
    states = Counter(latest.get(key, {}).get('state', 'NOT_RECORDED') for key in keys)
    result['sealed'] = states['DETECT_SEALED'] + states['EVALUATED']
    result['failed'] = states['FAILED'] + states['BLOCKED']
    result['running'] = states['DETECT_RUNNING']
    result['pending'] = len(keys) - result['sealed'] - result['failed'] - result['running']
    for key in sorted(keys):
        event = latest.get(key)
        if event and event['state'] == 'DETECT_RUNNING':
            age = ''
            try:
                since = datetime.fromisoformat(event['recorded_at_utc'].replace('Z', '+00:00'))
                seconds = max(0, int((datetime.now(timezone.utc) - since).total_seconds()))
                age = f' · 已运行 {seconds//60}分{seconds%60}秒'
            except (ValueError, TypeError):
                pass
            result['active'].append(f"{event['target']['task_id']} · {event['target']['method']} · attempt {event['attempt']}{age}")
    result['message'] = 'ledger 已核对；已封存数不代替产物验收或评分'
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='只读查看 98 PR 三组 Detect 进度')
    parser.add_argument('round', help='与运行命令使用相同轮次标签，如 testcase-002')
    parser.add_argument('--interval', type=float, default=10, help='刷新秒数，默认 10')
    parser.add_argument('--once', action='store_true', help='只显示一次后退出')
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error('--interval 必须大于 0')
    try:
        while True:
            lines = [f"98 PR Detect 进度 · 轮次 {args.round} · {datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%H:%M:%S')} 北京时间",
                     '只读，每 10 秒刷新（可用 --interval 调整）；Ctrl+C 只关闭查看，不停止实验。', '']
            totals = Counter()
            errors = 0
            for name in CONFIGS:
                try:
                    compiled = compile_round(BENCH / 'batch/experiments' / (name + '.json'), args.round, root=ROOT)
                    row = snapshot(compiled, bench=BENCH)
                    lines.append(f"{name}: 已封存 {row['sealed']}/{row['total']} | 运行中 {row['running']} | 失败 {row['failed']} | 待运行 {row['pending']}")
                    lines.append(f"  {row['message']}")
                    lines.extend('  正在运行：' + item for item in row['active'])
                    totals.update({k: row[k] for k in ('total', 'sealed', 'running', 'failed', 'pending')})
                except (BatchError, OSError, ValueError, KeyError, TypeError) as exc:
                    errors += 1
                    lines.append(f"{name}: 暂无法读取 [{getattr(exc, 'code', type(exc).__name__)}]，下次刷新重试。")
            lines.append(f"\n已核对组合计：已封存 {totals['sealed']}/{totals['total']} | 运行中 {totals['running']} | 失败 {totals['failed']} | 待运行 {totals['pending']}")
            if errors:
                lines.append(f'有 {errors} 组无法核对，合计未包含这些组。')
            if sys.stdout.isatty():
                print('\033[2J\033[H', end='')
            print('\n'.join(lines), flush=True)
            if args.once:
                return 2 if errors else 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\n已关闭进度查看，实验继续运行。')
        return 0
