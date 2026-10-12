# 有证据的知识关系与完整分析包

本地提取不产生语义判断。Agent 读取本次运行的原稿、校对记录、阅读分块和必要的视觉资料后填写分析包；脚本负责验证与展示。

## 两段执行

```bash
python scripts/pipeline.py "课程目录" ./out --visual --frame-interval 60
# 本次运行目录 R 见 out/summary.json 的 artifacts_dir
# R/分析包待填写.json 已自动生成，先复制成自己的分析包再填写
python scripts/analysis_bundle.py --summary ./out/summary.json --analysis ./my-analysis.json --out ./analysis-result
# 也可整合回一次流水线运行；只要原稿哈希一致即可复用分析包
python scripts/pipeline.py "课程目录" ./out --analysis-json ./my-analysis.json
```

`--guide-json` 只验证旧指南格式；`--analysis-json` 才验证完整证据结构。二者不能同时提供。单独运行 analysis_bundle 不重新转写。输出目录非空会拒绝覆盖，换新目录保存新版本。

## 数据契约（version=1）

- `status`：填写完成后设 `ready`；模板默认 `draft`，不能伪装完成。
- `source_hashes`：source_id → 本次原稿 JSON SHA256。来源集合必须完全一致，不允许拿其他课程的分析包混入。
- `analyses`：每条视频恰好一项，含 source_id、read_ranges、sections、section_notes。章节是概念、论证、案例与计算、操作步骤、适用条件、例外、待核对；值为 claim ID 数组。没有内容的章节必须说明“原文未提供”或“待核对”，不凭空补齐。
- `read_ranges`：报告已读原稿的区间 [[开始秒,结束秒],...]，要覆盖全时长。程序查缺口，不证明 Agent 实际阅读过，更不证明已经看过全部画面。
- `claims`：id、text、origin（讲师观点/整理者推断）、conditions、evidence。任何结论都须有证据。
- `relations`：id、from、to、type、explanation、origin、conditions、evidence。不根据共现自动生成关系。没有可靠关系可以留空。
- `synthesis`：一致、互补、冲突、未解决四组 claim ID；空组用 synthesis_notes 明确原因。
- `acceptance`：至少3组 question、answer、claim_ids，用真实学习问题检查可用性。
- `guide`：guide_builder 的内容 JSON，附 claim_bindings。概述、概念解释、操作、误区、实例、自测、前置与行动等正文位置必须绑定 claim ID。格式为 JSON pointer，例如 `/steps/0/items/0/text`: ["c1"]。

每条 evidence：`source_id`、`start`、`end`、`quote`、`verification`。start/end 是秒，须在来源时长范围内且 start < end；quote 必须存在于范围内的原始机器提取稿，不能用润色后的校对句子冒充原文。verification 为 machine 或 video_checked；后者只是填写者报告已核对视频，不是脚本自动验证的结果。数字、术语和画面操作需实际复查。

## 关系方向

| 类型 | from → to 的含义 |
|---|---|
| 前提 | 前提条件 → 依赖该条件的判断/动作 |
| 步骤 | 在先动作 → 后续动作 |
| 因果 | 原因 → 结果，须说明条件与依据 |
| 例外 | 一般规则 → 不适用情形 |
| 冲突 | 两个不相容观点；没有先后含义，展示为双向关系 |

冲突关系必须附两端观点的来源证据。引文匹配只证明引文和时间范围存在，不能自动证明引文足以支持因果、结论或全文事实。

## 产物与验收

产出逐视频内容分析 MD、跨视频综合 MD、分析包 JSON、学习指南 HTML、知识关系图 HTML、验收记录 JSON。关系图可按类型筛选、展开原稿和核对时间点；原视频链接能否自动跳转取决于本地播放器。文字证据在页面内可离线读。

现有术语共现图继续用于检索出处，两种图不混为一谈。原始提取目录不修改；本次运行原稿快照让后续缓存更新不影响已归档的证据。
