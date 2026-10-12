"""Optional text subtitle extraction; bitmap/hard subtitles require a separate OCR pass."""
import json
from pathlib import Path
import re
import shutil
import subprocess


def parse_srt(text):
    pattern = r'(\d+:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)'
    def seconds(value):
        h, m, s = value.replace(',', '.').split(':')
        return int(h)*3600 + int(m)*60 + float(s)
    segments=[]
    for match in re.finditer(pattern, text.replace('\r\n','\n'), re.S):
        start,end=seconds(match[1]),seconds(match[2])
        content=re.sub(r'<[^>]*>', '', match[3]).strip().replace('\n',' ')
        if content and 0 <= start <= end:
            segments.append({'start':start, 'end':end, 'text':content})
    return segments


def extract(video, output):
    from media_tools import ffmpeg_path, probe
    try:
        executable=ffmpeg_path()
        if not executable:
            return False, 'ffmpeg 不可用；回退 ASR'
        metadata=probe(video)
        streams=[s for s in metadata['streams'] if s.get('codec_type')=='subtitle']
        for stream in streams:
            result=subprocess.run([executable,'-v','error','-i',str(video),'-map',
                                   '0:'+str(stream['index']),'-f','srt','pipe:1'],
                                  capture_output=True, text=True, encoding='utf-8', timeout=120)
            segments=parse_srt(result.stdout) if result.returncode==0 else []
            if not segments:
                continue
            root=Path(output);root.mkdir(parents=True,exist_ok=True)
            (root/'引擎原始字幕.srt').write_text(result.stdout,encoding='utf-8')
            def stamp(t):
                t=int(t);return f'{t//3600:02d}:{t%3600//60:02d}:{t%60:02d}'
            (root/'原始提取.md').write_text(''.join(f"[{stamp(s['start'])}] {s['text']}\n" for s in segments),encoding='utf-8')
            (root/'原始提取.json').write_text(json.dumps({'method':'embedded-subtitle',
                'stream_index':stream['index'],'codec':stream.get('codec_name'),
                'duration':float(metadata['format']['duration']),
                'completeness':'字幕可能省略口述；未人工核对','segments':segments},ensure_ascii=False,indent=2),encoding='utf-8')
            return True, '已提取内嵌文字字幕（未人工核对）'
        return False, '没有可用文字字幕；硬字幕/图片字幕需另行 OCR，回退 ASR'
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return False, '字幕提取失败；回退 ASR：'+str(exc)
