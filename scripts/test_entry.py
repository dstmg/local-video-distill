import json
from pathlib import Path
import tempfile
import unittest
from build_entry import build


class EntryTests(unittest.TestCase):
    def test_pending_escapes_logs_and_omits_missing_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            summary=root/'summary.json'
            summary.write_text(json.dumps({'sources':[], 'status':'failed',
                'stages':[{'name':'<script>alert(1)</script>','status':'failed','log':'<img onerror=bad>'}]}),encoding='utf-8')
            page=build(summary).read_text(encoding='utf-8')
            self.assertIn('流程有失败阶段',page)
            self.assertNotIn('<img onerror=bad>',page)
            self.assertNotIn('href="学习指南.html"',page)
            self.assertIn('本次尚未生成',page)

    def test_ready_links_to_existing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);result=root/'result';result.mkdir()
            (result/'学习指南.html').write_text('guide',encoding='utf-8')
            summary=root/'summary.json'
            summary.write_text('{"sources":[]}',encoding='utf-8')
            page=build(summary,root/'index.html',result,True).read_text(encoding='utf-8')
            self.assertIn('分析产物已生成',page)
            self.assertIn('result/%E5%AD%A6%E4%B9%A0%E6%8C%87%E5%8D%97.html',page)

if __name__=='__main__':unittest.main()
