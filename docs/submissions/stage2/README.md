# 第二阶段材料索引

系统版本2.0.0，材料更新至2026年10月28日。本目录是材料索引；本次直接提交仓库[Contemporary-data-management-system-Projects](https://github.com/betterGuo/Contemporary-data-management-system-Projects)的[第二阶段分支`P1-stage2`](https://github.com/betterGuo/Contemporary-data-management-system-Projects/tree/P1-stage2)，完整保留可运行代码、配置示例、技术文档、测试、报告和证据的项目树。第一阶段对应[P1分支](https://github.com/betterGuo/Contemporary-data-management-system-Projects/tree/P1)。不以ZIP交付，也不能只提交本索引所在的子目录。

## 阅读顺序与最终文档

先阅读项目报告和测试结果，再按技术文档及证据链接核查。PDF用于直接阅读，DOCX用于编辑，Markdown保留源码及相对证据链接。

| 文档 | PDF | 可编辑DOCX | Markdown来源 |
| --- | --- | --- | --- |
| 项目完成报告 | [阅读报告](../../../output/stage2/第二阶段项目完成报告.pdf) | [编辑报告](../../../output/stage2/第二阶段项目完成报告.docx) | [报告源文档](../../stage2/report.md) |
| 测试用例与结果 | [阅读测试材料](../../../output/stage2/第二阶段测试用例与结果.pdf) | [编辑测试材料](../../../output/stage2/第二阶段测试用例与结果.docx) | [测试总览](../../stage2/tests.md)、[真实操作记录](../../stage2/manual-acceptance.md) |

最终报告覆盖原文九项主题及第二阶段八点演进说明；AI部分采用学生第一人称，写清学生提出的问题、方案取舍、修订意见及实际验收，与AI编码和自动测试的分工分别记录。

## 按实验要求核对提交内容

| 原文要求 | 提交位置与核对结果 |
| --- | --- |
| 可运行代码：后端、MongoDB结构、配置说明 | app、scripts、deploy、依赖锁与根README齐全；保留第一阶段系统，在原代码上增加第二阶段模块 |
| 技术文档：系统说明、数据库设计、API、关键逻辑 | docs/stage2中的architecture、database、api、rules及迁移说明齐全；MongoDB设计的三项说明已展开 |
| 测试用例：步骤、输入、输出、结果 | 测试DOCX/PDF、tests.md代表用例表、真实操作步骤、自动逐例结果及原始证据齐全；各执行批次和覆盖边界分别标明 |
| 完整报告及第二阶段演进说明 | 报告按目标、系统、MongoDB、跳转、校验、AI、测试、问题、解决方法九项组织；系统设计表逐项回答八点演进要求 |
| AI日志与报告AI四问 | ai-log记录工具、提示词、代码产物、是否修改及修改内容；报告及ai-use回答AI帮助、错误、本人修改和本人设计，并说明实际分工 |

教师原文见[第一阶段要求](../../../大作业一第一阶段.docx)和[需求变更](../../../大作业一：需求变更.docx)。Word、PDF与Markdown直接保存在分支对应目录，方便阅读与编辑；原文未额外规定必须提供压缩包、视频、固定截图数量或最新业务库BSON实体。

## 可运行代码与配置

- [完整前后端源码](../../../app)、[脚本](../../../scripts)、[测试源码](../../../tests)。
- [第二阶段集合及索引](../../../app/library_database.py)、[原结构兼容初始化](../../../app/database.py)。
- [依赖锁](../../../requirements.lock)、[项目配置](../../../pyproject.toml)、[环境示例](../../../.env.example)、[副本集部署](../../../deploy/stage2.compose.yaml)。
- [项目根运行说明](../../../README.md)：新空环境初始化与虚构演示、旧库延续与迁移分别说明。
- [参考与归档说明](REFERENCE_NOTES.md)：BSON不公开提供、历史宿主路径与仓库相对链接范围。

新环境运行会创建自己的配置、身份密钥和虚构演示ID，不承诺复现本地历史15用户、15问卷、42答卷或固定回执。远端分支不提交私密.env、原HMAC密钥、sessions、原始BSON、虚拟环境和缓存。

## 技术文档

- [八项需求对照](../../stage2/requirements.md)、[设计取舍](../../stage2/decisions.md)。
- [系统说明](../../stage2/architecture.md)、[MongoDB设计](../../stage2/database.md)。
- [API说明](../../stage2/api.md)、[关键逻辑](../../stage2/rules.md)。
- [数据与样例说明](../../stage2/data.md)、[迁移与恢复](../../stage2/migration.md)。
- [演示步骤](../../stage2/demo.md)、[实施状态](../../stage2/status.md)。

## 测试用例与结果

| 批次 | 已执行结果 | 对应材料 |
| --- | --- | --- |
| 初次交付与全新环境复现 | 原交付260项通过；全新Python环境260项通过；浏览器15流程 | [初次交付结果](../../evidence/stage2/final-2026-10-26/regression/test-results.json)、[全新环境](../../evidence/stage2/final-2026-10-26/clean-environment/reproduction.json)、[15流程](../../evidence/stage2/browser-2026-10-26/attempt-4/browser-results.json) |
| 功能复查 | 309项通过、0失败、0跳过；33场景为32项UI及1组API权限负例 | [复查说明](../../stage2/recheck-2026-10-26.md)、[逐例结果](../../evidence/stage2/recheck-2026-10-26-363f82/regression-final/test-results.json)、[浏览器总览](../../evidence/stage2/recheck-2026-10-26-363f82/browser/final-summary.json) |
| 固定样例真实操作 | 前段用户亲测、后段AI接手，记录至HM2-72；服务调用与页面操作分开 | [步骤输入输出与结果](../../stage2/manual-acceptance.md)、[补测证据清单](../../evidence/stage2/manual-acceptance-2026-10-26/hm2-ai-takeover-completion-2026-10-28.json) |
| 10月28日提交包独立冒烟 | 从候选ZIP重新解压，复用现有Python3.12.6的venv与新随机空库，30/30检查通过；不计入309项或全新环境260项 | [解压包冒烟](../../evidence/stage2/submission-2026-10-28/extracted-package-smoke.json)：启动、登录、页面与静态资源、seed幂等、3/3/2均值20及权限隔离；随机库与临时.env已清理 |

- [最终测试总览](../../stage2/tests.md)、[76场景逐项对照及覆盖边界](../../stage2/acceptance.md)。
- [双实例正式样例](../../evidence/stage2/manual-acceptance-2026-10-26/hm2-65-68-E-formal-double-instance-check-2026-10-28.json)：6与10对应2次回答、1份答卷、1份问卷、均值8。
- [过期编辑页保存冲突](../../evidence/stage2/manual-acceptance-2026-10-26/hm2-69-72-two-tab-conflict-final-check-2026-10-28.json)：A生成最大16的副本v2，B输入8保留且未生成v3。
- [补测后旧数据完整性](../../evidence/stage2/manual-acceptance-2026-10-26/hm2-post-cas-original-data-integrity-2026-10-28.json)：原始业务文档子集与原统计保持。
- [正式迁移](../../evidence/stage2/development-2026-10-26/final-migration-apply.json)、[幂等重跑](../../evidence/stage2/development-2026-10-26/final-migration-repeat.json)、[恢复清单](../../../artifacts/stage2/stage2-v2.0.0.archive.gz.manifest.json)。

这些批次分别保留，不能相加为新的用例总数，也不能把原生弹窗受阻部分或AI自动操作写成用户完整亲测。30项提交包冒烟由TestClient及真实MongoDB执行，未重新安装依赖或重跑完整回归，不能称为新一轮浏览器测试。

报告与测试材料均有PDF和DOCX版本。此前[文档质量检查](../../evidence/stage2/submission-2026-10-28/document-quality-check.json)作为历史记录保留；本次报告补充仓库与分支说明并重新导出，当前四份文件的哈希、中文、表格、分页、页码、相对链接及DOCX结构见[Git分支版文档检查](../../evidence/stage2/submission-2026-10-28/git-branch-document-quality-check.json)。

最后一轮从实际ZIP重新核对教师原文、报告/测试/数据一致性与全部218张图片；修正验收矩阵初次260项证据说明的范围，以及五张实际JPEG截图的扩展名。必交内容齐全，未发现私密或不应提交的文件，详见[最终内容复核](../../evidence/stage2/submission-2026-10-28/last-review-content-and-requirements.json)及[截图更正映射](../../evidence/stage2/submission-2026-10-28/last-review-screenshot-format-correction.json)。该次审计保留了当时四份DOCX/PDF的字节一致性；本次报告增加分支说明，业务源码、原始测试结果及截图字节继续保持。

## AI使用过程与原阶段对照

- [学生第一人称AI使用说明](../../stage2/ai-use.md)：十组设计讨论、本人参与验收和实验四问。
- [真实AI日志](../../stage2/ai-log.md)：工具、原始提示词、代码产物、修改内容与实际归属。
- [第二阶段执行计划](../../../第二阶段执行计划.md)、[第一阶段原提交材料](../stage1/README.md)。

教师原始DOCX、第一阶段文件及原始失败证据继续保留。对当前公开材料中的不可移植链接采用相对路径或归档清单链接，历史执行日志与原始截图内容不改写；具体范围见[参考与归档说明](REFERENCE_NOTES.md)。

## 分支提交与核对方式

第二阶段分支`P1-stage2`直接包含源码、技术文档、证据，以及`output/stage2/`中的四份Word/PDF文件，不推送ZIP或`dist/`目录。按[根README](../../../README.md)安装锁定依赖并运行演示；核对实际提交内容时以该分支的文件树和Git提交记录为准。

本次分支提交保留第一阶段远端`P1`，不改写其历史。本机私密配置、原始业务库BSON、会话、虚拟环境、缓存、临时测试目录和QA渲染图不提交。此前ZIP构建器及相关审计日志仅记录已经执行的整理过程，不是当前提交的必需步骤，也不代表本轮再次运行309项回归或33个浏览器场景。
