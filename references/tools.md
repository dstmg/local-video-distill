# 工具参考 · 视频蒸馏

本技能依赖少量外部工具。**首选方式：直接用 `scripts/` 下的跨平台脚本**（Windows / macOS / Linux 通吃，无 bash 依赖）；本文档解释各工具原理与手工兜底方案。

> **新用户第一步**：`python scripts/setup.py`（一键装环境）→ `python scripts/doctor.py`（体检）。
> 装完把脚本打印的解释器路径记为 `$VIDEO_ASR_PYTHON`，后续复用。

---

## 0. 最快路径：直接用脚本（推荐，跨平台）

| 脚本 | 作用 | 何时用 |
|---|---|---|
| `scripts/setup.py` | 建 .venv + 装 faster-whisper+av + 预拉 small 模型 + 打印下一步 | 第一次用 / 换机器 |
| `scripts/doctor.py` | 体检：Python/ffmpeg/faster-whisper/PyAV/模型缓存/云端Key，逐项给修复命令 | 装完确认、报错了 |
| `scripts/transcribe.py` | 转写：视频直接喂，产出 `原始提取.md`+`.json` | 每次转写 |

```bash
cd scripts
python setup.py            # 装环境
python doctor.py           # 体检，全 [OK] 即可
python transcribe.py 视频.mp4 输出目录   # 转写
```

细节见 `scripts/README-scripts.md`。下面各节是**原理与手工兜底**，供脚本不可用时参考。

---

## 1. 探测可用的 ASR Python 环境（手工版）

`doctor.py` 会自动做；这里是不用脚本时的手工探测：
```bash
python -c "import faster_whisper, av; print('faster-whisper', faster_whisper.__version__, '| PyAV ok')" 2>/dev/null \
  || echo "当前 python 没有 faster-whisper/PyAV，请见下方安装"
```
若你有多个环境（venv/conda/uv），用 `--python` 或显式路径指向对应解释器：
```bash
VIDEO_ASR_PYTHON="/path/to/venv/bin/python"   # Linux/macOS
# Windows PowerShell: $env:VIDEO_ASR_PYTHON = "C:\path\to\venv\Scripts\python.exe"
```

---

## 2. ffmpeg CLI（可选：仅「提取内嵌字幕轨 / 命令��行剪辑」需要）

> **ASR 转写不需要 ffmpeg** —— 音频解码由 PyAV 在 Python 内完成。只有抽字幕轨才装它。

### 探测
```bash
command -v ffmpeg && ffmpeg -version | head -1     # Git Bash / Linux / macOS
Get-Command ffmpeg -ErrorAction SilentlyContinue     # PowerShell
```

### 安装
```bash
winget install Gyan.FFmpeg        # Windows 推荐
# 或 choco install ffmpeg / brew install ffmpeg / sudo apt install ffmpeg
# 手动：https://www.gyan.dev/ffmpeg/builds/ 解压后把 bin/ 加进 PATH
```

### 常用命令
```bash
ffmpeg -i video.mp4 2>&1 | grep -i "subtitle"        # 找字幕轨
ffmpeg -i video.mp4 -map 0:s:0 -c copy sub.srt       # 抽第一条字幕轨
ffmpeg -i video.mp4 -ar 16000 -ac 1 -c:a pcm_s16le audio.wav   # 提音频(给 whisper CLI)
```
> 硬字幕（烧在画面）抽不到字幕流 → 走 ASR；可另加「抽帧 + OCR」省钱，见 tools 附注。

---

## 3. 本地 ASR（首选：faster-whisper）

### 安装依赖（推荐用虚拟环境，绕开 PEP 668 限制）
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      |  macOS/Linux: source .venv/bin/activate
pip install faster-whisper av
# GPU 可选：按 ctranslate2 文档装对应 CUDA，改 transcribe.py 为 device="cuda", compute_type="float16"
```

### 使用
直接跑脚本（推荐，跨平台）：`python transcribe.py 视频.mp4 输出目录`

以下是等价的手工逻辑（Python 核心，三平台写法一致，只是启动方式不同）：
```python
from faster_whisper import WhisperModel
m = WhisperModel("medium", device="cpu", compute_type="int8")
segs, info = m.transcribe("video.mp4", vad_filter=True, language="zh")
for s in segs:
    print(f"[{int(s.start)//60:02d}:{int(s.start)%60:02d}] {s.text.strip()}")
```
> 模型：速度优先 `small/base`，准确优先 `large-v3`。首次运行自动下载模型（体积见 doctor.py 提示）。

### 备选：openai-whisper CLI
`pip install openai-whisper` 后：`whisper audio.wav --model medium --output_format json --output_dir .`（需先提音频）。

---

## 4. 云端转写边界

本项目 pipeline 不实现云端 ASR 回退，也不会因检测到 Key 就上传音视频。本地引擎不可用时，保留诊断并按 setup / doctor 提示修复。用户若另选外部转写服务，应自行核对上传范围、授权、价格和输出格式。

## 5. 无字幕时的处理

先运行 doctor，安装本地 faster-whisper 及模型，再执行 transcribe。现有原稿也可直接进入后续分析。百炼配置只用于明确选择的文字分析，不是云端音视频转写。

## 6. 可选 · yt-dlp（从链接下视频）
```bash
pip install yt-dlp ; yt-dlp -o "%(title)s.%(ext)s" "https://..."
```

## 7. 可选 · 硬字幕 OCR（省算力）
硬字幕（烧在画面）可「抽帧 → OCR」比全片 ASR 便宜：
```bash
ffmpeg -i video.mp4 -vf fps=1 frames/%04d.png     # 每秒 1 帧
# 再用 tesseract/paddleocr 对 frames/ 批量识别，拼接为字幕
```

## 8. MT 输出格式约定

`原始提取.md`：
```
[00:00:12] 大家好，今天讲微付费起链接。
[00:00:35] 第一步先看近期可比竞品的价格带...
```
`原始提取.json`：
```json
{ "segments": [ { "start": 12.0, "end": 35.0, "text": "..." } ] }
```