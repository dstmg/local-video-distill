#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doctor.py — 本地视频蒸馏环境体检（跨平台：Windows / macOS / Linux）

用法：
    python doctor.py            # 只体检，不改动任何东西
    python doctor.py --json     # 机器可读输出

退出码：0 = 核心依赖齐全；1 = 有缺失（详见输出）
"""
import json
import os
import shutil
import subprocess
import sys

IS_WIN = sys.platform.startswith("win")

# 模型体积提示（首次运行会自动下载）
MODEL_SIZE = {
    "tiny": "~75 MB",
    "base": "~145 MB",
    "small": "~480 MB",
    "medium": "~1.5 GB",
    "large-v3": "~3 GB",
}

# --json 模式下必须保持 stdout 纯净（只输出 JSON），故全局静音 _out
_QUIET = False


def _out(s=""):
    if not _QUIET:
        print(s)


def check_python():
    ok = sys.version_info >= (3, 8)
    ver = ".".join(map(str, sys.version_info[:3]))
    _out(f"  [{'OK' if ok else '!!'}] Python {ver}  ({sys.executable})")
    if not ok:
        _out("       需要 Python 3.8+。Windows: https://www.python.org/downloads/ (勾选 Add to PATH)")
        _out("       macOS: brew install python   |   Linux: sudo apt install python3 python3-pip")
    return {"name": "python", "ok": ok, "version": ver}


def check_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        _out(f"  [OK] ffmpeg  ({exe})")
        tip = "仅「提取内嵌字幕轨 / 命令行剪辑」需要；纯 ASR 转写不需要它。"
    else:
        _out("  [--] ffmpeg 未找到（可选）")
        tip = ("仅「提取内嵌字幕轨」需要。安装：Windows: winget install Gyan.FFmpeg | "
               "macOS: brew install ffmpeg | Linux: sudo apt install ffmpeg")
    _out(f"       {tip}")
    return {"name": "ffmpeg", "ok": exe is not None, "optional": True, "path": exe}


def _run_import(mod):
    """在当前解释器里 import 一个模块，返回 (ok, version, error)"""
    code = "import importlib,sys;m=importlib.import_module(sys.argv[1]);print(getattr(m,'__version__','?'))"
    try:
        r = subprocess.run([sys.executable, "-c", code, mod],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return True, r.stdout.strip(), None
        return False, None, (r.stderr or "").strip().splitlines()[-1] if r.stderr else "import failed"
    except Exception as e:  # noqa: BLE001
        return False, None, str(e)


def check_faster_whisper():
    ok, ver, err = _run_import("faster_whisper")
    if ok:
        _out(f"  [OK] faster-whisper {ver}")
        return {"name": "faster-whisper", "ok": True, "version": ver}
    _out("  [!!] faster-whisper 未安装  <-- 核心依赖")
    _out("       pip install faster-whisper av")
    _out("       若报 externally-managed-environment，请用虚拟环境：")
    _out("         python -m venv .venv && .venv/bin/pip install faster-whisper av")
    _out("         Windows: .venv\\Scripts\\activate   后再 pip install")
    if err:
        _out(f"       实际报错：{err}")
    return {"name": "faster-whisper", "ok": False, "error": err}


def check_av():
    ok, ver, err = _run_import("av")
    if ok:
        _out(f"  [OK] PyAV {ver}   (音频解码，ASR 必需)")
        return {"name": "PyAV", "ok": True, "version": ver}
    _out("  [!!] PyAV 未安装  <-- 核心依赖（没有它 faster-whisper 无法解码视频）")
    _out("       pip install av")
    if err:
        _out(f"       实际报错：{err}")
    return {"name": "PyAV", "ok": False, "error": err}


def check_model_cache():
    # faster-whisper 默认模型缓存目录
    roots = [os.environ.get("HF_HOME"), os.path.join(os.path.expanduser("~"), ".cache", "huggingface")]
    found = False
    for root in roots:
        if root and os.path.isdir(root):
            for dirpath, _dirnames, filenames in os.walk(root):
                if "model.bin" in filenames:
                    _out(f"  [OK] 发现已下载模型缓存：{dirpath}")
                    found = True
                    break
        if found:
            break
    if not found:
        _out("  [--] 暂无模型缓存（首次转写会自动下载，耗时取决于网速）")
        for m, sz in MODEL_SIZE.items():
            _out(f"         {m:<8} {sz}")
        _out("       国内网络建议先设镜像（否则可能很慢/失败）：")
        _out('         export HF_ENDPOINT=https://hf-mirror.com   (macOS/Linux)')
        _out('         $env:HF_ENDPOINT="https://hf-mirror.com" (PowerShell)')
        _out("       想先预热：把 transcribe.py / setup.py 的 MODEL 改成 \"small\" 先跑一次")
    return {"name": "model-cache", "ok": found, "optional": True}


def check_cloud_keys():
    keys = {k: bool(os.environ.get(k)) for k in ("GROQ_API_KEY", "OPENAI_API_KEY")}
    if any(keys.values()):
        for k, v in keys.items():
            if v:
                _out(f"  [OK] {k} 已设置（仅检查存在，未验证账户；不会自动上传）")
    else:
        _out("  [--] 未设置其他云端转写 Key（本地提取不需要；本项目不自动回退云端 ASR）")
    return {"name": "cloud-keys", "ok": any(keys.values()), "optional": True}


def main():
    global _QUIET
    as_json = "--json" in sys.argv
    if as_json:
        _QUIET = True  # 静音人类可读输出，保证 stdout 是纯 JSON
    if not as_json:
        _out("=" * 60)
        _out("本地视频蒸馏 · 环境体检")
        _out("=" * 60)
        _out(f"\n平台：{sys.platform}   解释器：{sys.executable}\n")

    results = [check_python()]
    if not as_json:
        _out("")
    results.append(check_faster_whisper())
    if not as_json:
        _out("")
    results.append(check_av())
    if not as_json:
        _out("")
    results.append(check_ffmpeg())
    if not as_json:
        _out("")
    results.append(check_model_cache())
    if not as_json:
        _out("")
    results.append(check_cloud_keys())

    core_ok = all(r["ok"] for r in results if not r.get("optional"))
    optional_ok = all(r["ok"] for r in results if r.get("optional"))

    if not as_json:
        _out("\n" + "=" * 60)
        if core_ok:
            _out("[结论] 核心依赖齐全，可以开始转写。")
            if not optional_ok:
                _out("       可选项未就绪不影响主流程（详见上面标注 -- 的项）。")
            _out("\n下一步：编辑 transcribe.py 的 VIDEO / MODEL / OUTPUT_DIR，然后")
            _out("        python transcribe.py")
        else:
            _out("[结论] 有核心依赖缺失，请按上面的修复命令安装后重跑 doctor.py。")
            _out("       最小必需：pip install faster-whisper av")
        _out("=" * 60)

    if as_json:
        print(json.dumps({"platform": sys.platform,
                          "python": sys.executable,
                          "core_ok": core_ok,
                          "checks": results}, ensure_ascii=False, indent=2))
    return 0 if core_ok else 1


if __name__ == "__main__":
    sys.exit(main())
