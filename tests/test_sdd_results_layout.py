"""Offline presentation acceptance; fake evidence, no Agent/Docker/gold reads."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import http.client
import json
import shutil
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tests.test_sdd_results import sdd_results as viewer, SddResultsBatchFixtureTests, write_json

ui = viewer._layout()


def files(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class LayoutFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bench = SddResultsBatchFixtureTests().build_fixture(self.root)
        (self.bench/'schemas').mkdir()
        for name in ('batch-ledger-event-v1.schema.json','target-result-view-v1.schema.json','target-result-view-v2.schema.json'):
            shutil.copyfile(viewer.bench_default()/'schemas'/name,self.bench/'schemas'/name)
        self.experiments = viewer.discover(self.bench)
        self.parent, self.child = self.experiments
        self.registry_path = self.bench / 'batch/viewer/rounds.json'
        self.entry = {'id': 'round-a', 'name': 'Scrapy · 第一轮', 'groups': [
            {'batch_id': self.parent.batch_id, 'name': '首批 PR'}]}
        write_json(self.registry_path, {'version': 1, 'rounds': [self.entry]})

    def tearDown(self):
        self.temporary.cleanup()



class LayoutTests(LayoutFixture):
    def test_home_has_one_logical_round_and_no_pr_cards_or_artifacts(self):
        before = files(self.bench)
        content = viewer.dashboard_html(self.experiments, self.bench)
        self.assertEqual(content.count('class="round-row"'), 1)
        self.assertIn('Scrapy · 第一轮', content)
        self.assertNotIn('/experiment/' + viewer.experiment_token(self.child), content)
        self.assertNotIn('VISIBLE_SPEC', content)
        self.assertIn('/history', content)
        self.assertIn('/compare', content)
        self.assertEqual(before, files(self.bench))

    def test_unassigned_batches_are_only_in_history_without_pr_siblings(self):
        write_json(self.registry_path, {'version': 1, 'rounds': []})
        home = viewer.dashboard_html(self.experiments, self.bench)
        self.assertNotIn('class="round-row"', home)
        history = ui.homepage(viewer, self.bench, self.experiments, history=True)
        self.assertEqual(history.count('class="round-row"'), 1)
        self.assertIn('/experiment/' + viewer.experiment_token(self.parent), history)
        self.assertNotIn('/experiment/' + viewer.experiment_token(self.child), history)

    def test_round_overview_and_pr_list_keep_artifacts_on_pr_page(self):
        before = files(self.bench)
        content = ui.round_page(viewer, self.bench, self.experiments, 'round-a')
        self.assertIn('1 PR · 2 个方法目标', content)
        self.assertIn('data-tab="prs"', content)
        self.assertIn('/experiment/' + viewer.experiment_token(self.child), content)
        self.assertIn('data-filter="group"', content)
        self.assertIn('data-filter="state"', content)
        self.assertNotIn('VISIBLE_SPEC', content)
        pr = viewer.build_html(self.child, self.bench)
        self.assertIn('VISIBLE_SPEC', pr)
        self.assertIn('candidate &lt;reason&gt;', pr)
        self.assertIn('data-tab="openspec"', pr)
        self.assertIn('/round/round-a#prs', pr)
        self.assertNotIn('GOLD_SENTINEL', content + pr)
        self.assertEqual(before, files(self.bench))

    def test_notes_persist_are_escaped_and_empty_save_deletes(self):
        before = files(self.bench)
        ui.save_note(self.bench, 'round-a', self.parent.batch_id, 'line 1\n<script>alert(1)</script>', '')
        content = ui.round_page(viewer, self.bench, self.experiments, 'round-a')
        self.assertIn('line 1\n&lt;script&gt;alert(1)&lt;/script&gt;', content)
        self.assertNotIn('<script>alert(1)</script>', content)
        self.assertEqual(ui.notes(self.bench)['round-a/'+self.parent.batch_id], 'line 1\n<script>alert(1)</script>')
        after = files(self.bench)
        self.assertEqual({p:v for p,v in after.items() if p != 'Log/viewer/notes.json'}, before)
        ui.save_note(self.bench, 'round-a', self.parent.batch_id, '', 'line 1\n<script>alert(1)</script>')
        self.assertEqual(ui.notes(self.bench), {})

    def test_notes_conflicts_and_membership_checks_preserve_existing_value(self):
        ui.save_note(self.bench, 'round-a', self.parent.batch_id, 'first', '')
        with self.assertRaisesRegex(ui.LayoutError, '其他页面'):
            ui.save_note(self.bench, 'round-a', self.parent.batch_id, 'overwrite', '')
        with self.assertRaisesRegex(ui.LayoutError, '绑定'):
            ui.save_note(self.bench, 'round-b', self.parent.batch_id, 'elsewhere', '')
        self.assertEqual(list(ui.notes(self.bench).values()), ['first'])

    def test_notes_do_not_follow_symlinks(self):
        outside = self.root / 'outside.json'
        outside.write_text('{}')
        path = ui.notes_path(self.bench)
        path.parent.mkdir(parents=True)
        path.symlink_to(outside)
        with self.assertRaises(ui.LayoutError):
            ui.save_note(self.bench,'round-a',self.parent.batch_id,'danger','')
        self.assertEqual(outside.read_text(), '{}')

    def test_explicit_membership_rejects_duplicate_batches_and_overlapping_prs(self):
        self.entry['groups'].append(dict(self.entry['groups'][0]))
        write_json(self.registry_path, {'version':1,'rounds':[self.entry]})
        with self.assertRaisesRegex(ui.LayoutError, '重复归组'):
            ui.registry(self.bench)
        other = replace(self.parent, experiment_id='other', batch_id='other')
        entry = {**self.entry, 'groups':[{'batch_id':self.parent.batch_id,'name':'a'}, {'batch_id':'other','name':'b'}]}
        target = viewer.batch_targets(self.parent,self.bench)[0]
        groups = [ui.Group('a','a',self.parent,[target],{},[],'未评分','file-v1'),ui.Group('b','b',other,[target],{},[],'未评分','file-v1')]
        with patch.object(ui,'group_data',side_effect=groups), self.assertRaisesRegex(ui.LayoutError,'重复 PR'):
            ui.round_data(viewer,self.bench,entry,{self.parent.batch_id:self.parent,'other':other})

    def test_group_notes_never_inherit_to_new_round(self):
        second = {**self.entry, 'id':'round-b', 'groups':[{'batch_id':'different','name':'首批 PR'}]}
        write_json(self.registry_path, {'version':1,'rounds':[self.entry,second]})
        ui.save_note(self.bench,'round-a',self.parent.batch_id,'only in first','')
        content = ui.round_page(viewer,self.bench,self.experiments,'round-b')
        self.assertNotIn('only in first',content)
        self.assertIn('尚未准备', content)

    def test_metric_math_preserves_failure_zero_and_macro_micro(self):
        good = {'testcase':{'tp':1,'fp':0,'fn':0,'precision':1.0,'recall':1.0,'f1':1.0},'status':'OK'}
        bad = {'testcase':{'tp':0,'fp':0,'fn':3,'precision':0.0,'recall':0.0,'f1':0.0},'status':'FAILED_ZERO'}
        rows = [good,bad,{'testcase':None,'status':'HISTORICAL_UNSCORABLE'}]
        self.assertEqual(ui.summary_metric(rows,'testcase','macro'),([.5,.5,.5],2))
        self.assertEqual(ui.summary_metric(rows,'testcase','micro'),([1,.25,.4],2))

    def test_running_and_pending_diagnostics_do_not_count_as_failure(self):
        target=viewer.batch_targets(self.parent,self.bench)[0]
        targets=[replace(target,state='DETECT_RUNNING',execution=None,error='latest target state is DETECT_RUNNING'),replace(target,state='NOT_RECORDED',execution=None,error='target has no ledger event'),replace(target,state='FAILED',execution=None,error='latest target state is FAILED')]
        self.assertEqual(ui.counts(viewer,targets),(0,1,1,1))

    def test_metric_validation_cache_uses_report_and_schema_bytes(self):
        report={'metric_definition_version':'detect-metrics-v3','rows':[],'methods':[]}
        report['metric_set_sha256']=viewer.canonical_sha256(report)
        path=self.bench/'Log/reports/testcase-metrics/cache-test.json'
        schema=self.bench/'schemas/detect-metrics-v3.schema.json'
        write_json(path,report);write_json(schema,{})
        viewer._validated_testcase_metrics.cache_clear()
        import jsonschema
        with patch.object(jsonschema,'Draft202012Validator',wraps=jsonschema.Draft202012Validator) as validate:
            one=viewer.testcase_metrics(self.bench,'cache-test')
            one['rows'].append('cannot poison cache')
            self.assertEqual(viewer.testcase_metrics(self.bench,'cache-test')['rows'],[])
            self.assertEqual(validate.call_count,1)
            write_json(schema,{'required':['missing']})
            self.assertIsNone(viewer.testcase_metrics(self.bench,'cache-test'))
            self.assertEqual(validate.call_count,2)
            write_json(schema,{})
            report['metric_set_sha256']='bad-hash';write_json(path,report)
            self.assertIsNone(viewer.testcase_metrics(self.bench,'cache-test'))

    def test_stale_metric_report_is_hidden(self):
        targets = viewer.batch_targets(self.parent,self.bench)
        detect = targets[0]
        report = {'result_view_sha256':'x','rows':[{'target_key':viewer._target_key(detect.task_id,detect.method,detect.stage,detect.run_id,detect.mode), 'state':detect.state, 'attempt':999}]}
        with patch.object(viewer,'testcase_metrics',return_value=report):
            rows,status=ui.metric_rows(viewer,self.bench,self.parent,targets)
        self.assertEqual(rows,[])
        self.assertIn('过期',status)

    def test_comparison_uses_common_prs_for_metrics_and_tokens(self):
        target=viewer.batch_targets(self.parent,self.bench)[0]
        a=ui.Group('a','a',self.parent,[target,replace(target,task_id='extra-a')],{},[],'未评分','testcase-v1')
        b=ui.Group('b','b',self.parent,[target,replace(target,task_id='extra-b',state='FAILED')],{},[],'未评分','file-v1')
        entries=[{'id':'a','name':'A','groups':[{'batch_id':'a','name':'a'}]}, {'id':'b','name':'B','groups':[{'batch_id':'b','name':'b'}]}]
        with patch.object(ui,'registry',return_value=entries), patch.object(ui,'round_data',side_effect=[[a],[b]]), patch.object(ui,'metric_panel',return_value='<p>metric</p>') as metric, patch.object(ui,'usage_panel',return_value='<p>token</p>') as usage:
            content=ui.compare_page(viewer,self.bench,[],['a','b'])
        self.assertIn('共同 PR 范围：1',content)
        self.assertIn('不可认定为可比',content)
        for reader in (metric,usage):
            scoped=[call.args[2] for call in reader.call_args_list if len(call.args)==3]
            self.assertEqual(scoped,[{target.task_id},{target.task_id}])

    def test_home_index_checks_pins_and_stale_ledger_without_reprepare(self):
        from batch.result_view import write
        write(self.parent.config_path,self.bench,self.root)
        with patch.object(viewer,'batch_targets',side_effect=AssertionError('must not rebuild preparation')):
            targets=ui.snapshot_targets(viewer,self.bench,self.parent)
        self.assertEqual(len(targets),2)
        ledger=self.parent.root/'ledger.jsonl'
        ledger.write_text(ledger.read_text()+'\n')
        with self.assertRaisesRegex(ui.LayoutError,'引用已变化'):
            ui.snapshot_targets(viewer,self.bench,self.parent)

    def test_detail_and_pr_pages_never_rebuild_preparation_chain(self):
        from batch.result_view import write
        write(self.parent.config_path,self.bench,self.root)
        with patch.object(viewer,'batch_targets',side_effect=AssertionError('detail must not reload prepare')):
            content=ui.round_page(viewer,self.bench,self.experiments,'round-a')
            pr=ui.pr_page(viewer,self.bench,self.child)
        self.assertIn('PR 列表',content)
        self.assertIn('方法比较',pr)
        ledger=self.parent.root/'ledger.jsonl'
        ledger.write_text(ledger.read_text()+'\n')
        with patch.object(viewer,'batch_targets',side_effect=AssertionError('stale must not reload prepare')):
            groups=ui.round_data(viewer,self.bench,self.entry,ui.whole(self.experiments))
        self.assertEqual(groups[0].targets,[])
        self.assertIn('引用已变化',groups[0].error)

    def test_home_index_rejects_modified_seal(self):
        from batch.result_view import write
        # The fixture has no historical seals; create the actual current seal
        # before the index is built, then tamper it after its hash is pinned.
        target=viewer.batch_targets(self.parent,self.bench)[0]
        seal=target.execution/'seal.json'
        write_json(seal,{'seal':'original'})
        write(self.parent.config_path,self.bench,self.root)
        write_json(seal,{'seal':'tampered'})
        with self.assertRaisesRegex(ui.LayoutError,'引用已变化'):
            ui.snapshot_targets(viewer,self.bench,self.parent)

    def test_attempt_page_only_allows_ledger_bound_logs(self):
        target=viewer.batch_targets(self.child,self.bench)[0]
        usage=viewer.batch_token_usage(self.child,[target],self.bench)
        row=next(r for r in usage['rows'] if r['attempt']==2)
        content=ui.attempt_page(viewer,self.bench,self.child,ui.attempt_token(row))
        self.assertIn('VISIBLE_DETECT_MESSAGE',content)
        with self.assertRaises(ui.LayoutError):
            ui.attempt_page(viewer,self.bench,self.child,'0'*24)



class HttpLayoutTests(LayoutFixture):
    def test_http_note_save_reload_and_cross_origin_rejection(self):
        before=files(self.bench)
        server=viewer.make_server(self.bench,'127.0.0.1',0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        port=server.server_address[1]
        try:
            def request(method,path,value=None,headers=None):
                connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                connection.request(method,path,body=json.dumps(value) if value else None,headers=headers or {})
                response=connection.getresponse();result=response.status,response.read().decode();connection.close();return result
            for path in ('/','/round/round-a','/history','/compare','/experiment/'+viewer.experiment_token(self.child)):
                self.assertEqual(request('GET',path)[0],200,path)
            self.assertEqual(before,files(self.bench))
            value={'round_id':'round-a','batch_id':self.parent.batch_id,'text':'saved from HTTP','expected':''}
            headers={'Content-Type':'application/json','X-SDD-Viewer':'notes-v1'}
            self.assertEqual(request('POST','/api/note',value,{**headers,'Origin':'https://evil.example'})[0],403)
            self.assertEqual(request('POST','/api/note',value,{**headers,'Host':'evil.example:'+str(port)})[0],403)
            self.assertEqual(request('POST','/api/note',value,headers)[0],200)
            self.assertIn('正在读取实验记录',request('GET','/round/round-a')[1])
            self.assertIn('saved from HTTP',request('GET','/content/round/round-a')[1])
            self.assertEqual(request('POST','/api/note',value,headers)[0],409)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)
        self.assertEqual(list(ui.notes(self.bench).values()),['saved from HTTP'])


if __name__=='__main__':
    unittest.main()
