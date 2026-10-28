# 第二阶段实施与材料入口

更新至2026年10月28日。系统版本2.0.0，在第一阶段代码和数据上扩展八项变更。初次交付260项及全新Python环境260项通过；最新完整功能复查309项通过、33个浏览器场景通过；固定样本真实操作记录至HM2-72，页面、服务调用和实际操作者分别标明。

当前固定样本补测后为15用户、15问卷、42答卷。第一阶段原9用户/8问卷/33答卷，以及补测前12用户/10问卷/36答卷，属于不同时间节点；原记录和统计已核对保持。数据及归档口径见[数据说明](data.md)。

| 内容 | 文件 |
| --- | --- |
| 运行与新环境启动 | [项目README](../../README.md) |
| 完整安排及76个场景 | [第二阶段执行计划](../../第二阶段执行计划.md) |
| 八项需求和实际范围 | [需求与验收范围](requirements.md) |
| 业务规则与设计取舍 | [设计决策](decisions.md) |
| 当前进度与验证节点 | [实施状态](status.md) |
| 原代码与实际数据基线 | [M1基线记录](baseline.md) |
| 系统与数据库设计 | [架构](architecture.md)、[MongoDB设计](database.md) |
| 接口与关键逻辑 | [API](api.md)、[关键规则](rules.md) |
| 统一测试结果 | [测试用例与结果](tests.md)、[逐项验收](acceptance.md) |
| 用户执行与AI接手补测 | [真实操作测试记录](manual-acceptance.md) |
| 数据节点及迁移恢复 | [数据说明](data.md)、[迁移记录](migration.md) |
| 完整报告与演示 | [项目报告](report.md)、[演示步骤](demo.md) |
| 学生作用与真实AI过程 | [AI使用说明](ai-use.md)、[AI协作日志](ai-log.md) |
| 第二阶段提交入口 | [材料索引](../submissions/stage2/README.md) |

第一阶段材料和教师原始要求保留。第二阶段验证证据单独置于 `docs/evidence/stage2/`，历史失败与各批次结果不覆盖。新环境演示seed用于新建虚构样本，不能代替已有业务库的恢复与迁移；现有10月26日归档不包含之后新增的A～E样本。

提交整理已补充两份最终报告的DOCX/PDF，共24页完成检查；候选ZIP解压源码在既有venv和独立空测试库下30/30冒烟检查通过，临时库及配置已清理。本轮证据见[解压包冒烟](../evidence/stage2/submission-2026-10-28/extracted-package-smoke.json)和[文档检查](../evidence/stage2/submission-2026-10-28/document-quality-check.json)；不改称重新执行309项回归或全新环境260项。

当前按用户要求改为直接提交[仓库P1-stage2分支](https://github.com/betterGuo/Contemporary-data-management-system-Projects/tree/P1-stage2)，第一阶段P1保持。报告开头已注明仓库及分支，DOCX/PDF已同步重新导出，当前四份文档见[Git版质量记录](../evidence/stage2/submission-2026-10-28/git-branch-document-quality-check.json)。上述ZIP及冒烟描述仅保留已执行历史，不作为当前交付步骤。
