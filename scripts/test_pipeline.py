import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / '课程 空格.mp4'
        self.video.write_bytes(b'fake-video')
        self.out = self.root / 'out'
        self.real_run = pipeline.run

    def fake_run(self, cmd, dry=False):
        if str(cmd[1]) == pipeline.TRANSCRIBE:
            dest = Path(cmd[3]); dest.mkdir(exist_ok=True)
            (dest / '原始提取.md').write_text('[00:00] 报款\n', encoding='utf-8')
            pipeline.atomic_json(dest / '原始提取.json', {'segments': [{'start':0,'end':1,'text':'报款'}]})
            return 0, ''
        return self.real_run(cmd, dry)

    def invoke(self, extras=(), runner=None):
        with patch.object(pipeline, 'pick_python', return_value=sys.executable), \
             patch.object(pipeline, 'run', side_effect=runner or self.fake_run), \
             contextlib.redirect_stdout(io.StringIO()):
            return pipeline.main([str(self.video), str(self.out), '--skip-check', *extras])

    def summary(self):
        return json.loads((self.out / 'summary.json').read_text(encoding='utf-8'))

    def test_preserves_raw_and_records_revision(self):
        self.assertEqual(self.invoke(), 0)
        s = self.summary(); key = s['sources'][0]['id']; run = Path(s['artifacts_dir'])
        self.assertIn('报款', (self.out/'逐字稿'/key/'原始提取.md').read_text(encoding='utf-8'))
        self.assertIn('爆款', (run/'校对稿'/key/'原始提取.md').read_text(encoding='utf-8'))
        revisions=json.loads((run/'修订记录.json').read_text(encoding='utf-8'))
        self.assertEqual(revisions[0]['start'], 0)
        self.assertEqual(s['analysis_status'], 'pending')
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.summary()['skipped'], 1)

    def test_changed_source_invalidates_cache(self):
        self.invoke(); self.video.write_bytes(b'changed')
        self.invoke(); self.assertEqual(self.summary()['success'],1)
        self.assertTrue((Path(self.summary()['artifacts_dir'])/'历史原稿').is_dir())

    def test_truncated_json_invalidates_cache(self):
        self.invoke(); key=self.summary()['sources'][0]['id']
        (self.out/'逐字稿'/key/'原始提取.json').write_text('{', encoding='utf-8')
        self.invoke(); self.assertEqual(self.summary()['success'],1)

    def test_model_change_invalidates_cache(self):
        self.invoke(); self.invoke(['--model','tiny'])
        self.assertEqual(self.summary()['success'],1)

    def test_downstream_failure_propagates(self):
        def runner(cmd, dry=False):
            if str(cmd[1]) == pipeline.TERM_INDEX:
                return 7, 'injected failure'
            return self.fake_run(cmd, dry)
        self.assertEqual(self.invoke(runner=runner),1)
        s=self.summary()
        self.assertTrue(any(x['status']=='blocked' for x in s['stages']))
        self.assertFalse((Path(s['artifacts_dir'])/'术语共现图.html').exists())

    def test_nonzero_transcribe_does_not_publish_outputs(self):
        def runner(cmd, dry=False):
            rc, out=self.fake_run(cmd,dry)
            return (1, 'failed after write') if str(cmd[1])==pipeline.TRANSCRIBE else (rc,out)
        self.assertEqual(self.invoke(['--no-index','--no-wiki'],runner),1)
        self.assertFalse((self.out/'逐字稿'/pipeline.vid_key(self.video)/'完成记录.json').exists())

    def test_dry_run_has_no_output(self):
        self.assertEqual(self.invoke(['--dry-run']),0)
        self.assertFalse(self.out.exists())

    def test_model_weights_change_invalidates_fingerprint(self):
        model=self.root/'model';model.mkdir()
        (model/'model.bin').write_bytes(b'old')
        first=pipeline.model_fingerprint(str(model))
        (model/'model.bin').write_bytes(b'new weights')
        self.assertNotEqual(first,pipeline.model_fingerprint(str(model)))

    def test_evidence_analysis_integrates_with_index(self):
        from test_analysis import sample_bundle
        import analysis_bundle
        self.assertEqual(self.invoke(),0)
        summary=self.out/'summary.json'
        bundle=sample_bundle(analysis_bundle.catalog(summary))
        content=self.root/'analysis.json'
        content.write_text(json.dumps(bundle,ensure_ascii=False),encoding='utf-8')
        self.assertEqual(self.invoke(['--analysis-json',str(content)]),0)
        s=self.summary();run=Path(s['artifacts_dir'])
        self.assertEqual(s['analysis_status'],'evidence_structure_validated')
        self.assertTrue((run/'内容分析'/'知识关系图.html').is_file())
        self.assertIn('虚构测试学习指南',(run/'总索引.html').read_text(encoding='utf-8'))

    def test_same_basename_is_distinct(self):
        self.assertNotEqual(pipeline.vid_key(self.root/'a'/'x.mp4'), pipeline.vid_key(self.root/'b'/'x.mp4'))

    def test_invalid_guide_reports_failure(self):
        content=self.root/'content.json';content.write_text('[]',encoding='utf-8')
        self.assertEqual(self.invoke(['--guide-json',str(content)]),1)
        self.assertEqual(self.summary()['analysis_status'],'pending')

class CorrectedCopyTests(unittest.TestCase):
    def test_unchanged_files_are_copied(self):
        import fix_terms
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            raw=root/'raw.md';raw.write_text('[00:00] 正确文本',encoding='utf-8')
            dest=root/'corrected.md'
            fix_terms.process_md(str(raw),[],False,str(dest))
            self.assertEqual(raw.read_bytes(),dest.read_bytes())
            data=root/'raw.json';data.write_text('{"segments":[]}',encoding='utf-8')
            target=root/'corrected.json'
            fix_terms.process_json(str(data),[],False,str(target))
            self.assertEqual(json.loads(target.read_text(encoding='utf-8')),{'segments':[]})

class SubtitleTests(unittest.TestCase):
    def test_srt_multiline_and_hour(self):
        from subtitles import parse_srt
        segs=parse_srt('1\n01:02:03,250 --> 01:02:04,500\n第一行\n第二行\n\n2\n01:02:05.000 --> 01:02:06.000\n<b>字幕</b>\n')
        self.assertEqual(len(segs),2)
        self.assertEqual(segs[0]['start'],3723.25)
        self.assertEqual(segs[0]['text'],'第一行 第二行')
        self.assertEqual(segs[1]['text'],'字幕')

    def test_missing_tool_falls_back(self):
        from subtitles import extract
        with patch('media_tools.ffmpeg_path',return_value=None):
            self.assertFalse(extract('missing.mp4','unused')[0])

if __name__=='__main__':
    unittest.main()
