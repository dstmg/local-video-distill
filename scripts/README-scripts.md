# scripts/ — 脚本说明（Windows / macOS / Linux）

从项目根目录的首次操作见 [新手教程](../references/first-run.md)。本文旧脚本短命令默认已进入 scripts 目录。

**一条龙入口**：`python pipeline.py <视频目录> <输出目录>` —— 转写 → 术语纠错 → 总索引页 → **知识关联层（术语索引 + 知识图谱）**。

| 脚本 | 作用 | 何时用 |
|---|---|---|
| `pipeline.py` | **一条龙**：全部步骤 + summary.json | ★ 大多数情况用这个 |
| `setup.py` | 一键装环境：建 `.venv` + 装依赖 + 预拉模型 | 第一次用 / 换机器 |
| `doctor.py` | 环境体检：缺什么给精确修复命令 | 装完确认、报错了排查 |
| `download_model.sh` | 下载模型到本地目录（绕镜像 bug） | 下载模型 / 模型加载报错 |
| `transcribe.py` | 转写单个视频（+ 繁简 + 术语纠错） | 精细控制单个视频 |
| `batch_transcribe.sh` | 批量转写目录（幂等） | 已有转写流程，只想批量 |
| `fix_terms.py` | 术语纠错（事后修正历史稿，支持拼音模糊） | 术语不准想改 |
| `build_index.py` | 打包成单页总索引 | 已有逐字稿，只想出页面 |
| `build_term_index.py` | **术语反向索引**（Wiki 层） | 查"某概念在哪几节课讲过" |
| `build_graph.py` | **知识图谱**（共现可视化） | 看课程体系的知识结构 |
| `validate_skill.py` | 技能包完整性校验 | 做了技能包想自检 |
| `guide_builder.py` | 学习指南生成器（含规范校验） | 想规范产出学习指南 |
| `add_theme.py` | 给已有 HTML 注入三套主题 | 老页面想加主题切换 |

## 自检套件

```bash
python test_all.py          # 全部（纯标准库，无需额外依赖）
python test_all.py -v       # 详细
```

18 个用例覆盖：逐字稿解析、时间戳格式化、术语表加载与替换（含拼音误伤防护）、
技能包校验器、学习指南校验器、术语索引扫描、主题注入幂等性。
**不依赖 faster-whisper / ffmpeg，离线可跑。**

## 最快上手

```bash
# 一条龙（推荐）
python pipeline.py "G:/课程视频" ./out --limit 20

# 分步
cd scripts
python setup.py
python doctor.py
python transcribe.py 视频.mp4 ./out
```

## 一条龙脚本用法

```bash
python pipeline.py <视频目录> <输出目录> [选项]

# 限量 + 指定模型
python pipeline.py "G:/课程视频" ./out --limit 20 --model small

# 只转写，不建索引/知识层
python pipeline.py "G:/课程视频" ./out --no-index --no-wiki

# 先看会做什么
python pipeline.py "G:/课程视频" ./out --dry-run
```

| 选项 | 说明 |
|---|---|
| `--limit N` | 最多处理 N 个（0=全部） |
| `--model NAME` | tiny/base/small/medium/large-v3 或本地目录 |
| `--no-fix-terms` | 跳过术语纠错 |
| `--no-index` | 跳过总索引页 |
| `--no-wiki` | 跳过知识关联层（术语索引 + 知识图谱） |
| `--min-term N` | 术语至少出现几次才进索引（默认 2） |
| `--dry-run` | 只打印不执行 |
| `--skip-check` | 跳过环境体检（更快） |

**特性**
- **幂等**：已转写过的自动跳过，中断后重跑不重复劳动
- **不中断**：单个视频失败不中断整批，最后汇总失败清单
- **产出摘要**：自动写 `summary.json`（成功/失败/耗时/失败清单）

**五步流程**
```
1/5 环境体检  →  2/5 转写  →  3/5 术语纠错  →  4/5 总索引页  →  5/5 知识关联层
```

**输出结构**
```
输出目录/
├── 逐字稿/<视频ID>/{原始提取.md, 原始提取.json}
├── 学习产物/{总索引.html, 术语反向索引.html, 术语知识图谱.html}
└── summary.json
```

**环境变量**：`VIDEO_PYTHON` 指定带 faster-whisper 的解释器（脚本会自动探测 .venv）。

## 各脚本用法

