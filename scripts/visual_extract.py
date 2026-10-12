"""Local frame sampling and optional Tesseract OCR with honest coverage metadata."""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys


def command(args, timeout=120):
    r=subprocess.run([str(a) for a in args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if r.returncode: raise ValueError(r.stderr[-2000:] or '工具失败')
    return r.stdout


def sample(video,out,interval=60,max_frames=60,ocr=False,region=None,lang='chi_sim+eng'):
    if not math.isfinite(interval) or interval<=0 or max_frames<3: raise ValueError('interval 必须大于0，max_frames 至少3')
    from media_tools import ffmpeg_path, probe
    executable=ffmpeg_path()
    if not executable: raise ValueError('视觉提取需要本地 ffmpeg')
    data=probe(video)
    duration=float(data['format']['duration'])
    if not math.isfinite(duration) or duration<=0: raise ValueError('视频时长无效')
    root=Path(out)
    if root.exists() and any(root.iterdir()): raise ValueError('视觉输出目录非空，拒绝混入历史采样')
    root.mkdir(parents=True,exist_ok=True)
    end=max(0,duration-0.05)
    times=sorted(set([0,round(duration/2,3),round(end,3)]+[round(i*interval,3) for i in range(int(duration/interval)+1) if i*interval<end]))
    capped=len(times)>max_frames
    if capped: times=sorted(set(round(end*i/(max_frames-1),3) for i in range(max_frames)))
    if region:
        parts=region.split(':')
        if len(parts)!=4 or not all(x.isdigit() for x in parts) or int(parts[0])<=0 or int(parts[1])<=0:
            raise ValueError('region 格式 w:h:x:y，尺寸必须正整数')
    records=[]
    for i,t in enumerate(times):
        image=root/f'frame-{i:04d}.png'
        args=[executable,'-v','error','-ss',t,'-i',video,'-frames:v','1']
        if region: args+=['-vf','crop='+region]
        actual=t
        for seek in dict.fromkeys([t,max(0,t-0.5),max(0,t-1),0]):
            trial=list(args);trial[trial.index('-ss')+1]=seek
            command(trial+[image])
            if image.is_file():
                actual=seek
                break
        if not image.is_file(): raise ValueError('采样帧不存在：'+str(t))
        record={'requested_time':t,'sample_time':actual,'image':image.name,'ocr_status':'not_requested'}
        if ocr:
            if not shutil.which('tesseract'): raise ValueError('OCR 需要本地 tesseract 和对应语言数据')
            text=command(['tesseract',image,'stdout','-l',lang,'--psm','6'])
            txt=image.with_suffix('.txt');txt.write_text(text,encoding='utf-8')
            record.update({'ocr_status':'machine_unverified','text':txt.name})
        records.append(record)
    manifest={'source_path':str(Path(video).resolve()),'duration':duration,'requested_interval':interval,
              'capped':capped,'region':region,'records':records,
              'coverage':'sampled_frames_only','timestamp_kind':'sample_time_not_subtitle_bounds',
              'limitations':'采样不保证捕获短暂操作或全部字幕；OCR 未人工核对，不能替代完整转写'}
    (root/'visual.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    import html
    cards=''.join(f'<figure><a href="{html.escape(r["image"])}"><img loading="lazy" width="480" src="{html.escape(r["image"])}"></a><figcaption>{r["sample_time"]} 秒 · {r["ocr_status"]}</figcaption></figure>' for r in records)
    (root/'视觉核对.html').write_text('<!doctype html><meta charset="utf-8"><title>视觉采样核对</title><h1>视觉采样核对</h1><p>'+html.escape(manifest['limitations'])+'</p>'+cards,encoding='utf-8')
    return manifest


def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('video');ap.add_argument('out')
    ap.add_argument('--interval',type=float,default=60);ap.add_argument('--max-frames',type=int,default=60)
    ap.add_argument('--ocr',action='store_true');ap.add_argument('--region');ap.add_argument('--lang',default='chi_sim+eng')
    args=ap.parse_args(argv)
    try:
        sample(args.video,args.out,args.interval,args.max_frames,args.ocr,args.region,args.lang);return 0
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
        print(str(exc),file=sys.stderr);return 1

if __name__=='__main__': sys.exit(main())
