import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import analysis_bundle as analysis
import guide_builder
import visual_extract


def sample_bundle(sources):
    bundle=analysis.template(sources);bundle['status']='ready'
    first=next(iter(sources));end=sources[first]['duration']
    def ev(text):
        return {'source_id':first,'start':0,'end':end,'quote':text,'verification':'machine'}
    texts=[sources[first]['segments'][0]['text'],sources[first]['segments'][-1]['text']]
    bundle['claims']=[{'id':f'c{i+1}','text':t,'origin':'讲师观点','conditions':'仅此虚构示例',
                       'evidence':[ev(t)]} for i,t in enumerate(texts)]
    for a in bundle['analyses']:
        sid=a['source_id']; a['read_ranges']=[[0,sources[sid]['duration']]]
        if sid==first:
            for name in a['sections']: a['sections'][name]=['c1']
        else:
            cid='source-'+sid
            bundle['claims'].append({'id':cid,'text':sources[sid]['segments'][0]['text'],
                'origin':'讲师观点','conditions':'仅此虚构示例','evidence':[
                    {'source_id':sid,'start':0,'end':sources[sid]['duration'],
                     'quote':sources[sid]['segments'][0]['text'],'verification':'machine'}]})
            for name in a['sections']: a['sections'][name]=[cid]
    bundle['relations']=[{'id':'r'+str(i),'from':'c1','to':'c2','type':kind,
         'explanation':'虚构测试关系，不作为真实知识','origin':'整理者推断','conditions':'仅测试',
         'evidence':[ev(texts[0]),ev(texts[1])]} for i,kind in enumerate(sorted(analysis.RELATIONS))]
    bundle['synthesis']={k:['c1'] for k in bundle['synthesis']}
    bundle['acceptance']=[{'question':'测试问题'+str(i),'answer':texts[0],'claim_ids':['c1']} for i in range(3)]
    guide={'title':'虚构测试学习指南','overview':{'lead':texts[0],'body':[texts[0]]},
        'prereq':[texts[0]],'concepts':[{'title':'概念','what':texts[0],'why':texts[0],'how':texts[1]}],
        'steps':[{'title':'步骤','items':[{'text':texts[0],'ok':texts[1],'ts':'00:00'}]}],
        'pit':[{'wrong':'仅为示例','right':texts[0],'why':texts[1]}], 'example':[texts[0]],
        'quiz':[{'q':'测试问题','a':texts[0]}],'next':[texts[1]],
        'src':{'index':['00:00','00:01','00:02']}}
    pointers=['/overview/lead','/overview/body/0','/prereq/0','/concepts/0/what','/concepts/0/why','/concepts/0/how',
         '/steps/0/items/0/text','/steps/0/items/0/ok','/pit/0/wrong','/pit/0/right','/pit/0/why',
         '/example/0','/quiz/0/q','/quiz/0/a','/next/0']
    guide['claim_bindings']={p:['c1'] for p in pointers};bundle['guide']=guide
    return bundle


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);raw=self.root/'原稿快照'/'s1';raw.mkdir(parents=True)
        (raw/'原始提取.json').write_text(json.dumps({'duration':4,'segments':[
            {'start':0,'end':2,'text':'先确认来源。'},{'start':2,'end':4,'text':'再执行检查。'}]},ensure_ascii=False),encoding='utf-8')
        self.summary=self.root/'summary.json'
        self.summary.write_text(json.dumps({'artifacts_dir':str(self.root),'sources':[
            {'id':'s1','path':str(self.root/'视频.mp4')}]},ensure_ascii=False),encoding='utf-8')
        self.sources=analysis.catalog(self.summary);self.bundle=sample_bundle(self.sources)

    def test_valid_all_relation_types_and_render(self):
        self.assertEqual(analysis.validate(self.bundle,self.sources),[])
        path=self.root/'bundle.json';path.write_text(json.dumps(self.bundle,ensure_ascii=False),encoding='utf-8')
        out=analysis.build(path,self.summary,self.root/'out')
        for name in ('知识关系图.html','学习指南.html','001_内容分析.md','跨视频综合.md','验收记录.json'):
            self.assertTrue((out/name).is_file())
        page=(out/'知识关系图.html').read_text(encoding='utf-8')
        for kind in analysis.RELATIONS: self.assertIn(kind,page)
        self.assertIn('先确认来源。',page)

    def test_fake_quote_rejected(self):
        self.bundle['relations'][0]['evidence'][0]['quote']='原视频没有这句话'
        self.assertTrue(any('引文' in e for e in analysis.validate(self.bundle,self.sources)))

    def test_out_of_bounds_and_wrong_source(self):
        self.bundle['claims'][0]['evidence'][0]['end']=99
        self.bundle['claims'][1]['evidence'][0]['source_id']='other'
        errors=analysis.validate(self.bundle,self.sources)
        self.assertTrue(any('时间范围' in e for e in errors));self.assertTrue(any('未知来源' in e for e in errors))

    def test_changed_raw_hash_rejected(self):
        self.bundle['source_hashes']['s1']='old'
        self.assertTrue(any('哈希' in e for e in analysis.validate(self.bundle,self.sources)))

    def test_incomplete_reading_rejected(self):
        self.bundle['analyses'][0]['read_ranges']=[[0,1],[2,4]]
        self.assertTrue(any('缺口' in e for e in analysis.validate(self.bundle,self.sources)))

    def test_relation_without_evidence_rejected(self):
        self.bundle['relations'][0]['evidence']=[]
        self.assertTrue(any('缺少证据' in e for e in analysis.validate(self.bundle,self.sources)))

    def test_unbound_guide_rejected(self):
        del self.bundle['guide']['claim_bindings']['/steps/0/items/0/text']
        self.assertTrue(any('绑定' in e for e in analysis.validate(self.bundle,self.sources)))

    def test_no_edges_are_invented(self):
        self.bundle['relations']=[]
        self.assertEqual(analysis.validate(self.bundle,self.sources),[])
        out=self.root/'no-edges.html';analysis.render(self.bundle,self.sources,out)
        self.assertIn('未自动补边',out.read_text(encoding='utf-8'))

    def test_html_escaping(self):
        self.bundle['claims'][0]['text']='<script>alert(1)</script>'
        out=self.root/'escape.html';analysis.render(self.bundle,self.sources,out)
        page=out.read_text(encoding='utf-8')
        self.assertNotIn('<script>alert(1)</script>',page)
        self.assertIn('&lt;script&gt;',page)

    def test_nested_guide_input_rejected_without_crash(self):
        for value in ('bad',None,4,{'items':4}):
            bad=copy.deepcopy(self.bundle['guide']);bad['steps']=[value]
            errors,_,_=guide_builder.validate(bad)
            self.assertTrue(errors)

    def test_existing_analysis_output_preserved(self):
        path=self.root/'bundle.json';path.write_text(json.dumps(self.bundle),encoding='utf-8')
        out=self.root/'existing';out.mkdir();(out/'keep.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError,'拒绝覆盖'):
            analysis.build(path,self.summary,out)
        self.assertEqual((out/'keep.txt').read_text(),'keep')

    def test_visual_sampling_and_ocr_manifest(self):
        import visual_extract
        def command(args,timeout=120):
            if args[0]=='tesseract': return '机器字幕'
            Path(args[-1]).write_bytes(b'fake-frame')
            return ''
        with patch('media_tools.ffmpeg_path',return_value='ffmpeg'), \
             patch('media_tools.probe',return_value={'format':{'duration':4}}), \
             patch('visual_extract.shutil.which',return_value='tesseract'), \
             patch('visual_extract.command',side_effect=command):
            manifest=visual_extract.sample('sample.mp4',self.root/'visual',1,6,True,'640:360:0:0')
        self.assertEqual(manifest['coverage'],'sampled_frames_only')
        self.assertEqual(manifest['records'][0]['ocr_status'],'machine_unverified')
        self.assertTrue((self.root/'visual'/'frame-0000.txt').exists())

    def test_chunks_preserve_all_segments(self):
        plan=analysis.reading_chunks(self.sources,self.root/'chunks',max_chars=5)
        indices=[i for row in plan for i in row['segment_indexes']]
        self.assertEqual(indices,[0,1])
        self.assertEqual(plan[0]['start'],0)
        self.assertEqual(plan[-1]['end'],4)

    def test_empty_section_requires_reason(self):
        self.bundle['analyses'][0]['sections']['例外']=[]
        self.assertTrue(any('为空' in e for e in analysis.validate(self.bundle,self.sources)))
        self.bundle['analyses'][0]['section_notes']['例外']='原文未说明例外'
        self.assertEqual(analysis.validate(self.bundle,self.sources),[])

    def test_visual_missing_tool_error_is_explicit(self):
        with patch('media_tools.ffmpeg_path',return_value=None):
            with self.assertRaisesRegex(ValueError,'ffmpeg'):
                visual_extract.sample('missing','unused')

class SourceLookupTests(unittest.TestCase):
    def test_full_id_and_actual_index_target(self):
        import build_term_index, build_graph
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'video_title-abcd';source.mkdir()
            (source/'原始提取.md').write_text('[00:00] 概念甲 概念乙\n',encoding='utf-8')
            idx=build_term_index.scan(str(root),['概念甲','概念乙'],min_count=1)
            self.assertEqual(idx['概念甲']['hits'][0]['vid'],'video_title-abcd')
            page=build_term_index.build_html(idx,1,2,'test')
            self.assertIn('总索引.html#svideo_title-abcd-00-00',page)
            path=root/'index.json';path.write_text(json.dumps(idx,ensure_ascii=False),encoding='utf-8')
            nodes,edges=build_graph.build(str(path),str(root/'graph.html'),min_edge=1)
            self.assertEqual((nodes,edges),(2,1))
            self.assertIn('showSources',(root/'graph.html').read_text(encoding='utf-8'))

class HtmlScriptTests(unittest.TestCase):
    def test_guide_editor_is_script_not_visible_source(self):
        page=guide_builder.build_page({},'','const theme=1;','const editor=2;')
        self.assertIn('<script>const editor=2;</script>',page)

    def test_generated_index_scripts_parse(self):
        import contextlib,io,re,shutil,subprocess,sys
        import build_index
        if not shutil.which('node'): self.skipTest('node 不可用，跳过 JS 语法检查')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'sample';source.mkdir()
            (source/'原始提取.md').write_text('[00:00] 内容\n',encoding='utf-8')
            output=root/"index'quoted.html"
            with patch.object(sys,'argv',['build_index.py',str(root),str(output)]),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_index.main(),0)
            scripts=re.findall(r'<script[^>]*>(.*?)</script>',output.read_text(encoding='utf-8'),re.S)
            for i,script in enumerate(scripts):
                path=root/f'{i}.js';path.write_text(script,encoding='utf-8')
                r=subprocess.run(['node','--check',str(path)],capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stderr)

class AudioCompatibilityTests(unittest.TestCase):
    def test_only_known_incompatibility_uses_fallback(self):
        from unittest.mock import Mock
        import audio_input
        model=Mock();model.transcribe.side_effect=[TypeError("open() got an unexpected keyword argument 'metadata_errors'"),(['segment'],'info')]
        with patch('audio_input.decode_local',return_value='audio'):
            segments,info,decoder=audio_input.transcribe(model,'video',language='en')
        self.assertEqual(decoder,'ffmpeg-compat-fallback')
        self.assertEqual(model.transcribe.call_args.args[0],'audio')

    def test_unrelated_errors_not_hidden(self):
        from unittest.mock import Mock
        import audio_input
        model=Mock();model.transcribe.side_effect=TypeError('another failure')
        with patch('audio_input.decode_local') as decode:
            with self.assertRaises(TypeError): audio_input.transcribe(model,'video')
            decode.assert_not_called()

if __name__=='__main__': unittest.main()
