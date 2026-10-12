#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — 一条龙：视频目录 → 转写 → 术语纠错 → 总索引页 → 知识关联层

用法:
    python pipeline.py <视频目录> <输出根目录> [选项]

示例:
    # 最简：转写目录里所有视频，出 HTML + 知识关联层
    python pipeline.py "G:/课程视频" ./out

    # 限量 + 指定模型
    python pipeline.py "G:/课程视频" ./out --limit 20 --model small

    # 只转写，不建索引/知识层
    python pipeline.py "G:/课程视频" ./out --no-index --no-wiki

选项:
    --limit N        最多处理 N 个视频（0 = 全部，默认 0）
    --model NAME     使用的模型（tiny/base/small/medium/large-v3 或本地目录，默认 small）
    --no-fix-terms   跳过术语纠错
    --no-index       跳过生成总索引页
    --no-wiki        跳过知识关联层（术语反向索引 + 知识图谱）
    --min-term N     术语至少出现几次才进索引（默认 2）
    --dry-run        只打印将要做的事，不实际执行
    --skip-check     跳过环境体检（更快，但可能跑到一半才发现缺依赖）

产出：逐字稿（原始机器输出）、运行记录/<run-id>/校对稿、修订记录、索引和共现图。
summary.json 指向最新运行，分别报告阶段状态与内容分析状态。
原稿默认不做纠错/繁简转换；--llm-config 自动分析，或显式传分析包/指南。
缓存核验源文件 SHA256、参数、提取器版本及两份原始产物，旧缓存无完成记录会重新提取。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import hashlib
from functools import lru_cache
import shutil
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSCRIBE = os.path.join(HERE, "transcribe.py")
FIX_TERMS = os.path.join(HERE, "fix_terms.py")
BUILD_INDEX = os.path.join(HERE, "build_index.py")
TERM_INDEX = os.path.join(HERE, "build_term_index.py")
BUILD_GRAPH = os.path.join(HERE, "build_graph.py")
DOCTOR = os.path.join(HERE, "doctor.py")

VIDEO_EXT = (".mp4", ".mkv", ".mov", ".avi", ".flv", ".m4v", ".mkv", ".webm", ".wmv")


def log(msg=""):
    print(msg, flush=True)


def hr(title=""):
    log()
    log("=" * 62)
    if title:
        log(f" {title}")
        log("=" * 62)


def run(cmd, dry=False):
    if dry:
        log(f"    [dry-run] {' '.join(str(c) for c in cmd[:3])} …")
        return 0, ""
    log(f"    $ {' '.join(str(c) for c in cmd[:3])} …")
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONUTF8="1"))
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def pick_python():
    """找一个能 import faster_whisper 的解释器；找不到就用当前 python。"""
    cands = []
    env = os.environ.get("VIDEO_PYTHON")
    if env:
        cands.append(env)
    venv = os.path.join(HERE, ".venv")
    if os.path.isdir(venv):
        for p in ("Scripts/python.exe", "bin/python"):
            cands.append(os.path.join(venv, p))
    cands += [sys.executable, "python", "python3"]

    for c in cands:
        try:
            r = subprocess.run([c, "-c", "import faster_whisper, av"],
                               capture_output=True, timeout=60)
            if r.returncode == 0:
                return c
        except Exception:  # noqa: BLE001
            continue
    return sys.executable


def find_videos(src):
    return sorted(str(p) for p in Path(src).rglob("*")
                  if p.is_file() and p.suffix.lower() in VIDEO_EXT)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=32)
def model_file_hash(path, size, mtime_ns):
    return digest(path)


def model_fingerprint(model):
    roots = [Path(model).expanduser()] if model and Path(model).expanduser().is_dir() else []
    # Include installed fallbacks so replacing a model at the same path invalidates cache.
    installed = Path.home() / "faster-whisper-models"
    if installed.is_dir(): roots += [p for p in installed.iterdir() if p.is_dir()]
    records = {}
    for root in roots:
        for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
            path = root / name
            if path.is_file():
                stat = path.stat()
                records[str(path.resolve())] = model_file_hash(str(path), stat.st_size, stat.st_mtime_ns)
    return records


