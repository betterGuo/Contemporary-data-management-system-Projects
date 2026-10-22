# 关键验证证据

本目录只保留助教核对主要结论所需的五份结果，日期、测试数量和实际结果保持原记录。

| 文件 | 内容 |
| --- | --- |
| [最新逐项测试](stage1/final-review-2026-10-22/test-results.json) | 2026-10-22完整200项通过；每个测试节点、结果及源码SHA-256 |
| [最新原始输出](stage1/final-review-2026-10-22/pytest-output.txt) | 同次200项通过、1项第三方弃用提醒、13.18秒 |
| [数据库统计基准](stage1/baseline-verification.json) | 固定数据统计、含0的数字均值、索引和查询计划 |
| [新环境复现](stage1/reproduction.json) | 2026-10-22远端P1新克隆；Python 3.12.6、MongoDB 8.0.34；新环境200项通过、初始化与种子幂等、31项HTTP检查、浏览器基准及资源清理 |
| [历史旧数据扩展演练](stage1/recheck-extension.json) | 2026-10-20隔离恢复、迁移幂等、旧答卷及旧统计保留 |

旧数据扩展记录中的备份路径和旧Git标签属于当时的本机来源，不表示公开仓库包含这些文件或历史对象。新环境复现记录已更新为本次实际结果；10月20日197项的原记录保留在[此前P1提交](https://github.com/betterGuo/Contemporary-data-management-system-Projects/blob/eba11e6552da86f0d9de30fc4a7d5a16bcc6fb84/docs/evidence/stage1/reproduction.json)中。新环境pytest原始输出和逐项HTTP检查的本机记录没有另加为提交文件。其他专项结果、浏览器截图、人工数据库读回及内部自检材料留在本机，实际范围仍在测试说明与AI日志中如实记载。原始日志中的本机绝对路径替换为`<LOCAL_PROJECT_ROOT>`或`<LOCAL_HOME>`，测试结果与时间未改。