### setup.py
```bash
python setup.py              # 装环境 + 预拉 small 模型
python setup.py --no-model   # 只装依赖，不预拉模型（省 480MB 下载）
python setup.py --check      # 不改动任何东西，只体检（等价 doctor.py）
```
做四件事：① 检查 Python ≥3.8；② 建 `.venv`（绕开 PEP 668 `externally-managed-environment` 限制）；③ 装依赖；④ 预拉 `small` 模型。完成后**打印你机器上解释器的准确路径**——把它记为 `$VIDEO_ASR_PYTHON`。

### doctor.py
```bash
python doctor.py           # 人读格式
python doctor.py --json    # 机器可读
```
逐项检查并对缺失项打印精确修复命令；退出码 0 = 核心依赖齐全，1 = 有缺失。

### transcribe.py
```bash
python transcribe.py 视频.mp4 输出目录
python transcribe.py            # 不带参数则用文件顶部默认配置
```
或先编辑文件顶部的 `VIDEO` / `MODEL` / `OUTPUT_DIR` / `LANGUAGE`，再直接 `python transcribe.py`。

- **模型选择**：`MODEL` 留空时自动用 `LOCAL_MODEL_DIR`（默认 `~/faster-whisper-models/tiny`，存在就用它）；也可直接填模型名或本地目录绝对路径。
- **准确度**：`tiny` 最快但错字多，正式用建议 `small` 或 `medium`。
- **繁简转换**：`TO_SIMPLIFIED=True`（默认）会把 Whisper 输出的繁体自动转简体，需 `pip install opencc-python-reimplemented`（纯 Python 免编译）。
- GPU：把 `DEVICE`/`COMPUTE_TYPE` 改成 `"cuda"`/`"float16"`。
- **不需要 ffmpeg** —— faster-whisper 靠 PyAV 在 Python 内解码，视频文件可直接喂。
- **退出码**：0 成功 / 1 缺依赖 / 2 文件不存在 / 3 模型加载失败 / 4 无音频流 / 5 转写失败。

### download_model.sh —— 强烈建议用这个下模型
```bash
bash download_model.sh tiny|base|small|medium|large-v3
```
模型下到 `~/faster-whisper-models/<模型名>/`，`transcribe.py` 会自动识别并使用。支持断点续传。

**为什么要单独写这个脚本？两个坑：**

1. **307 重定向 bug**：国内镜像（hf-mirror.com）会返回 307 重定向到 `/api/resolve-cache/...`，而 `huggingface_hub` 某些版本处理这个新路径有 bug：**下载中断后在缓存里留下 0 字节文件**（config.json / tokenizer.json / vocabulary.txt 全是 0 字节，只有 model.bin 完整）。之后加载会报：
   ```
   RuntimeError: [json.exception.parse_error.101] parse error at line 1, column 1:
   syntax error while parsing value - unexpected end of input
   ```
   这个报错**极具误导性**——看起来像网络/JSON 问题，实际是"JSON 文件是空的"。

2. **大文件被代理拦截**：`model.bin`（几百 MB）整文件下载常被代理返回 `502 CONNECT tunnel failed`（小文件反而能过）。本脚本用**分段Range 请求**（每块 4MB）逐块下载，单块失败自动重试，实测能绕过。

**如果 model.bin 反复失败**：多半是 Clash 等代理工具在拦大文件请求，临时关掉代理重跑本脚本即可。

**智能模型加载（重要）**：脚本不会盲目下载模型，而是——
1. 先在本地 HF 缓存里找**完整**的模型（校验 `model.bin` 体积），找到就**离线加载**，又快又稳；
2. 没有完整缓存才尝试下载（默认走 `hf-mirror.com` 国内镜像）；
3. 都失败则**自动降级**到更小的模型（medium→small→base→tiny），并在结束时提示"已降级，准确度较低"。

产出的 `原始提取.json` 里 `model` 是实际用的模型，`model_requested` 是你请求的，便于溯源。

### fix_terms.py —— 术语纠错（可事后修正历史稿）
```bash
python fix_terms.py <文件或目录> [--dry-run] [--out <新目录>] [--pinyin]
```
对**已有转写稿**事后纠错，不用重新转写。

- `--dry-run`：只看命中统计不改文件（**建议先跑**）
- `--out <目录>`：输出到别处，保留原文件
- `--pinyin`：拼音模糊纠错（需 `pip install pypinyin`），捕捉词表**未收录**的同音错字

**术语表加载顺序**：`scripts/terms_custom.json`（你的，优先）→ `scripts/terms_*.json` → `examples/terms_*.example.json`。

