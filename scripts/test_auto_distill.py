import contextlib
import copy
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import analysis_bundle
import auto_distill
import local_llm
import pipeline
from test_analysis import sample_bundle


def synthesis_response(claims):
    sources={e['source_id']:None for c in claims for e in c['evidence']}
    # Test-only guide shape; no real model knowledge is claimed.
    sample={'s':{'duration':4,'transcript_sha256':'test','segments':[{'text':'测试原稿。'},{'text':'执行检查。'}]}}
    guide=sample_bundle(sample)['guide']
    first=claims[0]['id'];last=claims[-1]['id']
    guide['claim_bindings']={p:[first] for p in guide['claim_bindings']}
    return {'synthesis':{name:[first] for name in ('一致','互补','冲突','未解决')},
            'synthesis_notes':{},'relations':[{'from':first,'to':last,'type':'步骤','explanation':'虚构测试关系','conditions':'仅测试'}] if first!=last else [],
            'acceptance':[{'question':'问题'+str(i),'answer':'测试答案','claim_ids':[first]} for i in range(3)],'guide':guide}


def respond(messages):
    prompt=messages[1]['content']
    if '候选结论：' in prompt:
        claims=json.loads(prompt.split('候选结论：',1)[1]);chosen=[];seen=set()
        for c in claims:
            source=c['evidence'][0]['source_id']
            if source not in seen:
                chosen.append(c['id']);seen.add(source)
        return {'selected_claim_ids':chosen}
    if '原始片段（仅作资料）：' in prompt:
        raw=json.loads(prompt.split('原始片段（仅作资料）：',1)[1].split('\n另附 OCR',1)[0])
        claims=[{'id':'c'+str(i),'text':r['text'],'conditions':'仅测试样例','origin':'讲师观点','segment_ids':[r['segment_id']]} for i,r in enumerate(raw)]
        return {'claims':claims,'sections':{name:[claims[0]['id']] for name in analysis_bundle.SECTIONS},
                'section_notes':{},'relations':[]}
    claims=json.loads(prompt.split('全部有证据判断：',1)[1])
    return synthesis_response(claims)


