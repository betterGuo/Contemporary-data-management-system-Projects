# 第二阶段旧数据迁移说明

本次迁移把第一阶段问卷中的题目登记为独立题目和正式版本，补充来源及使用历史。原问卷快照、实例ID、选项、题序、跳转、发布状态、业务版本和旧答卷继续保留。迁移脚本不重新生成演示数据，也不把同名或同义题自动合成一题。

## 已完成的演练与当前边界

2026年10月26日已把M1归档恢复到隔离预览库 `survey_project1_stage2_preview`，在27018的 `survey-rs` 上执行迁移：

| 核对内容 | 实际结果 | 证据 |
| --- | --- | --- |
| 实际副本集事务 | commit和rollback验证通过 | 环境执行记录，由最终实施索引统一收录 |
| 定义与实例登记 | 8份问卷定义、25个实例，绑定25，完成定义8，改写答卷0 | [preview-migration.json](../evidence/stage2/development-2026-10-26/preview-migration.json) |
| 旧用户 | 原9个用户逐条BSON一致 | [preview-legacy-preservation.json](../evidence/stage2/development-2026-10-26/preview-legacy-preservation.json) |
| 旧答卷 | 原33份答卷逐条BSON一致 | 同上 |
| 原定义和统计 | 8份旧问卷内容、ID、规则、业务状态及统计一致 | 同上 |

当时原库没有历史survey_versions文档；历史版本映射及缺失定义另有隔离测试，不把原库数量0写成已有真实历史样本。预览库用于浏览器QA，未直接上线。正式切换已另外从最终备份恢复到空目标，dry-run预计25实例、apply绑定25、repeat新增0；[最终保留核对](../evidence/stage2/development-2026-10-26/final-legacy-preservation.json)通过。

正式切换归档为`artifacts/stage2/pre-upgrade-2026-10-26-v2.archive.gz`；升级后的完整归档为`artifacts/stage2/stage2-v2.0.0.archive.gz`，SHA-256为`549a01999c463a1f0b3f2a45674d89755a4351cb2366f182f30e8bc2227d3b59`。[最终恢复清单](../../artifacts/stage2/stage2-v2.0.0.archive.gz.manifest.json)验证12个业务集合、10份定义统计及恢复库登录/列表。原27017库保留，应用`.env`只切换URI，HMAC密钥及key version保持。新增虚构示例后正式库为12用户/10问卷/36答卷，原9/8/33逐条仍保留。

## 数据和环境前提

M1当前基线为9用户、8问卷、33答卷，归档是 `artifacts/stage2/m1-2026-10-26-f628973f.archive.gz`。原更早的stage1归档与标签同样保留。迁移前必须重新核对执行当时的实际数据，不能假定未来永远保持这些数量。

原27017实例还承载其他课程数据，第二阶段使用 `deploy/stage2.compose.yaml` 中的独立容器、27018端口和独立持久卷。首次启动新实例后需完成副本集初始化并等待可写主节点，连接串为：

```text
mongodb://localhost:27018/?replicaSet=survey-rs
```

该地址不是密钥。原 `.env` 中的HMAC secret和key version必须私密延续；不能在重新启动时生成新密钥，否则旧匿名防重复身份不能延续。配置及本地恢复副本不提交到公共材料。

## 显式脚本与幂等流程

入口为 `scripts/migrate_stage2.py`，参数包括 `--uri`、`--database`、`--apply` 和必填 `--output`。默认dry-run；报告已存在时拒绝覆盖。`--apply` 检查实际事务拓扑后初始化schema，再调用正式迁移。普通应用启动只维护schema和索引，不自动迁移全库。

迁移算法为：

