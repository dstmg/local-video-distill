#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcribe.py — 视频转 MT（跨平台：Windows / macOS / Linux，无 bash 依赖）

用法：
    python transcribe.py                      # 用下面默认配置
    python transcribe.py 视频.mp4              # 指定输入
    python transcribe.py 视频.mp4 输出目录      # 指定输入+输出目录

产物（写入输出目录）：
    原始提取.md    带时间戳纯文本
    原始提取.json  结构化 segments

前置：先跑 python doctor.py 确认依赖齐全。
说明：faster-whisper 靠 PyAV 在 Python 内解码视频，**不需要 ffmpeg**，视频文件可直接喂。
"""
import argparse
import json
import os
import sys

# 国内网络：默认走 HuggingFace 镜像（避免官方源下载失败/极慢）。
# 若你身处可直连环境，想用官方源，把下面这行改成 USE_MIRROR = False。
USE_MIRROR = True
if USE_MIRROR and not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

VIDEO = "video.mp4"          # ← 改成你的视频路径

# 模型：可填模型名（tiny/base/small/medium/large-v3）或本地目录绝对路径。
# 推荐先跑 bash download_model.sh <模型名> 下到本地目录再填路径 ——
# 因为 hf-mirror 的 307 重定向会让 huggingface_hub 下载中断留下 0 字节文件，
# 之后加载报 "json parse error: unexpected end of input"（极难排查）。
MODEL = ""                    # ← 留空则用 LOCAL_MODEL_DIR

LOCAL_MODEL_DIR = os.path.expanduser("~/faster-whisper-models/small")
OUTPUT_DIR = "transcript"    # ← 转写产物输出目录
LANGUAGE = "zh"              # ← None 表示自动检测语言

# 若 LOCAL_MODEL_DIR 里有完整模型就用它，否则回落到 MODEL 名字（触发在线加载）
if not MODEL and os.path.isfile(os.path.join(LOCAL_MODEL_DIR, "model.bin")):
    MODEL = LOCAL_MODEL_DIR
if not MODEL:
    MODEL = "small"

# CPU 通用配置；GPU 用户可改成 device="cuda", compute_type="float16"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

# 繁体→简体：Whisper 对中文有时会输出繁体（如"電商人""鏈接"）。
# 设为 True 可自动转简体。需要：pip install opencc-python-reimplemented
TO_SIMPLIFIED = False
_SIMPLIFIER = None

# 术语纠错：faster-whisper 对电商专有名词识别率低（"跟投"→"跟头"、"爆款"→"报款"）。
# 设为 True 时加载 terms_*.json 做 ASR 后字符串替换。
TO_FIX_TERMS = False
_TERM_FIXES = None  # [(错词, 正词), ...] 长词优先


def load_term_fixes():
    """加载术语纠错表，返回按长度降序的 [(错, 对)] 列表（长词优先，避免短词破坏长词）。

    查找顺序：scripts/terms_custom.json（用户自定义优先）→ scripts/terms_*.json
              → ../examples/terms_*.example.json（示例表）
    想用自己的领域术语，把 terms_custom.json 放到 scripts/ 下即可。
    """
    global _TERM_FIXES
    if _TERM_FIXES is not None:
        return _TERM_FIXES
    _TERM_FIXES = []
    here = os.path.dirname(os.path.abspath(__file__))
    ex_dir = os.path.join(os.path.dirname(here), "examples")

    candidates = []
    custom = os.path.join(here, "terms_custom.json")
    if os.path.isfile(custom):
        candidates.append(custom)
    for d in (here, ex_dir):
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if (name.startswith("terms_") and name.endswith(".json")
                    and name != "terms_custom.json"):
                candidates.append(os.path.join(d, name))

    try:
        for path in candidates:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for group, mapping in data.items():
                if group.startswith("_") or not isinstance(mapping, dict):
                    continue
                for wrong, right in mapping.items():
                    if wrong and right and wrong != right:
                        _TERM_FIXES.append((wrong, right))
        # 长词优先
        _TERM_FIXES.sort(key=lambda x: -len(x[0]))
    except Exception:  # noqa: BLE001
        _TERM_FIXES = []
    return _TERM_FIXES


def fix_terms(text: str):
    """按术语表纠错，返回 (新文本, 替换次数)。"""
    fixes = load_term_fixes()
    if not fixes:
        return text, 0
    n = 0
    for wrong, right in fixes:
        if wrong in text:
            cnt = text.count(wrong)
            text = text.replace(wrong, right)
            n += cnt
    return text, n


def to_simplified(text: str) -> str:
    """繁体转简体（惰性加载 opencc，失败则原样返回）。"""
    global _SIMPLIFIER
    if _SIMPLIFIER is None:
        try:
            from opencc import OpenCC
            _SIMPLIFIER = OpenCC("t2s")
        except Exception:  # noqa: BLE001
            _SIMPLIFIER = False  # 标记为不可用，避免反复尝试
    if _SIMPLIFIER is False:
        return text
    try:
        return _SIMPLIFIER.convert(text)
    except Exception:  # noqa: BLE001
        return text

# 模型体积提示（仅用于首次下载前告知用户）
MODEL_SIZE_HINT = {
    "tiny": "75MB", "base": "145MB", "small": "480MB",
    "medium": "1.5GB", "large-v3": "3GB",
}.get(MODEL, "视模型而定")

# 模型体积（用于完整性判断）
MODEL_MIN_BYTES = {
    "tiny": 60 * 1024 * 1024,
    "base": 120 * 1024 * 1024,
    "small": 400 * 1024 * 1024,
    "medium": 1200 * 1024 * 1024,
    "large-v3": 2500 * 1024 * 1024,
}

# 降级顺序：模型加载失败时自动往下试（体积更小 = 更快）
FALLBACK_ORDER = ["medium", "small", "base", "tiny"]

# faster-whisper 的 WhisperModel 构造器：
#   WhisperModel(model_path, device="cpu", device_index=0, compute_type="default", ...)
# 注意第二个位置参数是 device_index，**不是** compute_type —— 必须用关键字参数，
# 否则 int8 会被误传给 device_index 导致构造失败。
_WhisperModel = None


def build_model(model_path_or_name: str):
    """统一构造 WhisperModel（务必用关键字传 device/compute_type）。"""
    global _WhisperModel
    if _WhisperModel is None:
        from faster_whisper import WhisperModel
        _WhisperModel = WhisperModel
    return _WhisperModel(model_path_or_name,
                         device=DEVICE,
                         compute_type=COMPUTE_TYPE)


def find_cached_model_dir(name: str):
    """在 HF 缓存里找模型目录，并校验完整性（必须有足够大的 model.bin）。"""
    roots = [os.environ.get("HF_HOME"),
             os.path.join(os.path.expanduser("~"), ".cache", "huggingface")]
    need = MODEL_MIN_BYTES.get(name, 0)
    for root in roots:
        if not root:
            continue
        hub = os.path.join(root, "hub")
        if not os.path.isdir(hub):
            continue
        for entry in os.listdir(hub):
            if not entry.startswith("models--Systran--faster-whisper-"):
                continue
            if not entry.endswith(name):
                continue
            base = os.path.join(hub, entry)
            snapshots = os.path.join(base, "snapshots")
            if not os.path.isdir(snapshots):
                continue
            for snap in os.listdir(snapshots):
                binf = os.path.join(snapshots, snap, "model.bin")
                real = os.path.realpath(binf)  # 跟随 symlink
                if os.path.isfile(real) and (not need or os.path.getsize(real) >= need):
                    return os.path.join(snapshots, snap)
    return None


def load_model_with_fallback(name: str):
    """加载模型：优先本地完整缓存(离线) → 在线下载 → 失败则自动降级到更小模型。"""
    tried = []
    order = [name] + [m for m in FALLBACK_ORDER if m != name]

    for cand in order:
        cached = find_cached_model_dir(cand)
        # 1) 本地有完整缓存 → 离线加载，最快最稳
        if cached:
            print(f"      使用本地已缓存模型：{cand}")
            try:
                return build_model(cached), cand
            except Exception as e:  # noqa: BLE001
                print(f"      本地缓存加载失败（{type(e).__name__}），尝试下一个…")
                tried.append((cand, f"本地缓存损坏: {e}"))
                continue
        # 2) 尝试按名字加载（可能触发下载）
        print(f"      加载模型 {cand}（本地无完整缓存，可能需要下载 {MODEL_SIZE_HINT if cand==name else ''}）…")
        try:
            return build_model(cand), cand
        except Exception as e:  # noqa: BLE001
            print(f"      [x] {cand} 加载失败：{type(e).__name__}")
            tried.append((cand, str(e)[:120]))

    print("\n[错误] 所有候选模型都加载失败：", file=sys.stderr)
    for m, err in tried:
        print(f"    - {m}: {err}", file=sys.stderr)

    # 识别 ctranslate2 的误导性报错：它读模型失败时也会抛 JSON parse error，
    # 容易被误以为是网络/JSON 问题，实际多为"文件被占用/安全软件锁定/磁盘读取失败"。
    blob = " ".join(e for _m, e in tried)
    if "parse error" in blob or "json.exception" in blob:
        print("\n[诊断] ctranslate2 读取模型二进制时失败。", file=sys.stderr)
        print("       （注意：这常被误报为 JSON/网络问题，实际不是。）", file=sys.stderr)
        print("       常见原因与对策：", file=sys.stderr)
        print("         1) 模型文件正被其他进程占用 → 关掉正在用它的程序后重试", file=sys.stderr)
        print("         2) 被杀毒/安全软件锁定 → 把模型目录加入白名单，或换个目录重下", file=sys.stderr)
        print("         3) 缓存文件下载不完整 → 删除模型缓存目录后重跑本脚本（会重新下载）", file=sys.stderr)
        print("            Windows: rmdir /s /q \"%USERPROFILE%\\.cache\\huggingface\\hub\\models--Systran--faster-whisper-<模型名>\"",
              file=sys.stderr)
        print("         4) 内存不足 → 关掉占内存的程序后重试", file=sys.stderr)
        print("         5) 跨盘符 symlink 读取异常 → 用 MODEL 直接指定本地模型目录路径",
              file=sys.stderr)

    print("\n解决办法（按顺序试）：", file=sys.stderr)
    print("  1) 国内网络：设置镜像后重跑", file=sys.stderr)
    print('     set HF_ENDPOINT=https://hf-mirror.com        (Windows CMD)', file=sys.stderr)
    print('     $env:HF_ENDPOINT="https://hf-mirror.com"    (PowerShell)', file=sys.stderr)
    print('     export HF_ENDPOINT=https://hf-mirror.com    (macOS/Linux)', file=sys.stderr)
    print("  2) 手动下载模型到本地目录，再把 MODEL 设成该目录路径（离线可用）", file=sys.stderr)
    print("     例如把 Systran/faster-whisper-tiny 下载解压后，MODEL 设为该目录绝对路径", file=sys.stderr)
    raise SystemExit(3)


def fmt_ts(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def probe_streams(video: str):
    """用 PyAV 探测视频码流，返回 (stream_types, has_audio)。探测失败返回 (None, None)。"""
    try:
        import av
        with av.open(video) as container:
            types = [s.type for s in container.streams]
        return types, ("audio" in types)
    except Exception:  # noqa: BLE001
        return None, None


def probe_subtitle_track(video: str):
    """探测是否有内嵌字幕轨（有则提醒用户可走更省算力的抽轨路径）。"""
    types, _ = probe_streams(video)
    return types


def main():
    global VIDEO, OUTPUT_DIR, MODEL, LANGUAGE, DEVICE, COMPUTE_TYPE

    # 命令行参数（覆盖文件顶部配置；不传则用顶部配置）
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("video", nargs="?", help="视频路径")
    ap.add_argument("outdir", nargs="?", help="输出目录")
    ap.add_argument("--asr-only", action="store_true", help="跳过字幕提取，强制 ASR")
    ap.add_argument("--model", help="模型名或本地目录路径")
    ap.add_argument("--lang", help="语言码，如 zh / en；auto 表示自动检测")
    ap.add_argument("--device", help="cpu / cuda")
    ap.add_argument("--compute-type", help="int8 / float16 / int8_float16 等")
    ap.add_argument("-h", "--help", action="help", help="显示帮助")
    known, _unknown = ap.parse_known_args()

    if known.video:
        VIDEO = known.video
    if known.outdir:
        OUTPUT_DIR = known.outdir
    if known.model:
        MODEL = known.model
    if known.lang:
        LANGUAGE = None if known.lang.lower() in ("auto", "none", "") else known.lang
    if known.device:
        DEVICE = known.device
    if known.compute_type:
        COMPUTE_TYPE = known.compute_type

    # 路径容错：
    # 1) 支持 glob 通配（避免手输长文件名出错）
    # 2) 抖音下载的视频名常含 `#标签`，在 shell 里 # 是注释符会被截断——这里做提示
    if not os.path.isfile(VIDEO):
        import glob as _glob
        matches = [p for p in _glob.glob(VIDEO) if os.path.isfile(p)]
        if len(matches) == 1:
            VIDEO = matches[0]
        elif len(matches) > 1:
            print(f"[错误] 通配符匹配到 {len(matches)} 个文件，请指定更精确的路径：", file=sys.stderr)
            for m in matches[:5]:
                print(f"    {m}", file=sys.stderr)
            return 2
        else:
            print(f"[错误] 找不到视频文件：{VIDEO}", file=sys.stderr)
            print("用法：python transcribe.py <视频路径> [输出目录]", file=sys.stderr)
            if "#" in VIDEO:
                print("\n提示：路径里含 `#`，在 bash/shell 中会被当作注释符截断。", file=sys.stderr)
                print("      解决办法：① 用单引号包住整个路径 ② 改用通配符（脚本支持 glob）", file=sys.stderr)
                print("      例：python transcribe.py 'G:/某目录/7584794*' 输出目录", file=sys.stderr)
            return 2

    if not known.asr_only:
        from subtitles import extract
        extracted, message = extract(VIDEO, OUTPUT_DIR)
        print("[字幕] " + message)
        if extracted:
            return 0

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("[错误] 未安装 faster-whisper。请先运行：python doctor.py 查看修复方法",
              file=sys.stderr)
        return 1

    # 提前检查：没有音频流就别白费模型加载时间
    types, has_audio = probe_streams(VIDEO)
    if has_audio is False:
        print(f"[错误] 该视频没有音频流，无法转写。", file=sys.stderr)
        print(f"       探测到的码流：{types}", file=sys.stderr)
        print("       可能是纯画面/无声视频，或音轨损坏。", file=sys.stderr)
        return 4
    if has_audio is None:
        print("[警告] 无法探测码流（文件可能损坏或编码特殊），继续尝试…")

    # 友好提醒：若视频自带内嵌字幕轨，抽轨比 ASR 快且免费
    if types and "subtitle" in types:
        print("[提示] 检测到内嵌字幕轨。若想更省钱，可改用：")
        print("       ffmpeg -i \"%s\" -map 0:s:0 -c copy 字幕.srt" % VIDEO)
        print("       下面仍继续走 ASR（对字幕质量差的视频反而更准）。\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    md_path = os.path.join(OUTPUT_DIR, "原始提取.md")
    json_path = os.path.join(OUTPUT_DIR, "原始提取.json")

    print(f"[1/3] 加载模型（优先 {MODEL}）")
    if not USE_MIRROR:
        print("      提示：未启用国内镜像，首次下载可能很慢/失败。")
    try:
        model, used_model = load_model_with_fallback(MODEL)
    except SystemExit as e:
        try:
            if not os.listdir(OUTPUT_DIR):
                os.rmdir(OUTPUT_DIR)
        except OSError:
            pass
        return e.code

    if used_model != MODEL:
        print(f"      [注意] 已自动降级到 {used_model} 模型（{MODEL} 不可用）。")
        print(f"             {used_model} 速度快但准确度较低，重要视频建议手动用 {MODEL} 重跑。")

    print("[2/3] 转写：{VIDEO}".format(VIDEO=VIDEO))
    try:
        from audio_input import transcribe
        segments, info, decoder = transcribe(model, VIDEO, vad_filter=True, language=LANGUAGE)
    except Exception as e:  # noqa: BLE001
        print(f"\n[错误] 转写失败：{type(e).__name__}: {e}", file=sys.stderr)
        print("\n常见原因：", file=sys.stderr)
        print("  - 视频无音频流或音轨损坏 → 换一个有声音的视频", file=sys.stderr)
        print("  - 文件其实是网络链接/已失效 → 确认路径可访问", file=sys.stderr)
        print("  - 编码不受支持 → 先用 ffmpeg 转 wav 再试：", file=sys.stderr)
        print('      ffmpeg -i "%s" -ar 16000 -ac 1 audio.wav' % VIDEO, file=sys.stderr)
        try:
            if not os.listdir(OUTPUT_DIR):
                os.rmdir(OUTPUT_DIR)
        except OSError:
            pass
        return 5
    print(f"      语言：{info.language}  概率：{info.language_probability:.2f}  时长：{info.duration:.0f}s")

    print(f"[3/3] 写入产物 → {OUTPUT_DIR}")
    segs = []
    last_pct = -1
    dur = getattr(info, "duration", 0) or 0
    converted = 0
    fixed_terms = 0
    with open(md_path, "w", encoding="utf-8") as f:
        for i, s in enumerate(segments):
            text = s.text.strip()
            if not text:
                continue
            # 1) 术语纠错（长词优先）
            if TO_FIX_TERMS:
                text, k = fix_terms(text)
                fixed_terms += k
            # 2) 繁简转换
            if TO_SIMPLIFIED:
                new = to_simplified(text)
                if new != text:
                    converted += 1
                text = new
            f.write(f"[{fmt_ts(s.start)}] {text}\n")
            segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
            # 进度反馈：长视频每 ~5% 打一次，避免用户以为卡死
            if dur:
                pct = int(s.end / dur * 100)
                if pct >= last_pct + 5:
                    last_pct = pct
                    print(f"      … {pct}%  ({fmt_ts(s.start)} / {fmt_ts(dur)})", flush=True)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"method": "asr", "source_path": os.path.abspath(VIDEO),
                   "decoder": decoder, "language": info.language,
                   "duration": round(info.duration, 2),
                   "model": used_model,
                   "model_requested": MODEL,
                   "segments": segs}, f, ensure_ascii=False, indent=2)

    print(f"\n[完成] 共 {len(segs)} 段（模型：{os.path.basename(used_model) if os.path.isdir(str(used_model)) else used_model}）")
    print(f"  MT 文本：{md_path}")
    print(f"  结构化  ：{json_path}")
    if segs:
        total = sum(len(x["text"]) for x in segs)
        print(f"  字符数  ：{total}   （超过 1500 行请走 long-video-chunking.md 分块读法）")
    if TO_SIMPLIFIED and converted:
        print(f"  繁简转换：{converted}/{len(segs)} 段已转为简体")
    elif TO_SIMPLIFIED and segs:
        # 区分"确实无需转换"与"opencc 不可用"——之前这里会误报
        if _SIMPLIFIER is False:
            print("  繁简转换：opencc 不可用（可选：pip install opencc-python-reimplemented）")
        else:
            print("  繁简转换：已启用，本次输出无繁体（无需转换）")
    if TO_FIX_TERMS:
        n_fix = len(load_term_fixes())
        if n_fix:
            print(f"  术语纠错：已应用 {fixed_terms} 处（术语表 {n_fix} 条）")
        else:
            print("  术语纠错：未找到 terms_*.json（可选：放入同目录即自动生效）")
    if not segs:
        print("\n[警告] 没有识别到任何语音内容。可能原因：视频无音轨 / 纯音乐 / 音量过低。")
    print("\n下一步：把 原始提取.md 交给 AI 走 Stage2-4（入库 / 学习指南 HTML / 技能包）")
    return 0


if __name__ == "__main__":
    sys.exit(main())