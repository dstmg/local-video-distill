"""Bailian tests use dummy credentials and local/mocked transport, never real API calls."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import Mock, patch

import analysis_bundle
import auto_distill
import local_llm
import pipeline
from test_auto_distill import respond

DUMMY_KEY = 'test-only-not-a-real-key'


def reply(content='{"ok":true}', reason='stop'):
    return {'choices':[{'finish_reason':reason,'message':{'content':content}}],
            'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}


class BailianTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'config.json'
        self.write_config()
        env=patch.dict(os.environ,{'DASHSCOPE_API_KEY':DUMMY_KEY});env.start();self.addCleanup(env.stop)

    def write_config(self, **updates):
        data={'provider':'bailian','model':'qwen-plus','request_retries':0}
        data.update(updates)
        self.path.write_text(json.dumps(data),encoding='utf-8')
        return local_llm.load_config(self.path)

    def mocked_client(self, response=None):
        client=local_llm.Client(local_llm.load_config(self.path))
        client.opener=Mock()
        client.opener.open.return_value=io.BytesIO(json.dumps(response or reply()).encode())
        return client

    def test_official_endpoints_and_workspace_domains(self):
        endpoints=['https://dashscope.aliyuncs.com/compatible-mode/v1',
                   'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
                   'https://workspace123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
                   'https://workspace123.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1']
        for endpoint in endpoints:
            self.assertEqual(self.write_config(base_url=endpoint)['base_url'],endpoint)

    def test_untrusted_endpoint_and_inline_keys_rejected(self):
        for url in ('http://dashscope.aliyuncs.com/compatible-mode/v1',
                    'https://dashscope.aliyuncs.com.evil.test/compatible-mode/v1',
                    'https://evil.test/compatible-mode/v1',
                    'https://dashscope.aliyuncs.com/other',
                    'https://key@dashscope.aliyuncs.com/compatible-mode/v1',
                    'https://dashscope.aliyuncs.com:444/compatible-mode/v1'):
            with self.assertRaises(ValueError):self.write_config(base_url=url)
        with self.assertRaises(ValueError):self.write_config(api_key=DUMMY_KEY)

    def test_missing_key_fails_without_network_or_transcription(self):
        client=self.mocked_client()
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':''}):
            with self.assertRaisesRegex(ValueError,'缺少'):client.preflight()
        client.opener.open.assert_not_called()
        video=self.root/'input.mp4';video.write_bytes(b'test')
        with patch.dict(os.environ,{'DASHSCOPE_API_KEY':''}), \
             patch.object(pipeline,'run') as run,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):pipeline.main([str(video),str(self.root/'out'),'--llm-config',str(self.path)])
        run.assert_not_called()

    def test_auth_json_flags_and_usage(self):
        client=self.mocked_client();client.preflight()
        self.assertEqual(client.complete([{'role':'user','content':'JSON test'}]),{'ok':True})
        request=client.opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Authorization'),'Bearer '+DUMMY_KEY)
        body=json.loads(request.data)
        self.assertEqual(body['response_format'],{'type':'json_object'})
        self.assertFalse(body['enable_thinking']);self.assertFalse(body['enable_search'])
        self.assertNotIn(DUMMY_KEY,json.dumps(body))
        self.assertEqual(client.usage['total_tokens'],15)
        self.assertEqual(client.usage['request_count'],1)

    def test_key_is_not_forwarded_elsewhere(self):
        client=self.mocked_client()
        with self.assertRaisesRegex(ValueError,'拒绝发送'):
            client.request('https://example.com/chat/completions',{'messages':[]})
        client.opener.open.assert_not_called()

    def test_401_is_clear_without_leaking_server_body(self):
        client=self.mocked_client()
        client.opener.open.side_effect=urllib.error.HTTPError(
            client.config['base_url'],401,'server body '+DUMMY_KEY,{},io.BytesIO(DUMMY_KEY.encode()))
        with self.assertRaises(ValueError) as error:
            client.complete([{'role':'user','content':'JSON test'}])
        self.assertIn('地域',str(error.exception));self.assertNotIn(DUMMY_KEY,str(error.exception))
        self.assertEqual(client.opener.open.call_count,1)

    def test_rate_limit_retries_and_counts_requests(self):
        self.write_config(request_retries=1);client=self.mocked_client()
        client.opener.open.side_effect=[urllib.error.HTTPError(client.config['base_url'],429,'limited',{},None),
                                       io.BytesIO(json.dumps(reply()).encode())]
        with patch('local_llm.time.sleep'):
            client.complete([{'role':'user','content':'JSON test'}])
        self.assertEqual(client.usage['request_count'],2)
        self.assertEqual(client.usage['responses_with_usage'],1)

    def test_truncation_and_empty_json_do_not_look_successful(self):
        for data in (reply(reason='length'),reply(content='')):
            client=self.mocked_client(data)
            with self.assertRaises(ValueError):client.complete([{'role':'user','content':'JSON test'}])
            self.assertEqual(client.usage['total_tokens'],15)

    def test_local_mode_has_no_bailian_authorization(self):
        self.path.write_text(json.dumps({'provider':'local-compatible','model':'test-local'}),encoding='utf-8')
        client=self.mocked_client();client.complete([{'role':'user','content':'JSON'}])
        request=client.opener.open.call_args.args[0]
        self.assertIsNone(request.get_header('Authorization'))

    def test_empty_json_repair_preserves_chat_role_order(self):
        raw=self.root/'run'/'原稿快照'/'s1'
        raw.mkdir(parents=True)
        (raw/'原始提取.json').write_text(json.dumps({'duration':4,'segments':[
            {'start':0,'end':2,'text':'确认来源。'},
            {'start':2,'end':4,'text':'执行检查。'}]},ensure_ascii=False),encoding='utf-8')
        summary=self.root/'sources.json'
        summary.write_text(json.dumps({'artifacts_dir':str(self.root/'run'),'sources':[
            {'id':'s1','path':str(self.root/'video.mp4')}]},ensure_ascii=False),encoding='utf-8')
        client=local_llm.Client(local_llm.load_config(self.path))
        captured=[]
        def open_response(request,timeout):
            messages=json.loads(request.data)['messages'];captured.append(messages)
            if len(captured)==1:
                data=reply(content='')
            else:
                # Repair hints are appended to the original user turn.
                original=[dict(m) for m in messages]
                original[1]['content']=original[1]['content'].split('\n请修正',1)[0]
                data=reply(json.dumps(respond(original),ensure_ascii=False))
            return io.BytesIO(json.dumps(data).encode())
        client.opener=Mock();client.opener.open.side_effect=open_response
        result=auto_distill.generate(summary,self.path,self.root/'generated',client=client)
        self.assertTrue((result/'学习指南.html').exists())
        self.assertEqual(len(captured),3)
        for messages in captured:
            self.assertTrue(all(messages[i]['role']!=messages[i+1]['role'] for i in range(len(messages)-1)))
        state=analysis_bundle.read(self.root/'generated'/'自动蒸馏状态.json')
        self.assertEqual(state['usage']['total_tokens'],45)

    def test_cloud_pipeline_with_loopback_fixture_and_no_secret_in_outputs(self):
        captured=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured.append({'path':self.path,'authorization':self.headers.get('Authorization'),'body':data})
                response=reply(json.dumps(respond(data['messages']),ensure_ascii=False))
                body=json.dumps(response,ensure_ascii=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        actual_opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        class FixtureTransport:
            def open(self,request,timeout):
                # Only tests reroute the declared vendor endpoint to a localhost fixture.
                path=urllib.parse.urlsplit(request.full_url).path
                local=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,
                    data=request.data,headers=dict(request.headers),method=request.method)
                return actual_opener.open(local,timeout=timeout)
        actual_run=pipeline.run
        video=self.root/'video.mp4';video.write_bytes(b'fixture-video')
        def run(cmd,dry=False):
            if str(cmd[1])==pipeline.TRANSCRIBE:
                folder=Path(cmd[3]);folder.mkdir(exist_ok=True)
                (folder/'原始提取.md').write_text('[00:00] 确认来源。\n[00:02] 执行检查。\n',encoding='utf-8')
                pipeline.atomic_json(folder/'原始提取.json',{'duration':4,'segments':[
                    {'start':0,'end':2,'text':'确认来源。'},{'start':2,'end':4,'text':'执行检查。'}]})
                return 0,''
            if str(cmd[1]).endswith('auto_distill.py'):
                arg=lambda flag:cmd[cmd.index(flag)+1]
                with patch('local_llm.urllib.request.build_opener',return_value=FixtureTransport()):
                    auto_distill.generate(arg('--summary'),arg('--config'),arg('--out'),arg('--cache'),
                                         include_skill='--skill-bundle' in cmd)
                return 0,'Fixture cloud analysis passed'
            return actual_run(cmd,dry)
        with patch.object(pipeline,'run',side_effect=run),patch.object(pipeline,'pick_python',return_value=sys.executable),contextlib.redirect_stdout(io.StringIO()):
            rc=pipeline.main([str(video),str(self.root/'out'),'--skip-check','--llm-config',str(self.path),'--skill-bundle'])
        self.assertEqual(rc,0);self.assertEqual(len(captured),2)
        self.assertTrue(all(item['authorization']=='Bearer '+DUMMY_KEY for item in captured))
        self.assertTrue(all(item['path']=='/compatible-mode/v1/chat/completions' for item in captured))
        summary=analysis_bundle.read(self.root/'out'/'summary.json')
        self.assertEqual(summary['privacy'],'text_to_bailian_cloud')
        self.assertEqual(summary['llm_provider'],'bailian')
        self.assertEqual(summary['llm_usage']['total_tokens'],30)
        self.assertEqual(summary['analysis_status'],'auto_generated_evidence_validated')
        state=analysis_bundle.read(Path(summary['artifacts_dir'])/'自动蒸馏'/'自动蒸馏状态.json')
        self.assertTrue(Path(state['skill_bundle'],'SKILL.md').exists())
        for file in (self.root/'out').rglob('*.json'):
            self.assertNotIn(DUMMY_KEY,file.read_text(encoding='utf-8'))
        # A second pipeline run reuses cache and incurs no additional fixture API requests.
        with patch.object(pipeline,'run',side_effect=run),patch.object(pipeline,'pick_python',return_value=sys.executable),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pipeline.main([str(video),str(self.root/'out'),'--skip-check','--llm-config',str(self.path)]),0)
        again=analysis_bundle.read(self.root/'out'/'summary.json')
        self.assertEqual(len(captured),2);self.assertEqual(again['llm_usage']['request_count'],0)
        self.assertEqual(again['llm_usage']['total_tokens'],0)

if __name__=='__main__':unittest.main()
