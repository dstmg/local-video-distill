# 独立程序的全自动蒸馏（本地模型或百炼 API）

这条路线让脚本直接调用所选模型服务，不再依赖 Codex/WorkBuddy 人工接力填写分析包。提取、分块分析、综合、知识关系、指南、校验与有限修订都在流水线中。自动产物仍是机器分析，重要数值、术语、因果和画面需要核对。

## 三种使用方式

1. 本地模型：pipeline --llm-config，脚本调用本机服务。
2. API 模型：已加入通义千问／阿里云百炼。用 provider=bailian 与环境变量 Key 启用，见 [百炼说明](bailian-distillation.md)。
3. Agent 软件：保留原来的技能工作流，由 Codex/WorkBuddy 等读取文件和编排模型。Agent 背后也可以用本地或远端模型，因此第三项是编排方式，不是另一种模型种类。

## 准备本地服务

先自行安装 Ollama 并准备本地模型。示例采用 qwen3:4b，不表示本机已安装或已经实测质量：

```powershell
# 官方 Ollama 安装后执行；模型约2.5GB，下载不由本项目自动触发
ollama pull qwen3:4b
# 手动启动时禁用云功能，只绑定本机
$env:OLLAMA_NO_CLOUD='1'
$env:OLLAMA_HOST='127.0.0.1:11434'
ollama serve
```

若 Ollama 已由桌面程序运行，不要另起重复服务；设置云禁用项后按官方说明重启。模型文件放仓库外。本项目不会自动安装 Ollama、拉取 LLM 权重或改变其系统设置。

模型示例来源：[官方 Qwen3 4B 条目](https://ollama.com/library/qwen3:4b)。[Ollama 本地/云设置](https://docs.ollama.com/faq)。官方模型大小是文件大小，显存还需容纳上下文、缓存和其他运行开销。

## 一条命令

```powershell
Copy-Item examples/local-model.config.example.json local-model.config.json
# 配置里的 model 改为你实际安装的本地模型名
python scripts/pipeline.py 'G:/课程视频' ./out --llm-config ./local-model.config.json
# 可选：同时采样画面并生成本地知识技能包
python scripts/pipeline.py 'G:/课程视频' ./out --llm-config ./local-model.config.json --visual --skill-bundle
```

纯文字字幕无需 ASR；无字幕音频仍需 faster-whisper/PyAV 与本地转写权重。OCR 要本地 Tesseract 与语言包。

原稿已提取后，可单独自动分析而不重新转写：

```powershell
python scripts/auto_distill.py --summary ./out/summary.json --config ./local-model.config.json --out ./auto-result --cache ./out/模型缓存 --skill-bundle
```

单独输出目录必须为空/不存在；中断后换新目录并复用同一个 cache。pipeline 重跑则创建新运行目录并自动共享缓存。

## 实际执行

1. 先检查本地模型服务，或检查百炼 Key 环境变量是否存在；百炼实际鉴权在首次 API 调用发生。dry-run 不调用服务。
2. 每个原稿分块调用模型，要求详细判断与 segment_id 引用；程序从原始片段绑定引文和时间点，模型不能伪造引用文字。
3. 合并所有分块判断、逐视频分类、阅读区间与关系，详细结论保留完整。
4. 内容过多时分组挑选综合概览的代表性判断，覆盖各组来源。详细分析不删除。仍超过预算则停止并保留进度，不假装全批成功。
5. 模型生成跨视频综合、五类有证据关系、学习指南及至少三个问题验收；程序验证来源、引用、关系端点、章节和指南绑定。
6. 校验失败将错误返回模型，最多 repair_attempts 次；请求重试仅针对瞬时服务错误。次数耗尽不生成成功报告。
7. 生成原始/校对稿、详细分析 MD、跨视频综合 MD、关系图、学习指南、索引；可选生成知识技能包，不自动安装或发布。

OCR 文本可以作为标记未核对的补充资料传入所选模型服务；它不能冒充音频原稿引文，视觉独有内容仍应列待核对。当前不直接向模型传视频/图像。

## 配置和小模型限制

- provider=ollama 使用官方 `/api/chat`、format=json、think=false 和明确的 num_ctx；provider=local-compatible 使用本机的 `/chat/completions` 兼容接口，base_url 要填实际本地入口。
- 本地模式的 base_url 只允许 localhost/loopback；拒绝嵌入账号、云模型名字及 Ollama 返回的远端模型信息；禁用代理和重定向。兼容服务本身应配置为本地推理，不用远端代理转发。
- chunk_chars 控制分块字符量；max_input_chars 是程序字符预算，不是精确 token 数。context_length 是 Ollama 的 token 上下文。模型、语言和输出长度都会影响实际占用。百炼云端模式不使用 context_length 来配置服务端上下文，但仍执行客户端输入/输出预算检查。
- 示例 context_length=16384、max_output_tokens=4096，可按显存调整。显存不足时减少 context_length、chunk_chars 和输入预算，并使用更小的量化模型。不要只把输入预算调大而不改变模型上下文。
- 缓存键绑定提示词、模型名、入口、上下文/输出配置及代码版本。模型同名但内容替换时，应换模型名或换缓存目录；程序不对 Ollama 内部权重计算哈希。
- 自动模型不能声明 video_checked，也不自动核对全部视频画面；结构通过不保证语义正确。

接口依据：[官方 Chat API](https://docs.ollama.com/api/chat)、[本机兼容接口](https://docs.ollama.com/api/openai-compatibility)、[上下文说明](https://docs.ollama.com/context-length)。

## 当前验证范围

本机没有可用的 Ollama 服务/LLM，因此尚未实测真实本地模型的速度和蒸馏质量。测试使用 loopback 模拟服务，覆盖真实 HTTP 契约和子进程流水线，不把它当真实模型成功。已有真实 ASR/字幕/帧采样测试仍有效。

百炼模式另有鉴权、Token 用量与云端发送范围说明：[百炼自动蒸馏](bailian-distillation.md)。当前真实模型效果（本地与云端）均未实测。