**`--pinyin` 的安全边界**（避免误伤）：
- 只在**拼音唯一对应一个术语**时才替换；多个术语同音 → 跳过
- 命中词已在正确术语表里 → 跳过；命中常见日常词（内置白名单）→ 跳过
- 所有替换都会列出，**建议人工复核后再实际写入**

```bash
python fix_terms.py ./out --pinyin --dry-run   # 先看
python fix_terms.py ./out --pinyin             # 再执行
```

### build_index.py —— 打包成单页总索引
```bash
python build_index.py <逐字稿根目录> <输出HTML> [--title T] [--guide 学习指南.html] [--src-dir 原视频目录] [--open-all]
```
把一批转写稿 + 可选学习指南打包成**单个 HTML**：学习指南**真正内联**（不是 iframe）+ 全部逐字稿（带 `[mm:ss]`、可折叠）+ 顶部搜索过滤 + 「✏️修改」。

- `--guide`：学习指南 HTML，**用绝对路径**（会被内联进本页）
- `--src-dir`：原视频目录，用于从文件名还原可读标题（去抖音话题标签）
- `--open-all`：默认展开全部逐字稿

### validate_skill.py —— 技能包完整性校验
```bash
python validate_skill.py <技能目录> [...] [--require-anchors N]
```
校验：
- frontmatter `name` == 目录名（**不一致会导致宿主加载不到**）
- `capability-count` 与实际能力卡数一致
- 路由表引用的文件无断链
- 名称合法（仅小写字母/数字/连字符）
- 术语表存在
- 可选：每张能力卡的 `--require-anchors N` 个时间锚点

退出码 0 = 通过。发布前跑一次能挡住今天踩过的那几个坑。

### guide_builder.py —— 学习指南生成器（Stage 3）
```bash
python guide_builder.py --print-schema              # 看内容 JSON 结构
python guide_builder.py content.json -o 指南.html   # 生成（先校验）
python guide_builder.py content.json --check-only   # 只校验
python guide_builder.py --validate-html 指南.html   # 校验已生成 HTML
```
从结构化 JSON 生成单页 HTML 学习指南，**生成前自动按 `teaching-note-spec.md` 校验**：9 个必填章节、每条结论是否挂时间戳、自测题答案是否折叠、是否标注「课内示例」。不通过就中止生成。

这样 AI 只负责填内容，格式与合规由脚本保证。

### build_term_index.py —— 术语反向索引（Wiki 层）
```bash
python build_term_index.py <逐字稿根目录> -o 索引.html --json 索引.json \
  [--src-dir 原视频目录] [--min-count 2]
```
解决"同一个概念散落在多条视频，找不到在哪讲"：扫全部逐字稿，统计每个**正确术语**出现在**哪些视频的哪些时间点**。

- 输出 HTML：点时间戳直达总索引页对应视频；支持搜索 + 按"跨多视频/单视频"筛选
- 输出 JSON：供 `build_graph.py` 或其他程序消费
- `--min-count N`：术语至少出现 N 次才收录（默认 2，过滤噪声）

跨视频出现的术语就是**知识枢纽**——实测"人群"跨 18 个视频、"拉新"跨 13 个。

### build_graph.py —— 知识图谱（共现可视化）
```bash
python build_graph.py <术语索引.json> -o 图谱.html [--min-edge 2] [--top-nodes 40]
```
节点=术语（大小=频次），边=共现（粗细=共现视频数）。
纯 JS 力导向布局，**无外部依赖、无需联网**。交互：悬停看详情、点击聚焦邻接、搜索定位、拖拽平移、滚轮缩放、点空白取消。

典型产出：31 节点 / 318 条边，一眼看出课程的知识骨架。

### add_theme.py —— 给已有 HTML 注入三套主题
```bash
python add_theme.py <文件.html> [...] [-o 新文件] [--dry-run]
```
给早于多主题功能生成的存量 HTML 补上主题切换（light / dark / magazine）。**幂等**：已含主题则跳过。

## 常见问题

**Q：`pip install` 报 externally-managed-environment？**
A：Python 3.12+ 的系统环境保护机制。用 `python setup.py` 建 `.venv` 隔离即可，已自动处理。

**Q：国内网络装依赖慢/失败？**
A：`setup.py` 失败时会打印清华镜像命令，复制执行即可。模型下载已默认走 `hf-mirror.com`，无需额外配置；若想用官方源，把 `transcribe.py` / `setup.py` 顶部 `USE_MIRROR` 改成 `False`。