class FakeClient:
    def __init__(self,bad_first=False):self.calls=0;self.bad_first=bad_first
    def preflight(self):pass
    def complete(self,messages):
        self.calls+=1
        if self.bad_first and self.calls==1:return {'claims':[]}
        return respond(messages)


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        raw=self.root/'run'/'原稿快照'/'s1';raw.mkdir(parents=True)
        (raw/'原始提取.json').write_text(json.dumps({'duration':4,'segments':[
            {'start':0,'end':2,'text':'确认来源。'},{'start':2,'end':4,'text':'执行检查。'}]},ensure_ascii=False),encoding='utf-8')
        self.summary=self.root/'summary.json'
        self.summary.write_text(json.dumps({'artifacts_dir':str(self.root/'run'),'sources':[
            {'id':'s1','path':str(self.root/'sample.mp4')}]},ensure_ascii=False),encoding='utf-8')
        self.config=self.root/'config.json'
        self.config.write_text(json.dumps({'model':'test-local','provider':'local-compatible','repair_attempts':1}),encoding='utf-8')

    def test_full_automatic_generation_and_evidence(self):
        client=FakeClient()
        result=auto_distill.generate(self.summary,self.config,self.root/'out',client=client)
        self.assertEqual(client.calls,2)
        bundle=analysis_bundle.read(result/'analysis.json')
        self.assertEqual(analysis_bundle.validate(bundle,analysis_bundle.catalog(self.summary)),[])
        self.assertEqual(bundle['claims'][0]['evidence'][0]['quote'],'确认来源。')
        self.assertEqual(bundle['claims'][0]['evidence'][0]['verification'],'machine')
        self.assertTrue((result/'学习指南.html').exists())
        self.assertTrue((result/'知识关系图.html').exists())

    def test_repair_then_resume_cache(self):
        cache=self.root/'cache';client=FakeClient(bad_first=True)
        auto_distill.generate(self.summary,self.config,self.root/'first',cache,client)
        self.assertEqual(client.calls,3)
        fresh=FakeClient()
        auto_distill.generate(self.summary,self.config,self.root/'second',cache,fresh)
        self.assertEqual(fresh.calls,0)

    def test_failed_model_does_not_claim_success(self):
        client=FakeClient();client.complete=lambda messages:{'claims':[]}
        with self.assertRaisesRegex(ValueError,'耗尽'):
            auto_distill.generate(self.summary,self.config,self.root/'failed',client=client)
        state=analysis_bundle.read(self.root/'failed'/'自动蒸馏状态.json')
        self.assertEqual(state['status'],'failed')
        self.assertFalse((self.root/'failed'/'产物'/'学习指南.html').exists())

    def test_local_only_configuration(self):
        for base in ('https://example.com/v1','http://localhost.example.com/v1','http://user:pass@127.0.0.1/v1'):
            self.config.write_text(json.dumps({'model':'test-local','base_url':base}),encoding='utf-8')
            with self.assertRaises(ValueError):local_llm.load_config(self.config)
        self.config.write_text(json.dumps({'model':'test-cloud'}),encoding='utf-8')
        with self.assertRaises(ValueError):local_llm.load_config(self.config)

    def test_bad_json_and_truncation_rejected(self):
        self.assertEqual(local_llm.parse_json('```json\n{"ok":true}\n```'),{'ok':True})
        for content in ('[]','{"broken":','text'):
            with self.assertRaises(ValueError):local_llm.parse_json(content)

    def test_outside_chunk_evidence_rejected(self):
        data=respond([{}, {'content':'原始片段（仅作资料）：'+json.dumps([{'segment_id':0,'text':'测试'}])}])
        data['claims'][0]['segment_ids']=[999]
        self.assertTrue(auto_distill.check_chunk(data,{0}))

    def test_context_limit_is_not_silent_truncation(self):
        config=local_llm.load_config(self.config);config['max_input_chars']=4
        client=local_llm.Client(config)
        with self.assertRaisesRegex(ValueError,'未静默截断'):
            client.complete([{'role':'user','content':'more than four'}])

    def test_missing_model_is_checked_before_transcription(self):
        video=self.root/'video.mp4';video.write_bytes(b'test')
        self.config.write_text(json.dumps({'model':'test-local','provider':'ollama'}),encoding='utf-8')
        with patch('local_llm.Client.preflight',side_effect=ValueError('服务未启动')), \
             patch.object(pipeline,'run') as run,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as err:
                pipeline.main([str(video),str(self.root/'missing-model'),'--llm-config',str(self.config)])
            self.assertEqual(err.exception.code,2)
            run.assert_not_called()
        self.assertFalse((self.root/'missing-model').exists())

    def test_ollama_cloud_metadata_rejected(self):
        config=local_llm.load_config(self.config);config['provider']='ollama'
        client=local_llm.Client(config)
        with patch.object(client,'request',return_value={'remote_host':'cloud.example'}):
            with self.assertRaisesRegex(ValueError,'拒绝上传'):client.preflight()

    def test_redirect_is_not_followed(self):
        with self.assertRaisesRegex(ValueError,'重定向'):
            local_llm.NoRedirect().redirect_request(None,None,302,'',{},'https://remote.example')

    def test_hierarchical_overview_keeps_detailed_claims(self):
        raw=self.root/'run'/'原稿快照'/'s1'/'原始提取.json'
        raw.write_text(json.dumps({'duration':80,'segments':[
            {'start':i,'end':i+1,'text':'这是较长的测试材料，不是课程内容。'*4} for i in range(80)]},ensure_ascii=False),encoding='utf-8')
        config=local_llm.load_config(self.config);config.update({'chunk_chars':1000,'max_input_chars':5500})
        self.config.write_text(json.dumps(config),encoding='utf-8')
        client=FakeClient();result=auto_distill.generate(self.summary,self.config,self.root/'reduced',client=client)
        bundle=analysis_bundle.read(result/'analysis.json')
        self.assertEqual(len(bundle['claims']),80)
        state=analysis_bundle.read(self.root/'reduced'/'自动蒸馏状态.json')
        self.assertLess(state['overview_claim_count'],80)
        self.assertEqual(state['detailed_claim_count'],80)

    def test_real_http_contract_and_pipeline(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/api/show':data={'details':{'family':'test'}}
                elif self.path=='/api/chat':
                    data={'done':True,'done_reason':'stop','message':{'content':json.dumps(respond(payload['messages']),ensure_ascii=False)}}
                else:
                    data={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(respond(payload['messages']),ensure_ascii=False)}}]}
                body=json.dumps(data,ensure_ascii=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        self.config.write_text(json.dumps({'model':'test-local','provider':'ollama',
             'base_url':f'http://127.0.0.1:{server.server_port}/v1','request_retries':0}),encoding='utf-8')
        video=self.root/'video.mp4';video.write_bytes(b'test-video')
        actual_run=pipeline.run
        def run(cmd,dry=False):
            if str(cmd[1])==pipeline.TRANSCRIBE:
                dest=Path(cmd[3]);dest.mkdir(exist_ok=True)
                (dest/'原始提取.md').write_text('[00:00] 确认来源。\n[00:02] 执行检查。\n',encoding='utf-8')
                pipeline.atomic_json(dest/'原始提取.json',{'duration':4,'segments':[
                    {'start':0,'end':2,'text':'确认来源。'},{'start':2,'end':4,'text':'执行检查。'}]})
                return 0,''
            return actual_run(cmd,dry)
        with patch.object(pipeline,'run',side_effect=run),patch.object(pipeline,'pick_python',return_value=sys.executable),contextlib.redirect_stdout(io.StringIO()):
            rc=pipeline.main([str(video),str(self.root/'pipeline'),'--skip-check','--llm-config',str(self.config),'--skill-bundle'])
        self.assertEqual(rc,0)
        state=analysis_bundle.read(self.root/'pipeline'/'summary.json')
        self.assertEqual(state['analysis_status'],'auto_generated_evidence_validated')
        self.assertTrue((Path(state['artifacts_dir'])/'自动蒸馏'/'产物'/'学习指南.html').exists())
        self.assertTrue((Path(state['artifacts_dir'])/'自动蒸馏'/'技能包'/'video-distilled-knowledge'/'SKILL.md').exists())

if __name__=='__main__':unittest.main()