def vid_key(path):
    return Path(path).stem[:32] + "-" + hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:12]


def valid_transcript(folder):
    try:
        data = json.loads((Path(folder) / "原始提取.json").read_text(encoding="utf-8"))
        md = (Path(folder) / "原始提取.md").read_text(encoding="utf-8")
        segs = data["segments"]
        previous = 0
        if not isinstance(segs, list) or not segs or not md.strip():
            return False
        for seg in segs:
            if not isinstance(seg.get("text"), str) or not seg["text"].strip():
                return False
            if not 0 <= seg["start"] <= seg["end"] or seg["start"] < previous:
                return False
            previous = seg["start"]
        from transcribe import fmt_ts
        expected = [(fmt_ts(x["start"]), x["text"]) for x in segs]
        import re
        actual = []
        for line in md.splitlines():
            match = re.match(r"^\[(\d+:\d{2}(?::\d{2})?)\]\s*(.*)$", line)
            if match:
                stamp = match[1]
                # Subtitle extractor emits HH:MM:SS even for short clips.
                if stamp.startswith("00:") and stamp.count(":") == 2:
                    stamp = stamp[3:]
                actual.append((stamp, match[2]))
        return actual == expected
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def reusable(folder, identity):
    try:
        data = json.loads((Path(folder) / "完成记录.json").read_text(encoding="utf-8"))
        return (data["identity"] == identity and valid_transcript(folder)
                and {"原始提取.md", "原始提取.json"} <= set(data["outputs"]) <= {"原始提取.md", "原始提取.json", "引擎原始字幕.srt"}
                and all(digest(Path(folder) / n) == h for n, h in data["outputs"].items()))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def atomic_json(path, data):
    temp = str(path) + ".tmp"
    Path(temp).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="一条龙：转写 → 术语纠错 → 总索引页",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="视频目录（或单个视频文件）")
    ap.add_argument("out", help="输出根目录")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 个（0=全部）")
    ap.add_argument("--lang", default="zh", help="ASR语言；auto 自动识别")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--model", default="", help="模型名或本地目录（默认自动找已下载的）")
    ap.add_argument("--no-fix-terms", action="store_true", help="跳过术语纠错")
    ap.add_argument("--no-index", action="store_true", help="跳过生成总索引页")
    ap.add_argument("--no-wiki", action="store_true",
                    help="跳过知识关联层（术语反向索引 + 知识图谱）")
    ap.add_argument("--min-term", type=int, default=2,
                    help="术语至少出现几次才进索引（默认 2）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不执行")
    ap.add_argument("--skip-check", action="store_true", help="跳过环境体检")
    ap.add_argument("--asr-only", action="store_true", help="忽略字幕轨，强制 ASR")
    ap.add_argument("--skill-bundle", action="store_true", help="自动蒸馏后生成本地知识技能包")
    ap.add_argument("--llm-config", help="启用本地模型或百炼云端自动蒸馏，配置 JSON 路径")
    ap.add_argument("--analysis-json", help="完整分析包，带来源哈希、关系与引文")
    ap.add_argument("--visual", action="store_true", help="本地关键帧采样")
    ap.add_argument("--ocr", action="store_true", help="采样帧追加本地 OCR（自动启用视觉采样）")
    ap.add_argument("--frame-interval", type=float, default=60)
    ap.add_argument("--max-frames", type=int, default=60)
    ap.add_argument("--ocr-region", help="采样区域 w:h:x:y")
    ap.add_argument("--guide-json", help="Agent 分析后的内容 JSON；严格格式校验再渲染")
    args = ap.parse_args(argv)
    if sum(bool(x) for x in (args.guide_json,args.analysis_json,args.llm_config)) > 1:
        ap.error("--guide-json、--analysis-json 与 --llm-config 只能选择一个")
    if args.skill_bundle and not args.llm_config:
        ap.error("--skill-bundle 当前需配合 --llm-config")
    if args.llm_config:
        from local_llm import load_config, Client
        try:
            config = load_config(args.llm_config)
            if not args.dry_run:
                Client(config).preflight()
        except (OSError, ValueError, TypeError) as exc:
            ap.error(str(exc))

    t0 = time.time()
    dry = args.dry_run

    hr("视频提取与自动蒸馏" if args.llm_config else "本地视频提取与索引 · 内容分析另行完成")
    if args.llm_config:
        log(" 分析模型：" + config['provider'] + " / " + config['model'])
        if config['provider'] == 'bailian':
            log(" 百炼云端模式：发送原稿片段/可选OCR文本，视频文件不上传。")
    log(f" 视频源：{args.src}")
    log(f" 输出到：{args.out}")

    # ---- Step 0：收集视频 ----
    if os.path.isfile(args.src):
        videos = [args.src]
        src_root = os.path.dirname(os.path.abspath(args.src))
    elif os.path.isdir(args.src):
        videos = find_videos(args.src)
        src_root = os.path.abspath(args.src)
    else:
        log(f"\n[错误] 找不到：{args.src}")
        return 2

    if not videos:
        log(f"\n[错误] 该目录下没找到视频（支持 {' '.join(VIDEO_EXT[:4])} …）")
        return 2

    total_found = len(videos)
    if args.limit > 0:
        videos = videos[: args.limit]
    log(f" 找到 {total_found} 个视频" + (f"，本次处理前 {len(videos)} 个" if args.limit else ""))

    transcript_dir = os.path.join(args.out, "逐字稿")
    artifacts_dir = os.path.join(args.out, "运行记录", time.strftime("%Y%m%d-%H%M%S") + "-" + str(time.time_ns()))
    if dry:
        log(json.dumps({"videos": videos, "out": args.out, "analysis": "pending"}, ensure_ascii=False))
        return 0
    os.makedirs(transcript_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    stats = {"found": total_found, "processed": len(videos), "success": 0,
             "skipped": 0, "failed": 0}
    failed_list = []
    stages = []
    sources = []
    corrected_dir = os.path.join(artifacts_dir, "校对稿")
    os.makedirs(corrected_dir, exist_ok=True)

    def execute(name, cmd, outputs=()):
        start = time.time()
        rc, output = run(cmd)
        if rc == 0 and any(not os.path.isfile(p) or os.path.getsize(p) == 0 for p in outputs):
            rc = 1
            output += "\n缺少预期产物"
        stages.append({"name": name, "status": "failed" if rc else "success", "returncode": rc,
                       "elapsed_sec": round(time.time()-start, 2), "log": output[-16000:]})
        return rc, output


    # ---- Step 1：环境体检 ----
    py = pick_python()
    if not args.skip_check and not dry:
        hr("Step 1/5 · 环境体检")
        rc, out = execute("environment", [py, DOCTOR])
        if rc == 1 and "核心依赖缺失" in out:
            stages[-1]["status"] = "warning"  # Subtitle-only extraction need not install ASR.
        core_ok = "核心依赖齐全" in out
        if not core_ok:
            log("  [警告] 核心依赖可能不全，继续尝试（失败的视频会跳过）")
            log("  提示：可先运行  python setup.py")

    # ---- Step 2：转写 ----
    hr("Step 2/5 · 转写")
    model_files = model_fingerprint(args.model)
    model_arg = (["--model", args.model] if args.model else []) + (["--asr-only"] if args.asr_only else []) + ["--lang", args.lang, "--device", args.device, "--compute-type", args.compute_type]

    for i, v in enumerate(videos, 1):
        key = vid_key(v)
        dest = os.path.join(transcript_dir, key)
        md = os.path.join(dest, "原始提取.md")

        identity = {"path": os.path.realpath(v), "sha256": digest(v), "model": args.model,
                    "transcriber_sha256": digest(TRANSCRIBE), "asr_only": args.asr_only, "local_models": model_files,
                    "language": args.lang, "device": args.device, "compute_type": args.compute_type,
                    "subtitle_extractor_sha256": digest(os.path.join(HERE, "subtitles.py")),
                    "media_tools_sha256": digest(os.path.join(HERE, "media_tools.py")),
                    "audio_input_sha256": digest(os.path.join(HERE, "audio_input.py"))}
        if reusable(dest, identity):
            stats["skipped"] += 1
        else:
            os.makedirs(dest, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=artifacts_dir) as tmp:
                rc, out = execute("transcribe:" + os.path.basename(v), [py, TRANSCRIBE, v, tmp] + model_arg)
                if rc != 0 or not valid_transcript(tmp):
                    stats["failed"] += 1
                    failed_list.append(os.path.basename(v))
                    stages.append({"name": "transcript-validation:" + key, "status": "failed", "log": "转写失败或产物不完整"})
                    continue
                if os.listdir(dest):
                    shutil.copytree(dest, os.path.join(artifacts_dir, "历史原稿", key))
                for name in ("原始提取.md", "原始提取.json", "引擎原始字幕.srt"):
                    if not os.path.isfile(os.path.join(tmp, name)):
                        if name == "引擎原始字幕.srt" and os.path.isfile(os.path.join(dest, name)):
                            os.remove(os.path.join(dest, name))  # Already preserved in this run history.
                        continue
                    shutil.copy2(os.path.join(tmp, name), os.path.join(dest, name))
                atomic_json(os.path.join(dest, "完成记录.json"), {"identity": identity,
                    "outputs": {n: digest(os.path.join(dest, n)) for n in ("原始提取.md", "原始提取.json", "引擎原始字幕.srt") if os.path.isfile(os.path.join(dest, n))}})
                stats["success"] += 1
        raw_meta = json.loads(Path(dest, "原始提取.json").read_text(encoding="utf-8"))
        sources.append({"id": key, "title": Path(v).stem, "method": raw_meta.get("method", "asr"),
                        "actual_model": raw_meta.get("model"), **identity})
        shutil.copytree(dest, os.path.join(corrected_dir, key))
        shutil.copytree(dest, os.path.join(artifacts_dir, "原稿快照", key))
        if args.visual or args.ocr:
            cmd = [py, os.path.join(HERE, "visual_extract.py"), v,
                   os.path.join(artifacts_dir, "视觉资料", key), "--interval", args.frame_interval,
                   "--max-frames", args.max_frames]
            if args.ocr: cmd.append("--ocr")
            if args.ocr_region: cmd += ["--region", args.ocr_region]
            execute("visual:"+key, cmd, [os.path.join(artifacts_dir, "视觉资料", key, "visual.json")])

    # ---- Step 3：术语纠错 ----
    if not args.no_fix_terms and sources:
        hr("Step 3/5 · 术语纠错")
        if dry:
            log(f"    [dry-run] python fix_terms.py {transcript_dir}")
        else:
            rc, out = execute("term-correction", [sys.executable, FIX_TERMS, corrected_dir])
            for line in (out or "").splitlines():
                if "共替换" in line or "已加载" in line:
                    log(f"  {line.strip()}")

    from fix_terms import load_fixes
    term_rules = load_fixes() if not args.no_fix_terms else []
    atomic_json(os.path.join(artifacts_dir, "术语规则快照.json"), term_rules)
    revisions = []
    for source in sources:
        key = source["id"]
        old = json.loads(Path(transcript_dir, key, "原始提取.json").read_text(encoding="utf-8"))
        new = json.loads(Path(corrected_dir, key, "原始提取.json").read_text(encoding="utf-8"))
        for before, after in zip(old["segments"], new["segments"]):
            if before["text"] != after["text"]:
                revisions.append({"source_id": key, "start": before["start"], "end": before["end"],
                    "original": before["text"], "corrected": after["text"], "basis": "术语表自动替换，未人工核对",
                    "candidate_rules": [{"wrong":w,"right":r} for w,r in term_rules if w in before["text"]]})
    atomic_json(os.path.join(artifacts_dir, "修订记录.json"), revisions)
    guide_path = os.path.join(artifacts_dir, "学习指南.html")
    analysis_status = "pending"
    if sources:
        # Frozen source catalog is usable independently of the mutable raw cache.
        draft_summary = {"sources": sources, "artifacts_dir": os.path.abspath(artifacts_dir)}
        atomic_json(os.path.join(artifacts_dir, "sources.json"), draft_summary)
        from analysis_bundle import catalog, template, reading_chunks
        raw_sources = catalog(os.path.join(artifacts_dir, "sources.json"))
        draft = template(raw_sources)
        reading_chunks(raw_sources, os.path.join(artifacts_dir, "阅读分块"))
        atomic_json(os.path.join(artifacts_dir, "分析包待填写.json"), draft)
        if args.llm_config:
            generated = os.path.join(artifacts_dir, "自动蒸馏")
            rc, out = execute("auto-distill", [sys.executable, os.path.join(HERE, "auto_distill.py"),
                "--summary", os.path.join(artifacts_dir, "sources.json"), "--config", args.llm_config,
                "--out", generated, "--cache", os.path.join(args.out, "模型缓存")] + (["--skill-bundle"] if args.skill_bundle else []),
                [os.path.join(generated, "产物", "知识关系图.html"),os.path.join(generated, "产物", "学习指南.html")])
            if rc == 0:
                guide_path = os.path.join(generated, "产物", "学习指南.html")
                analysis_status = "auto_generated_evidence_validated"
        if args.analysis_json:
            rc, out = execute("evidence-analysis", [sys.executable, os.path.join(HERE, "analysis_bundle.py"),
                "--summary", os.path.join(artifacts_dir, "sources.json"), "--analysis", args.analysis_json,
                "--out", os.path.join(artifacts_dir, "内容分析")],
                [os.path.join(artifacts_dir, "内容分析", "知识关系图.html")])
            if rc == 0:
                guide_path = os.path.join(artifacts_dir, "内容分析", "学习指南.html")
                analysis_status = "evidence_structure_validated"
    if args.guide_json and sources:
        rc, out = execute("guide", [sys.executable, os.path.join(HERE, "guide_builder.py"),
            args.guide_json, "-o", guide_path, "--strict"], [guide_path])
        if rc == 0:
            analysis_status = "supplied_and_format_validated"

    # ---- Step 4：总索引页 ----
    index_path = os.path.join(artifacts_dir, "总索引.html")
    if not args.no_index and sources:
        hr("Step 4/5 · 生成总索引页")
        if dry:
            log(f"    [dry-run] python build_index.py {transcript_dir} {index_path}")
        else:
            cmd = [sys.executable, BUILD_INDEX, corrected_dir, index_path,
                   "--src-dir", src_root]
            if analysis_status in ("supplied_and_format_validated", "evidence_structure_validated", "auto_generated_evidence_validated"):
                cmd += ["--guide", guide_path]
            rc, out = execute("index", cmd, [index_path])
            for line in (out or "").splitlines()[:4]:
                if line.strip():
                    log(f"  {line.strip()}")

    # ---- Step 5（可选）：知识关联层 ----
    term_index = None
    graph = None
    if not args.no_wiki and sources:
        hr("Step 5/5 · 知识关联层（术语索引 + 知识图谱）")
        idx_path = os.path.join(artifacts_dir, "术语索引.json")
        term_index = os.path.join(artifacts_dir, "术语反向索引.html")
        graph = os.path.join(artifacts_dir, "术语共现图.html")
        if dry:
            log(f"    [dry-run] build_term_index.py {transcript_dir}")
            log(f"    [dry-run] build_graph.py {idx_path}")
        else:
            rc, out = execute("term-index", [sys.executable, TERM_INDEX, corrected_dir,
                           "-o", term_index, "--json", idx_path,
                           "--min-count", str(args.min_term)], [term_index, idx_path])
            for line in (out or "").splitlines():
                if "收录术语" in line or "总命中" in line:
                    log(f"  {line.strip()}")
            rc2, out2 = execute("cooccurrence-graph", [sys.executable, BUILD_GRAPH, idx_path, "-o", graph], [graph]) if rc == 0 else (1, "前置索引失败，未生成图谱")
            if rc != 0:
                stages.append({"name": "cooccurrence-graph", "status": "blocked", "log": "前置索引失败"})
            for line in (out2 or "").splitlines()[:3]:
                if "个节点" in line:
                    log(f"  {line.strip()}")

    # ---- 汇总 ----
    hr("完成")
    log(f" 找到视频  ：{stats['found']}")
    log(f" 成功转写  ：{stats['success']}")
    log(f" 已存在跳过：{stats['skipped']}")
    log(f" 失败      ：{stats['failed']}")
    if failed_list:
        log(f" 失败清单  ：{', '.join(failed_list[:5])}"
            + ("…" if len(failed_list) > 5 else ""))
        log(f" 失败原因多半是：模型未下载 / 视频无音轨 / 格式不支持")
        log(f" 可先跑  python doctor.py  检查环境")
    log(f" 耗时      ：{time.time() - t0:.1f} 秒")
    log()
    log(f" 逐字稿    ：{transcript_dir}")
    log(f" 学习产物  ：{artifacts_dir}")
    if term_index:
        log(f" 术语索引  ：{os.path.basename(term_index)}")
    if graph:
        log(f" 知识图谱  ：{os.path.basename(graph)}")

    stats.update({"elapsed_sec": round(time.time()-t0, 1), "failed_list": failed_list,
                  "sources": sources, "stages": stages, "analysis_status": analysis_status,
                  "semantic_verification": "not_performed", "artifacts_dir": os.path.abspath(artifacts_dir)})
    if args.llm_config:
        stats['llm_provider'] = config['provider']
        stats['privacy'] = 'text_to_bailian_cloud' if config['provider']=='bailian' else 'loopback_only'
        model_state = Path(artifacts_dir, '自动蒸馏', '自动蒸馏状态.json')
        if model_state.is_file():
            stats['llm_usage'] = json.loads(model_state.read_text(encoding='utf-8')).get('usage', {})
    failed = stats["failed"] > 0 or any(x["status"] == "failed" for x in stages)
    stats["status"] = "failed" if failed else "success"
    summary_file = os.path.join(artifacts_dir, "summary.json")
    latest_summary = os.path.join(args.out, "summary.json")
    atomic_json(summary_file, stats)
    atomic_json(latest_summary, stats)
    try:
        from build_entry import build
        started = time.time()
        entry = build(summary_file)
        latest_entry = build(summary_file, os.path.join(args.out, "结果入口.html"))
        stages.append({"name": "result-entry", "status": "success", "elapsed_sec": round(time.time()-started, 2)})
        stats['result_entry'] = str(latest_entry)
        stats['run_entry'] = str(entry)
        log(" 打开结果：" + str(latest_entry))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        stages.append({"name": "result-entry", "status": "failed", "log": str(exc)})
        failed = True
        stats['status'] = "failed"
    atomic_json(summary_file, stats)
    atomic_json(latest_summary, stats)
    log("提取流程：" + stats["status"] + "；内容分析：" + analysis_status)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
