"""Live TI progress must be read-only and distinct from model completion."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from tests.test_sdd_results import sdd_results as viewer, write_json

ui = viewer._layout()
from batch import intention_results as provider


class IntentionResults(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bench = self.root/'sdd-bench/scrapy-sdd'
        self.bench.mkdir(parents=True)
        self.run = self.root/'experiment'
        self.plan = {'version': 'dynamic-d-run-v1', 'groups': ['D'], 'prs': [42, 43],
                     'targets': [dict(group='D', task_id=f'repo__pr{pr}', pr=pr, method=m)
                                 for pr in [42, 43] for m in provider.METHODS],
                     'model': 'fixture', 'effort': 'high', 'rollout_per_target': 100000,
                     'timeout_seconds': 2700, 'max_parallel': 3}
        write_json(self.run/'plan.json', self.plan)
        self.entry = {'id': 'ti-d', 'name': '当前实验 · D组', 'provider': provider.PROVIDER,
                      'run_root': str(self.run),
                      'plan_sha256': hashlib.sha256((self.run/'plan.json').read_bytes()).hexdigest(),
                      'groups': [{'batch_id': 'ti-d', 'name': 'D组'}]}
        write_json(self.bench/'batch/viewer/rounds.json', {'version': 1, 'rounds': [self.entry]})
        write_json(self.run/'execution-status.json', {'stage': 'PREPARING_NO_MODELS'})
        stat = Path(f'/proc/{os.getpid()}/stat').read_text().split(') ', 1)[1].split()
        write_json(self.run/'workflow-process.json', {'pid': os.getpid(), 'start_ticks': stat[19]})

    def files(self):
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def journal(self, entries):
        with sqlite3.connect(self.run/'ledger.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS targets(key TEXT PRIMARY KEY,state TEXT,starts INTEGER,detail TEXT)')
            db.executemany('INSERT INTO targets VALUES(?,?,?,?)',
                           [(f'D:repo__pr{pr}:{m}', s, n, '{"secret":"NEVER_EXPOSE"}')
                            for pr, m, s, n in entries])

    def test_preparation_is_not_formal_progress_and_reads_never_write(self):
        write_json(self.run/'execution-root/sdd-bench/scrapy-sdd/batch/runs/round-one/tasks/repo__pr42/preflight-summary.json',
                   {'status': 'BLOCKED', 'runtime_preflight_status': 'READY'})
        before = self.files()
        doc = provider.snapshot(self.bench, self.entry)
        self.assertEqual((doc['prepared'], doc['formal_starts'], doc['terminal'], doc['pending']), (1, 0, 0, 6))
        page = ui.round_page(viewer, self.bench, [], 'ti-d')
        self.assertIn('准备检查 1/2 PR', page)
        self.assertIn('正式终态 0/6', page)
        self.assertIn('15000', page)
        self.assertIn('data-ti-target="42:openspec"', page)
        home = viewer.dashboard_html([], self.bench)
        self.assertIn('查看实时进度', home)
        self.assertEqual(before, self.files())

    def test_states_denominators_and_no_raw_details(self):
        self.journal([(42, 'openspec', 'DETECT_SEALED', 1), (42, 'speckit', 'FAILED', 1),
                      (42, 'cc-sdd', 'BLOCKED', 0), (43, 'openspec', 'DETECT_RUNNING', 1)])
        doc = provider.snapshot(self.bench, self.entry)
        self.assertEqual((doc['formal_starts'], doc['terminal'], doc['running'], doc['pending']), (3, 3, 1, 2))
        self.assertEqual((doc['sealed'], doc['failed']), (1, 2))
        self.assertNotIn('NEVER_EXPOSE', json.dumps(doc))
        self.assertNotIn('run_root', doc)
        self.assertNotIn('workflow', doc)

    def test_dead_or_recycled_controller_is_not_shown_as_live(self):
        self.journal([(42, 'openspec', 'DETECT_RUNNING', 1)])
        write_json(self.run/'workflow-process.json', {'pid': os.getpid(), 'start_ticks': 'wrong'})
        doc = provider.snapshot(self.bench, self.entry)
        self.assertFalse(doc['workflow_alive'])
        self.assertIn('已退出', doc['label'])
        self.assertIn('需核查', provider.state_label('DETECT_RUNNING', doc))

    def test_invalid_plan_scope_journal_or_completion_is_not_silent_zero(self):
        write_json(self.run/'plan.json', dict(self.plan, model='changed'))
        with self.assertRaisesRegex(ValueError, '哈希'):
            provider.snapshot(self.bench, self.entry)
        write_json(self.run/'plan.json', self.plan)
        self.journal([(999, 'openspec', 'DETECT_SEALED', 1)])
        with self.assertRaisesRegex(ValueError, '范围'):
            provider.snapshot(self.bench, self.entry)
        (self.run/'ledger.sqlite3').unlink()
        write_json(self.run/'completion.json', {'status': 'COMPLETE', 'targets': 6})
        with self.assertRaisesRegex(ValueError, '终态'):
            provider.snapshot(self.bench, self.entry)

    def test_valid_completion_keeps_failures_and_works_after_controller_exit(self):
        self.journal([(pr, m, 'FAILED' if m == 'speckit' else 'DETECT_SEALED', 1)
                      for pr in [42, 43] for m in provider.METHODS])
        write_json(self.run/'completion.json', {'status': 'COMPLETE', 'targets': 6})
        write_json(self.run/'workflow-process.json', {})
        doc = provider.snapshot(self.bench, self.entry)
        self.assertEqual((doc['complete'], doc['failed'], doc['terminal']), (True, 2, 6))
        self.assertEqual(doc['label'], '实验完成')

    def test_http_api_bypasses_discovery_and_does_not_write(self):
        before = self.files()
        server = viewer.make_server(self.bench, '127.0.0.1', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(*server.server_address)
        try:
            with patch.object(viewer, 'discover', side_effect=AssertionError('API must not discover')):
                connection.request('GET', '/api/intention-results/ti-d')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())['expected'], 6)
                connection.request('GET', '/api/intention-results/unknown')
                response = connection.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
                write_json(self.run/'plan.json', {})
                connection.request('GET', '/api/intention-results/ti-d')
                response = connection.getresponse()
                self.assertEqual(response.status, 422)
                response.read()
                write_json(self.run/'plan.json', self.plan)
            connection.request('GET', '/content/round/ti-d')
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn('D组', response.read().decode())
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(before, self.files())

    def test_browser_updates_without_page_reload_and_reports_poll_failures(self):
        if not shutil.which('node'):
            self.skipTest('Node not available')
        doc = provider.snapshot(self.bench, self.entry)
        script = provider.live_script(self.entry).removeprefix('<script>').removesuffix('</script>')
        harness = '''
let tick;const nodes={};let data=DOC,fail=false;
const scope={querySelector:s=>nodes[s]||(nodes[s]={textContent:'',style:{}})};
global.document={hidden:false,querySelector:()=>scope,addEventListener:()=>{}};
global.setInterval=(f,ms)=>{if(ms!==15000)throw Error('interval');tick=f;};
global.fetch=async()=>({ok:!fail,status:422,json:async()=>data});
SCRIPT
(async()=>{await new Promise(r=>setTimeout(r,0));
 data.prepared=1;data.terminal=2;data.targets[0].state='FAILED';await tick();
 if(!nodes['[data-ti="summary"]'].textContent.includes('正式终态 2/6'))throw Error('stale count');
 if(nodes['[data-ti-target="42:openspec"]'].textContent!=='失败')throw Error('stale target');
 fail=true;await tick();if(!nodes['[data-ti="error"]'].textContent.includes('上次状态'))throw Error('poll failure hidden');
})();'''
        result = subprocess.run(['node', '-e', harness.replace('DOC', json.dumps(doc)).replace('SCRIPT', script)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
