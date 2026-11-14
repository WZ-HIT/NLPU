"""Offline/read-only UI checks for the external two-phase batch provider."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import shutil
import subprocess
import unittest
from unittest.mock import patch

from tests import test_sdd_results as fixtures
viewer = fixtures.sdd_results
ui = viewer._layout()
from batch import production_results as provider


class ProductionResults(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.bench=self.root/'sdd-bench/scrapy-sdd';self.bench.mkdir(parents=True)
        self.entry={'id':'production-first30','name':'当前实验 · 两阶段定位','provider':provider.PROVIDER,
            'snapshot':'Log/viewer/production.json','manifest_sha256':'a'*64,
            'historical_compare_round':'old','historical_batch_id':'historical-batch',
            'groups':[{'batch_id':'first30','name':'首批30 PR'}]}
        self.write(self.bench/'batch/viewer/rounds.json',{'version':1,'rounds':[self.entry]})
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        groups=[]
        for method in provider.METHODS:
            stages={s:{'status':'PENDING','usage':None,'error':None} for s in ['production','tests']}
            groups.append({'pr':42,'method':method,'state':'PENDING','stages':stages,
                           'production_predictions':None,'test_predictions':None})
        self.doc={'version':1,'document_type':'PRODUCTION_TEST_RESULTS_VIEW','experiment_id':'first30',
            'updated_at':now,'started_at':now,'controller_state':'RUNNING','controller_error':None,
            'agent':'Codex CLI 0.153.4','model':'deepseek-flash','reasoning':'high','methods':list(provider.METHODS),
            'budgets':{'max_stage_runs':6,'token_budget_per_pr':200000,'production_token_budget':100000,'deadline_seconds_per_pr':2700},
            'tasks':[{'pr':42,'title':'Escape <candidate>'}],'groups':groups,'counts':{},
            'usage':{'rollout_known_subtotal':0,'recorded_stages':0,'started_stages':0},
            'metrics_available':False,'method_metrics':None,'evaluation_rows':[],'paired_comparison':None,
            'source_refs':{'manifest_sha256':'a'*64}}
        self.publish()

    def tearDown(self):self.temp.cleanup()

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False))

    def publish(self):
        value=copy.deepcopy(self.doc);value['view_sha256']=provider.canonical(value)
        self.write(self.bench/self.entry['snapshot'],value)

    def files(self):
        return {str(p.relative_to(self.bench)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.bench.rglob('*') if p.is_file()}

    def test_home_and_round_show_pending_not_zero_metrics_and_no_writes(self):
        before=self.files()
        home=viewer.dashboard_html([],self.bench)
        detail=ui.round_page(viewer,self.bench,[],self.entry['id'])
        self.assertIn('当前实验 · 两阶段定位',home)
        self.assertIn('/round/production-first30',home)
        self.assertIn('未评分',detail);self.assertIn('N/A',detail)
        self.assertNotIn('0.0%',detail)
        self.assertIn('Escape &lt;candidate&gt;',detail)
        self.assertNotIn('Escape <candidate>',detail)
        self.assertEqual(before,self.files())

    def test_pr_detail_renders_both_phases_optional_reason_and_escaped_source(self):
        g=self.doc['groups'][0];g['state']='OK'
        g['stages']['production']['status']='OK';g['stages']['tests']['status']='OK'
        g['production_predictions']={'files':[],'classes':[],'functions':[]}
        g['test_predictions']={'candidates':[{'path':'tests/test_x.py','symbols':['test_x'],
            'production_refs':[],'needs_update':True,'update_reason':None,'relation_reason':'<script>source</script>'}]}
        self.publish()
        before=self.files()
        page=provider.pr_page(viewer,ui,self.bench,self.entry,42)
        self.assertIn('第一轮生产候选',page);self.assertIn('第二轮测试候选与判断',page)
        self.assertIn('未提供（允许）',page);self.assertIn('&lt;script&gt;source&lt;/script&gt;',page)
        self.assertNotIn('<script>source</script>',page)
        self.assertEqual(before,self.files())

    def test_all_tests_round_and_pr_describe_independent_search(self):
        self.doc['test_search_strategy']='all_tests'
        self.doc['production_predictions_role']='human_analysis_only'
        g=self.doc['groups'][0];g['state']='OK'
        g['stages']['production']['status']='OK';g['stages']['tests']['status']='OK'
        g['production_predictions']={'files':[],'classes':[],'functions':[]}
        g['test_predictions']={'candidates':[{'path':'tests/test_x.py','symbols':['test_x'],
            'needs_update':True,'relation_reason':'PR source evidence'}]}
        self.publish();before=self.files()
        page=provider.round_page(viewer,ui,self.bench,self.entry)
        detail=provider.pr_page(viewer,ui,self.bench,self.entry,42)
        home=provider.homepage_row(viewer,self.bench,self.entry)
        self.assertIn('搜索全部已有测试',page)
        self.assertIn('不要求生产关联',page)
        self.assertNotIn('成功空生产仍按PR描述',page)
        self.assertIn('独立全量测试定位',home)
        self.assertIn('第一轮生产候选（人工分析材料）',detail)
        self.assertIn('第二轮全量测试更新判断',detail)
        self.assertNotIn('成功空预测：第二轮按PR描述直接定位测试',detail)
        self.assertEqual(before,self.files())

    def test_pending_all_tests_pr_already_displays_its_search_scope(self):
        self.doc['test_search_strategy']='all_tests';self.publish()
        detail=provider.pr_page(viewer,ui,self.bench,self.entry,42)
        self.assertIn('搜索全部已有测试',detail)
        self.assertIn('不要求生产关联',detail)

    def test_corrupt_or_wrong_manifest_snapshot_is_rejected(self):
        path=self.bench/self.entry['snapshot'];value=json.loads(path.read_text());value['controller_state']='EVALUATED';self.write(path,value)
        with self.assertRaisesRegex(ValueError,'哈希'):provider.snapshot(self.bench,self.entry)
        self.doc['source_refs']['manifest_sha256']='b'*64;self.publish()
        with self.assertRaisesRegex(ValueError,'身份'):provider.snapshot(self.bench,self.entry)

    def test_snapshot_never_accepts_gold_fields(self):
        self.doc['groups'][0]['testcase_gold']=['GOLD_SENTINEL'];self.publish()
        with self.assertRaisesRegex(ValueError,'评估内容'):provider.snapshot(self.bench,self.entry)
        home=viewer.dashboard_html([],self.bench)
        self.assertNotIn('GOLD_SENTINEL',home)

    def test_stale_or_stopped_running_group_is_not_presented_as_live(self):
        self.doc['groups'][0]['state']='RUNNING';self.doc['groups'][0]['stages']['production']['status']='RUNNING'
        self.doc['updated_at']='2000-01-01T00:00:00+00:00';self.publish()
        doc=provider.snapshot(self.bench,self.entry)
        self.assertTrue(doc['stale']);self.assertIn('未确认',provider.effective_state(doc))
        self.assertIn('待核查',provider.group_label(doc['groups'][0],doc))
        self.doc['controller_state']='STOPPED';self.publish();doc=provider.snapshot(self.bench,self.entry)
        self.assertIn('待核查',provider.group_label(doc['groups'][0],doc))

    def test_path_traversal_symlinks_and_unknown_pr_are_rejected(self):
        with self.assertRaises(ValueError):provider.snapshot(self.bench,dict(self.entry,snapshot='../outside.json'))
        path=self.bench/self.entry['snapshot'];target=self.root/'outside.json';target.write_text(path.read_text());path.unlink();path.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'符号链接'):provider.snapshot(self.bench,self.entry)
        path.unlink();self.publish()
        with self.assertRaisesRegex(ValueError,'不属于'):provider.pr_page(viewer,ui,self.bench,self.entry,99)

    def test_incomplete_target_scope_and_malformed_snapshot_rejected(self):
        self.doc['groups'].pop();self.publish()
        with self.assertRaisesRegex(ValueError,'不完整'):provider.snapshot(self.bench,self.entry)
        self.write(self.bench/self.entry['snapshot'],[])
        with self.assertRaises(ValueError):provider.snapshot(self.bench,self.entry)

    def test_evaluated_metrics_keep_failure_warning_and_all_granularities(self):
        a={'macro_f1':1.,'micro_f1':1.,'micro_precision':1.,'micro_recall':1.,'positive_tasks':1,'no_positive_fp':0}
        self.doc['controller_state']='EVALUATED';self.doc['metrics_available']=True
        self.doc['method_metrics']={m:{'successful_groups':1,'failed_no_positive_groups':0,'testcase':a,
            'all_pr_micro':{'testcase':{'f1':2/3}},'production':{k:a for k in ['file','class','function']},'scoped_file':a}
            for m in provider.METHODS}
        b={'paired_count':1,'new':a,'historical':a,'new_all_pr_micro':{'f1':2/3},'historical_all_pr_micro':{'f1':1},'new_failed_groups':0,'historical_failed_groups':1}
        self.doc['paired_comparison']={m:{'metrics':{'testcase':b}} for m in provider.METHODS};self.publish()
        page=ui.round_page(viewer,self.bench,[],self.entry['id'])
        self.assertIn('66.7%',page);self.assertIn('生产类',page);self.assertIn('生产函数',page)
        self.assertIn('不能解释为正确负判断',page);self.assertIn('历史失败',page)

    def test_cross_protocol_comparison_does_not_invent_a_paired_delta(self):
        old={'id':'unrelated','name':'文件定位历史','groups':[{'batch_id':'another','name':'旧组'}]}
        self.write(self.bench/'batch/viewer/rounds.json',{'version':1,'rounds':[self.entry,old]})
        page=ui.compare_page(viewer,self.bench,[],[self.entry['id'],'unrelated'])
        self.assertIn('没有已核对的成对历史报告',page)
        self.assertNotIn('共同 PR 范围：0',page)

    def test_live_script_does_not_reload_on_heartbeat_but_does_on_phase_change(self):
        if not shutil.which('node'):self.skipTest('Node not installed')
        script=provider.live_script(self.entry,self.doc).removeprefix('<script>').removesuffix('</script>')
        harness='''let tick,reloads=0;global.setInterval=f=>{tick=f};global.document={hidden:false,activeElement:null,querySelectorAll:()=>[]};global.location={reload:()=>{reloads++}};let data=DOC;global.fetch=async()=>({ok:true,json:async()=>data});SCRIPT
(async()=>{await tick();if(reloads!==0)throw Error('idle snapshot reloaded');data.groups[0].state='RUNNING';await tick();if(reloads!==1)throw Error('phase transition not refreshed');})();'''
        result=subprocess.run(['node','-e',harness.replace('DOC',json.dumps(self.doc)).replace('SCRIPT',script)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_http_snapshot_and_both_pages_are_read_only_and_api_skips_discovery(self):
        before=self.files();server=viewer.make_server(self.bench,'127.0.0.1',0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        connection=http.client.HTTPConnection(*server.server_address)
        try:
            with patch.object(viewer,'discover',side_effect=AssertionError('API must not rebuild/discover')):
                connection.request('GET','/api/production-results/production-first30');response=connection.getresponse()
                self.assertEqual(response.status,200);payload=json.loads(response.read());self.assertFalse(payload['metrics_available'])
            for url,text in [('/content/round/production-first30','未评分'),('/content/production-pr/production-first30/42','生产定位')]:
                connection.request('GET',url);response=connection.getresponse();self.assertEqual(response.status,200);self.assertIn(text,response.read().decode())
            connection.request('GET','/api/production-results/not-registered');response=connection.getresponse();self.assertEqual(response.status,404);response.read()
        finally:
            connection.close();server.shutdown();server.server_close();thread.join()
        self.assertEqual(before,self.files())


if __name__=='__main__':unittest.main()
