# 商知 · 电商视频知识蒸馏

[![tests](https://github.com/dstmg/local-video-distill/actions/workflows/tests.yml/badge.svg)](https://github.com/dstmg/local-video-distill/actions/workflows/tests.yml)

商知面向电商人的视频学习与知识积累，把运营、推广、选品、数据分析等本地视频教程变成带时间戳的原稿、详细分析、有证据的知识关系和学习指南。支持三种分析方式：Codex / WorkBuddy 等 Agent、本地模型、通义千问／阿里云百炼。

![商知：把电商视频，变成自己的知识](assets/shangzhi-cover.png)

中文展示名为 **商知**；仓库与技能标识保持 `local-video-distill`。

## 首次使用

从项目根目录运行，先选一条短视频。完整操作见 [三种方式的新手教程](references/first-run.md)。

```powershell
python scripts/setup.py --no-model
& .\scripts\.venv\Scripts\python.exe scripts/doctor.py
```

无字幕视频需要本地语音转写模型，首次加载可能联网下载；内嵌字幕、视觉采样和部分解码兼容路径需要 ffmpeg。Linux/macOS 将示例中的解释器替换为 `scripts/.venv/bin/python`。

| 分析方式 | 如何选择 | 文字发送范围 |
|---|---|---|
| Agent | 先提取，再让 Agent 按分析契约读完整原稿、填写并验证分析包 | 由 Agent 软件及账户设置决定 |
| 本地模型 | 安装并启动 Ollama，复制本地模型配置并指定已安装模型 | 本机 loopback 服务 |
| 百炼 API | 配置对应地域的 Key，复制百炼配置 | 原稿文字与综合判断发送百炼；视频不上传 |

### 先提取，交给 Agent

```powershell
& .\scripts\.venv\Scripts\python.exe scripts/pipeline.py 'G:/课程/视频.mp4' './out' --model small
```

没有分析配置时，自动完成提取、校对副本、索引及术语共现图，内容分析待完成。将本次 summary.json 交给 Agent，要求按 [分析包契约](references/analysis-bundle-spec.md) 阅读冻结原稿与全部分块，再验证：

```powershell
& .\scripts\.venv\Scripts\python.exe scripts/analysis_bundle.py --summary './out/summary.json' --analysis './填好的分析包.json' --out './分析产物'
```

### 使用本地模型全自动分析

复制 `examples/local-model.config.example.json` 为 `local-model.config.json`。安装并启动 Ollama，把 model 改为本机实际可用的模型。分析模型与语音转写模型相互独立，用户可按电脑配置选择。

```powershell
& .\scripts\.venv\Scripts\python.exe scripts/pipeline.py 'G:/课程/视频.mp4' './out' --model small --llm-config './local-model.config.json'
```

配置、上下文和限制见 [本地自动蒸馏](references/automatic-distillation.md)。本地服务失败不会自动改用云端。

### 使用通义千问／百炼

复制 `examples/bailian.config.example.json` 为 `bailian.config.json`。在本机设置 `DASHSCOPE_API_KEY` 环境变量，确认 Key、模型和入口地域匹配；不要把 Key 写进配置或提交到 Git。

```powershell
& .\scripts\.venv\Scripts\python.exe scripts/pipeline.py 'G:/课程/视频.mp4' './out' --model small --llm-config './bailian.config.json'
```

无需本地分析大模型；语音转写仍需本地依赖。费用、发送范围及可选预算保护见 [百炼配置](references/bailian-distillation.md)。

## 查看结果

打开输出目录的 **结果入口.html**。它集中链接指南、关系证据、原稿、详细分析、待核对事项和运行记录，明确区分提取完成、分析待完成和失败。

```text
out/
├── 结果入口.html                 最新一轮入口
├── summary.json                  最新一轮摘要
├── 逐字稿/<来源ID>/               原始机器提取及完成记录
├── 模型缓存/                     已校验分析缓存
└── 运行记录/<运行ID>/
    ├── 结果入口.html             本轮独立入口
    ├── 原稿快照/                 本轮使用的冻结原稿
    ├── 校对稿/                   术语修订副本
    ├── 修订记录.json
    ├── 阅读分块/
    ├── 总索引.html
    ├── 术语反向索引.html
    ├── 术语共现图.html
    └── 自动蒸馏/产物/            配置模型后生成指南、分析与知识关系
```

原始机器稿与校对稿分别保留。术语共现图用于找出处；知识关系另标前提、步骤、因果、例外、冲突，每条绑定来源引文与时间。机器检查验证结构、引用和覆盖，不能证明知识或因果正确。重要数字、错词、画面操作和历史活动背景仍需回看视频。

## 常用选项与恢复

- `--limit 1`：目录中只处理一条，适合首次测试。
- `--dry-run`：显示计划，不调用模型。
- `--model`：语音转写模型名或本机目录；分析模型写在配置的 model 字段。
- `--visual`：本地抽帧，按配置可做 OCR；仅覆盖采样画面。
- `--skill-bundle`：配合模型配置生成本地知识技能包，不自动安装或发布。
- `--no-fix-terms`、`--no-index`、`--no-wiki`：关闭对应可选阶段。

失败时先查看结果入口中的阶段记录。相同输入、参数和配置重跑会复用已核验原稿及分析缓存；源文件或工具变化会使相关缓存失效。独立 auto_distill 输出目录须为空，重试可使用新目录并共享 cache。完整参数用 `python scripts/pipeline.py --help` 查看。

## 开发与边界

```powershell
python -X utf8 -m unittest discover -s scripts -p 'test*.py' -q
python -X utf8 -m compileall -q scripts
```

公共 examples 使用虚构或自造内容；真实验收文件留在忽略的 out 目录。项目不绕过授权、不自动发布课程或安装技能，云端分析只在明确选择配置后执行。过程说明见 [蒸馏流程](references/distillation-workflow.md)；脚本说明见 [scripts/README-scripts.md](scripts/README-scripts.md)。
