#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup.py — 一键环境安装（跨平台：Windows / macOS / Linux）

用法：
    python setup.py                 # 建 .venv + 装依赖 + 预拉 small 模型
    python setup.py --no-model      # 只装依赖，不预拉模型
    python setup.py --check         # 不改动，只看当前环境是否就绪

作用：新用户零配置冷启动入口。自动处理：
  1. 检查 Python >= 3.8
  2. 创建隔离虚拟环境 .venv（绕开 PEP 668 externally-managed 限制）
  3. 装 faster-whisper + av
  4. 预拉 small 模型（约 480MB，避免首次转写时卡住）
  5. 打印「下一步怎么用」

装完请用 .venv 里的解释器跑：
    Windows : .venv\\Scripts\\python.exe doctor.py
    mac/Linux: .venv/bin/python doctor.py
（下方会直接打印这条命令，复制即可。）
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")
PREWARM_MODEL = "small"

# 国内网络走 HuggingFace 镜像，避免官方源下载失败/极慢
USE_MIRROR = True
if USE_MIRROR and not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


def venv_python():
    if sys.platform.startswith("win"):
        return os.path.join(VENV, "Scripts", "python.exe")
    return os.path.join(VENV, "bin", "python")


def run(cmd, **kw):
    print("  $", " ".join(cmd))
    return subprocess.run(cmd, **kw).returncode


def banner(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def check_env():
    banner("环境自检")
    rc = run([sys.executable, os.path.join(HERE, "doctor.py")])
    return rc == 0


def ensure_python():
    banner("1/4 检查 Python")
    v = sys.version_info
    print(f"  当前：Python {v.major}.{v.minor}.{v.micro}  ({sys.executable})")
    if v < (3, 8):
        print("  [!!] 需要 Python 3.8+")
        print("       Windows: https://www.python.org/downloads/  (安装时勾选 Add python.exe to PATH)")
        print("       macOS  : brew install python")
        print("       Linux  : sudo apt install python3 python3-venv")
        sys.exit(1)
    print("  [OK] Python 版本满足要求")


def make_venv():
    banner("2/4 创建虚拟环境 .venv（隔离依赖）")
    if os.path.isdir(VENV):
        print("  .venv 已存在，跳过创建")
        return
    rc = run([sys.executable, "-m", "venv", VENV])
    if rc != 0 or not os.path.isfile(venv_python()):
        print("  [!!] 创建 venv 失败")
        print("       Windows 需确保 Python 带 venv 模块；或手动：python -m venv .venv")
        sys.exit(1)
    print("  [OK] .venv 就绪")


def install_deps():
    banner("3/4 安装依赖 faster-whisper + av")
    pip = [venv_python(), "-m", "pip", "install", "--upgrade", "pip"]
    run(pip)
    rc = run([venv_python(), "-m", "pip", "install", "faster-whisper", "av"])
    if rc != 0:
        print("  [!!] 依赖安装失败")
        print("       国内网络可加镜像：")
        print("         " + " ".join([venv_python(), "-m", "pip", "install",
                                      "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                                      "faster-whisper", "av"]))
        print("       注意 GPU 用户需按 ctranslate2 文档装对应 CUDA。")
        sys.exit(1)
    print("  [OK] 依赖安装完成")


def prewarm():
    banner(f"4/4 预拉模型 {PREWARM_MODEL}（约 480MB，仅首次）")
    code = (f"from faster_whisper import WhisperModel;"
            f"WhisperModel('{PREWARM_MODEL}', device='cpu', compute_type='int8');"
            f"print('  [OK] 模型就绪')")
    try:
        run([venv_python(), "-c", code], timeout=1800)
    except subprocess.TimeoutExpired:
        print("  [--] 模型下载超时，可稍后手动重试（不影响安装结果）")


def next_steps():
    vp = venv_python()
    banner("安装完成 · 怎么用")
    prefix = '& ' if sys.platform.startswith('win') else ''
    print(f'  1. 体检：{prefix}"{vp}" "{os.path.join(HERE, "doctor.py")}"')
    print(f'  2. 提取：{prefix}"{vp}" "{os.path.join(HERE, "pipeline.py")}" "视频路径" "输出目录" --model small')
    print('  3. 自动分析：追加 --llm-config 配置路径；不加时交给 Agent 接续')
    print('  4. 打开输出目录的 结果入口.html 查看产物与运行状态')
    print('  详细教程：references/first-run.md（从项目根目录运行）')
    print('  首次模型加载可能联网；字幕、画面采样及部分解码路径需要 ffmpeg。')


def main():
    if "--check" in sys.argv:
        sys.exit(0 if check_env() else 1)

    ensure_python()
    make_venv()
    install_deps()
    if "--no-model" not in sys.argv:
        prewarm()
    next_steps()
    print("\n建议现在跑一次 doctor.py 确认全部 [OK]。")


if __name__ == "__main__":
    main()