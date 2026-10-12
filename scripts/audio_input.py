"""Narrow fallback for PyAV versions incompatible with faster-whisper's metadata_errors."""
import subprocess


def decode_local(video):
    from media_tools import ffmpeg_path
    executable=ffmpeg_path()
    if not executable: raise ValueError('PyAV 解码接口不兼容，且没有可用的本地 ffmpeg')
    result=subprocess.run([executable,'-v','error','-i',str(video),'-f','f32le','-ac','1','-ar','16000','pipe:1'],
                          capture_output=True)
    if result.returncode: raise ValueError(result.stderr.decode('utf-8',errors='replace')[-2000:])
    import numpy as np
    audio=np.frombuffer(result.stdout,dtype=np.float32)
    if not audio.size: raise ValueError('解码后音频为空')
    return audio


def transcribe(model,video,**options):
    try:
        segments,info=model.transcribe(video,**options)
        return segments,info,'pyav'
    except TypeError as exc:
        if "metadata_errors" not in str(exc) or 'unexpected keyword' not in str(exc): raise
        audio=decode_local(video)
        segments,info=model.transcribe(audio,**options)
        return segments,info,'ffmpeg-compat-fallback'
