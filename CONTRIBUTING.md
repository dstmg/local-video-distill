# 参与开发

先阅读README和新手教程。修复问题或新增功能请提交PR，说明触发条件、最终行为与验证方式。保持原稿不可变、校对副本独立、证据可追溯；不要把共现连边当成因果。

从根目录执行：

```shell
python -X utf8 -m unittest discover -s scripts -p "test*.py" -q
python -X utf8 -m compileall -q scripts
```

CI运行标准库测试及可选pypinyin，不上传素材、不调用付费模型、不要求API Key。真实模型实测应另行获得素材和费用授权，记录用量及质量局限。

提交前排除真实课程、模型权重、缓存、Key、个人配置和内部对话。examples仅使用虚构或自造素材。报告问题时提供脱敏日志、系统/Python版本与最小复现；不要公开Key或受限制的原稿。
