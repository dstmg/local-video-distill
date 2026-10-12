# 新手首次运行：三种分析方式

所有命令从项目根目录运行。先用一个短视频测试，再处理整批。

## 共同准备

安装 Python，执行 `python scripts/setup.py --no-model`。Windows 后续使用 `& .\scripts\.venv\Scripts\python.exe`；Linux/macOS 使用 `scripts/.venv/bin/python`。

执行 `& .\scripts\.venv\Scripts\python.exe scripts/doctor.py` 检查提取环境。无字幕视频需要本地语音转写模型；首次加载模型可能联网下载。内嵌字幕提取、视觉采样及部分解码兼容路径需要 ffmpeg。模型文件可通过 `--model` 指定本机目录。

## 方式一：Codex / WorkBuddy 等 Agent

```powershell
& .\scripts\.venv\Scripts\python.exe scripts/pipeline.py 'G:/课程/视频.mp4' './out' --model small
```

此时完成的是提取与检索，结果入口会显示分析待完成。把本次 summary.json 路径交给 Agent，要求它按 `references/analysis-bundle-spec.md` 阅读冻结原稿和全部分块，填写分析包并绑定原稿证据。不要仅凭简短摘要生成完整分析。

```powershell
& .\scripts\.venv\Scripts\python.exe scripts/analysis_bundle.py --summary './out/summary.json' --analysis './填好的分析包.json' --out './分析产物'
```

按照帮助中的参数验证并渲染填写完成的分析包。Agent 是否将文字上传云端，由所用软件及账户设置决定。

## 方式二：本地模型

安装 Ollama，下载适合电脑配置的模型并启动服务。复制 `examples/local-model.config.example.json` 为 `local-model.config.json`，将 model 改为本机实际已安装的名称。转写模型和分析模型是两套独立模型；示例名称不保证适合所有电脑。

```powershell
& .\scripts\.venv\Scripts\python.exe scripts/pipeline.py 'G:/课程/视频.mp4' './out' --model small --llm-config './local-model.config.json'
```

原稿发送到本机 loopback 服务。上下文不足、模型缺失或验证失败会明确停止，不自动改用云端。详见 [本地自动蒸馏](automatic-distillation.md)。

## 方式三：通义千问／百炼 API

在百炼创建对应地域的 Key。Windows 按 Win+R，输入 `sysdm.cpl`，进入“高级 → 环境变量 → 用户变量 → 新建”：名称 `DASHSCOPE_API_KEY`，值为自己的 Key。重新打开终端使设置生效；不要提交 Key 到 Git。

复制 `examples/bailian.config.example.json` 为 `bailian.config.json`，确认模型、入口与 Key 地域一致。

```powershell
# 已设置用户变量但当前窗口尚未刷新时，只读取，不输出 Key
$env:DASHSCOPE_API_KEY=[Environment]::GetEnvironmentVariable('DASHSCOPE_API_KEY','User')
& .\scripts\.venv\Scripts\python.exe scripts/pipeline.py 'G:/课程/视频.mp4' './out' --model small --llm-config './bailian.config.json'
```

视频提取仍在本地，文字片段与综合判断发送百炼，可能收费。详见 [百炼配置与费用](bailian-distillation.md)。

## 查看结果与恢复

打开输出目录的 `结果入口.html`，查看学习指南、关系证据、原稿、校对稿、待核对事项及运行记录。根入口指向最新运行，每次运行保留自己的入口。失败时先查看入口中的错误与摘要；相同输入和配置重跑可复用有效缓存。

术语共现图用于找出处；知识关系另标前提、步骤、因果、例外、冲突并绑定证据。机器验证检查结构和引用，不保证推理正确。重要数字、历史活动背景和操作步骤仍需回看原视频。产物保存在本地，不代表已发布。
