# 通义千问／阿里云百炼自动蒸馏

无需在电脑上运行分析用大语言模型。视频文字提取和产物渲染仍在本地，分块分析与综合由百炼 API 完成。无字幕视频的本地 ASR 仍需安装提取依赖和转写模型。

## 配置与运行

在阿里云百炼开通模型服务并创建 API Key。示例使用北京地域的 `qwen-plus` 和官方仍可使用的兼容入口。切换地域必须使用对应地域的 Key；若采用业务空间专属域名，从控制台复制实际地址。

```powershell
Copy-Item examples/bailian.config.example.json bailian.config.json
# 在当前 PowerShell 窗口读取 Key，不显示、不写入 JSON 或命令历史
$env:DASHSCOPE_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host '输入百炼 API Key' -AsSecureString)).Password
python scripts/pipeline.py 'G:/课程视频' ./out --llm-config ./bailian.config.json
# 可选：本地视觉采样和知识技能包
python scripts/pipeline.py 'G:/课程视频' ./out --llm-config ./bailian.config.json --visual --skill-bundle
```

不传百炼配置时继续原来的本地提取、Agent 或本地模型方式。已有原稿可以直接执行：

```powershell
python scripts/auto_distill.py --summary ./out/summary.json --config ./bailian.config.json --out ./bailian-result --cache ./out/模型缓存
```

单独分析的输出目录须为空。重跑可换新输出目录并共享同一缓存。CLI 的 --model 是语音转写模型；千问模型名写在百炼 JSON 配置的 model 中。模型名可改为百炼账户中支持 JSON 与本流程非思考参数的千问文本模型；不同模型能力并不相同，默认示例不代表所有模型都已实测。

## 入口与 Key

| 用途 | base_url 示例 |
|---|---|
| 北京兼容入口（默认示例） | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 北京业务空间入口 | `https://实际WorkspaceId.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` |
| 新加坡兼容入口 | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` |
| 新加坡业务空间入口 | `https://实际WorkspaceId.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` |

示例里的业务空间 ID 必须替换为控制台实际值。客户端只接受已支持的百炼官方 HTTPS 兼容入口，拒绝账号嵌入 URL、非官方域名和重定向。Key 只从 `api_key_env` 指定的环境变量读取，默认 `DASHSCOPE_API_KEY`；本地配置已被 gitignore 排除，公共示例不含 Key。

开始提取前检查环境变量是否存在；这不证明 Key 有效或地域匹配。实际鉴权在首次 API 调用时发生。401 提示核对 Key 与地域，403 提示服务/权限，404 提示模型/业务空间/路径。错误报告不记录服务返回的敏感正文。

## 发送范围与费用记录

- 只有明确选择 `provider: bailian` 才发送云端请求；本地服务失败不会自动切到百炼。
- 请求包含系统提示、原稿片段、标题、综合判断，以及启用 OCR 时的机器文字。视频、音频、图片文件不作为请求附件上传，Key 不进入提示词。
- 输出采用 JSON、非思考模式，关闭联网搜索；原始引用、关系、条件、指南绑定沿用本地验证，并有限次数修订。
- 原稿、自动结果和缓存落在本地。云端运行的摘要明确标为 `text_to_bailian_cloud`，不能称全程离线。
- 每次响应与总摘要记录服务报告的输入/输出/总 Token 数及请求次数；缓存命中不发 API 请求。修订和重试可能增加用量。
- 没有 usage 的请求单列为 `requests_without_usage`，不能据此判断免费；请求发出后超时也可能已被服务处理。币种金额不硬编码，以百炼账户账单和当前模型/地域价格为准。

机器结构验证不保证知识正确，真实课程的重要数字、术语、因果和画面仍需核对。生成技能包只保存到本地，不自动安装或发布。

## 当前验证状态

适配器、鉴权头、JSON 参数、错误处理、Token 汇总、修订、缓存及完整流水线通过本地模拟服务测试。2026-10-12 已使用用户授权的一分钟视频验证真实北京 qwen-plus，最终完整流水线及证据结构校验通过。真实测试发现并修复了JSON格式示例与修订错误截断问题；同时发现疑似ASR错词被模型解释为ROI的语义风险，内容仍需人工复核。具体用量、失败轮次和边界见[公开验证记录](../docs/验证记录.md)。跨视频及其他模型/地域未做真实验收。

## 可选费用上限

北京默认入口的 `qwen-plus` 配置可加入 `max_cost_cny: 2` 和 `budget_ledger: "本机费用记录的绝对路径"`。启用后按 2026-10-12 核对的非思考、输入不超过128K档位价格（输入0.8元/百万 Token、输出2元/百万 Token）预留每次调用费用；输入按 UTF-8 字节加4096的保守上界，输出按最大长度。每次重试都预留，缓存不收费；同一 ledger 跨重跑累计，不退回超时或失败请求的预留。超预算、档位不符或记录被占用时停止发送。

这是基于所核对价格的预算保护，预留金额不是实际账单；价格调整后须重新核对代码中的档位与价格。未设置 ledger 时不会启用金额上限。当前不支持其他模型或地域的金额保护。完成后打开输出目录的 `结果入口.html`。

官方来源（2026-10-12 核对）：[兼容入口及地域要求](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[结构化输出](https://help.aliyun.com/en/model-studio/qwen-structured-output)、[API Key](https://help.aliyun.com/zh/model-studio/get-api-key)、[qwen-plus 模型信息](https://help.aliyun.com/zh/model-studio/qwen-plus)。