1. 枚举当前问卷与现有历史定义，确认每份旧答卷引用的问卷版本均可找到。
2. 检查所有者、实例ID唯一性、已有引用及版本内容hash，不猜测缺失身份或用当前定义代替历史。
3. 对缺来源的实例使用稳定旧来源键 `(surveyId, definitionVersion, instanceId)`，创建私有独立题目及v1、可选状态、本人收藏和“第一阶段导入”标签。
4. 同一事务写入该定义的questionRefs和存量usage。旧快照不规范化重写、不重新编号；已发布/关闭来源设置永久发布引用标记。
5. 只增加结构关联，schemaVersion变为2；definitionVersion不变，responses不修改。
6. 按定义逐笔提交并保存结果。中断后再次运行复用已有来源，完成后第二次执行应无新增绑定；正式完成标记保存在schema_migrations。

原始独立问卷中相同标题缺乏来源证据，分别建立根身份。此后明确复用或派生才形成可追溯共同来源。usage只覆盖迁移时存在的关联及之后记录的行为，observedAt为登记时间，不伪造原始首次使用时间，也无法补回迁移前已删除记录。

## 演练命令示例

以下使用尚不存在的隔离库；目标若已有数据应先检查，不覆盖。每次报告使用新路径，示例路径只作操作说明，不代表这些具体命令均已再执行一遍。

```sh
mongorestore --uri='mongodb://localhost:27018/?replicaSet=survey-rs' --archive=artifacts/stage2/m1-2026-10-26-f628973f.archive.gz --gzip --nsFrom='survey_project1.*' --nsTo='survey_project1_test_stage2_review.*'
.venv/bin/python scripts/migrate_stage2.py --uri='mongodb://localhost:27018/?replicaSet=survey-rs' --database=survey_project1_test_stage2_review --output=docs/evidence/stage2/review-dry-run.json
.venv/bin/python scripts/migrate_stage2.py --uri='mongodb://localhost:27018/?replicaSet=survey-rs' --database=survey_project1_test_stage2_review --apply --output=docs/evidence/stage2/review-apply.json
.venv/bin/python scripts/migrate_stage2.py --uri='mongodb://localhost:27018/?replicaSet=survey-rs' --database=survey_project1_test_stage2_review --apply --output=docs/evidence/stage2/review-repeat.json
.venv/bin/python scripts/verify_stage2_upgrade.py --source-uri='mongodb://localhost:27017/' --target-uri='mongodb://localhost:27018/?replicaSet=survey-rs' --source-database=survey_project1 --target-database=survey_project1_test_stage2_review --output=docs/evidence/stage2/review-preservation.json
```

## 迁移后核对

`verify_stage2_upgrade.py` 对原users和responses逐条按_id查找并比较BSON；问卷允许新增questionRefs并更新schemaVersion，投影回原业务字段后仍必须逐条BSON一致。每个实例有匹配来源版本，旧统计按问卷及业务版本逐项相同。目标允许额外的新记录，因此验证不能只比较集合总数，也不能把用户合法新增记录误判为丢失旧数据。

还需要在恢复环境验证旧账号登录、原分享链接、特殊实例ID和旧提交幂等重放。迁移后从某个旧题选入新问卷并回答，才能证明旧数据真正进入新能力；不能只把旧系统留在另一个数据库作展示。

## 正式切换与失败恢复

正式切换顺序为：停止旧应用写入，生成最终备份，恢复到全新的正式目标库，重新执行迁移与核对，确认原身份配置，再切换应用连接。演练期间源库可能新增回答，因此不能直接使用早期预览副本。

保持原共享数据库、旧归档和私密配置恢复副本。开放新写入前失败，可停止目标应用并切回未修改原库；开放后已有第二阶段新记录时，应先停写并保全新增数据，不能直接用旧备份覆盖而丢失新回答。不得双端同时写入。

迁移中发现缺历史定义、无所有者、重复实例、内容与来源不一致时停止并报告，先修复事实问题。目标库升级期间不接受管理和填写写入；未完成映射的已答定义会使跨卷统计返回MIGRATION_INCOMPLETE，不静默漏算为0。

正式阶段的备份和恢复需覆盖questions、versions、state、grants、bookmarks、usage、operation_receipts及管理员审计等全部新增业务集合。sessions仍按可重新登录的临时状态排除，初始化、登录等验证只在恢复副本上执行。