**Q：第一次转写很慢 / 模型下载失败？**
A：在下载模型。`small` 约 480MB、`medium` 约 1.5GB、`large-v3` 约 3GB。若下载失败，脚本会自动降级到更小模型。想先跑通就 `setup.py --no-model` 后把 `MODEL` 设成 `tiny`（75MB）。

**Q：日志出现 `[注意] 已自动降级到 tiny 模型`？**
A：你请求的模型本地没有完整缓存且下载失败，脚本自动用了能用的较小模型。重要视频建议手动设回大模型重跑。

**Q：需要 ffmpeg 吗？**
A：纯 ASR 转写**不需要**（PyAV 解码）。只有「提取内嵌字幕轨为 srt」或命令行剪辑才需要 ffmpeg CLI。

**Q：模型体积很大吗？**
A：`tiny` ~75MB / `base` ~145MB / `small` ~480MB / `medium` ~1.5GB / `large-v3` ~3GB。

## 环境变量（可选）

不会因为存在 API Key 自动启用云端 ASR；本项目没有自动云端转写回退。百炼 Key 只用于显式选择的云端文字分析。

## 2026-10-12：原稿保留、恢复与分析接入

pipeline 默认原始提取不纠错，术语纠错只在本次运行的校对副本中执行。产物位于输出目录的 `运行记录/<run-id>/`；根 summary.json 指向最新运行。每阶段退出码和日志独立记录，失败返回非零。

`--guide-json content.json` 将 Agent 的分析内容接入 guide_builder 的严格格式验证和渲染；不传则内容分析状态为 pending。图谱是术语共现图，不能替代知识关系分析。

`--asr-only` 强制 ASR，否则优先尝试 ffmpeg/ffprobe 抽取文字字幕。字幕/ASR 均不等于人工逐字稿，硬字幕 OCR 和屏幕操作分析仍需另行安排。

旧原稿无完成记录会重新提取并保存历史副本。校验包括来源哈希、模型参数、提取脚本和产物哈希；本地模型权重内容已纳入缓存指纹；远端缓存建议显式传本地模型目录。

运行测试：`python -m unittest discover -s scripts -p "test*.py" -v`。

## 2026-10-12：完整分析与视觉路径

新增 `analysis_bundle.py`（详细分析/关系/证据校验及离线展示）、`visual_extract.py`（帧采样和可选本地 OCR）、`media_tools.py`（本地媒体工具探测）、`audio_input.py`（已知 PyAV 接口不兼容时的 FFmpeg 回退）。完整契约见 references/analysis-bundle-spec.md。

pipeline 新增 --analysis-json、--visual、--ocr、--frame-interval、--max-frames、--ocr-region、--lang、--device、--compute-type。OCR 用本地 Tesseract，默认 chi_sim+eng，可用独立脚本 --lang 调整。固定区域必须按视频分辨率/版式设置，不能对不同视频盲目统一裁剪。采样报告明确区分采样时间与字幕起止，不能声称采样已覆盖全部操作。

工具从 PATH 或 VIDEO_FFMPEG/VIDEO_FFPROBE 找本地二进制；也支持已安装 imageio_ffmpeg 的捆绑文件及 PyAV 探测，不自动下载工具。不在 PATH 时应显式指定自己的工具路径。

本地模型文件内容纳入缓存指纹；手动更换 HuggingFace 外部缓存但保持相同模型名称时，建议显式传本地模型目录以获得内容指纹。每次运行产生原稿快照和逐段阅读分块，详细分析只能声明自报阅读覆盖，不自动证明阅读行为。

## 自动蒸馏脚本（2026-10-12）

新增 local_llm.py、auto_distill.py、test_auto_distill.py。pipeline 增加 --llm-config 与 --skill-bundle；模型服务先检查，分块结果独立缓存，生成后严格验证并有限修订。无需额外 Python API SDK。

本地 Ollama 原生 API 可明确设置上下文。local-compatible 仅允许本机；provider=bailian 支持官方云端兼容入口。测试模拟服务与真实模型效果分开报告。配置/命令见 references/automatic-distillation.md。


## 百炼 API 适配

local_llm.py 保留原文件名以兼容既有导入，现支持 provider=bailian。--llm-config 使用同一流水线，新增环境变量鉴权、官方HTTPS入口验证、明确关闭思考和搜索、Token统计。完整配置：references/bailian-distillation.md。请求失败不回落到其他服务，模型真实效果未实测。
