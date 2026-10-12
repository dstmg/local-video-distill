"""Resolve local media tools; never download binaries or inspect unrelated paths."""
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def ffmpeg_path():
    configured=os.environ.get('VIDEO_FFMPEG')
    if configured:
        if not Path(configured).is_file(): raise ValueError('VIDEO_FFMPEG 指向的文件不存在')
        return configured
    found=shutil.which('ffmpeg')
    if found: return found
    # imageio_ffmpeg bundles a local binary. No download operation is called.
    try:
        import imageio_ffmpeg
        candidate=imageio_ffmpeg.get_ffmpeg_exe()
        return candidate if Path(candidate).is_file() else None
    except (ImportError,RuntimeError):
        return None


def probe(video):
    executable=os.environ.get('VIDEO_FFPROBE') or shutil.which('ffprobe')
    if executable:
        r=subprocess.run([executable,'-v','error','-show_entries','format=duration:stream=index,codec_name,codec_type','-of','json',str(video)],
                         capture_output=True,text=True,encoding='utf-8',timeout=30)
        if r.returncode: raise ValueError('ffprobe 失败：'+r.stderr[-1500:])
        return json.loads(r.stdout)
    try:
        import av
    except ImportError as exc:
        raise ValueError('需要 ffprobe 或已安装的 PyAV 来探测视频') from exc
    with av.open(str(video)) as container:
        streams=[{'index':s.index,'codec_type':s.type,'codec_name':s.codec_context.name} for s in container.streams]
        duration=container.duration / av.time_base if container.duration else max(
            (float(s.duration*s.time_base) for s in container.streams if s.duration and s.time_base),default=0)
        return {'format':{'duration':duration},'streams':streams}
