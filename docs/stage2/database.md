# 第二阶段 MongoDB 数据库设计

本阶段沿用第一阶段的用户、会话、问卷和答卷结构，增加独立题目、正式版本、版本可选状态、个人收藏、共享授权、使用历史和操作回执。问卷继续保存冻结内容，答卷继续按原问卷版本和实例ID解释。具体迁移执行结果以迁移证据和[实施状态](status.md)为准，本文说明已落地代码的数据设计。

实现入口为 `app/database.py`、`app/library_database.py`、`app/services/library_service.py`、`question_reference_service.py` 和 `library_migration.py`。

## 原结构与新增关联

第一阶段的 `surveys.questions[]` 是完整题目定义，`responses.answers[].questionId` 指向其中的问卷实例ID。第二阶段保留这两种含义，在问卷旁增加 `questionRefs[]`，不把旧答案中的实例ID替换成独立题目的ObjectId。

| 身份 | 含义 | 使用场景 |
| --- | --- | --- |
| questionId | 独立题目，BSON ObjectId | 所有权、共享、正式版本序列 |
| questionVersionId / versionId | 不可变题目版本，BSON ObjectId | 明确选用、快照核对、跨卷统计 |
| rootQuestionId | 最初来源，BSON ObjectId | 记录来源家族；不授予权限，不默认合并统计 |
| derivedFromVersionId | 直接依据的旧版本 | 修订、恢复和派生历史 |
| instanceId | 问卷中的一次出现，原有不透明字符串 | 题序、跳转、答案定位、同卷重复选题 |
| definitionVersion | 整份问卷的内容版本 | 历史定义读取、旧答案解释 |
| revision | 可变记录的并发修订号 | 管理记录或状态记录的条件更新 |

同题可在同卷出现两次，各有自己的 instanceId，但指向同一版本。独立创建的同名题分别生成 questionId 和 root，不凭相似标题自动合并。

## 集合及主要字段

| 集合 | 主要字段 | 一致性和权限含义 |
| --- | --- | --- |
| users | 原账号字段，可选 role | 缺role按普通用户处理；admin只扩展公共题维护，不扩展私人答卷读取 |
| sessions | 原令牌摘要、userId、expiresAt | 延续登录、CSRF与TTL，不在业务备份中延续会话 |
| surveys | 原定义、questions、questionRefs、revision、definitionVersion | 快照和当前关联同文档保存；发布冻结 |
| survey_versions | surveyId、definitionVersion及历史定义、questionRefs | 如有历史版本，按其原实例映射，不读取最新版代替 |
| responses | 原surveyId、surveyDefinitionVersion、respondentKey、answers等 | 旧BSON、payloadHash及幂等键不因题库迁移重写 |
| questions | ownerId、createdBy、rootQuestionId、visibility、status、workingContent、workingContentHash、workingBaseVersionId、latestVersionId、latestVersionNumber、revision、hasPublishedUsage、selectionGuard、时间戳 | 可变编辑稿与管理记录；已被发布问卷用过后禁止普通稿覆盖；归档停止新增选用 |
| question_versions | questionId、versionNumber、content、contentHash、derivedFromVersionId、createdBy、changeReason、createdAt | 正式内容只插入，不覆盖或物理删除 |
| question_version_state | versionId、selectable、revision、selectionGuard、changedBy、changedAt | 版本下架只改可选状态，保留版本正文和旧快照 |
| question_bookmarks | userId、questionId、selectedVersionId、tags、revision、时间戳 | 同一道共享题的标签属于整理者本人，不写回源题 |
| question_grants | questionId、granteeId、active、revision、selectionGuard、授权者及时间 | 精确到独立题目，不覆盖root家族；共享不授予答卷读取权 |
| question_usage | surveyId、surveyDefinitionVersion、instanceId、questionId、versionId、rootQuestionId、surveyOwnerId、isCurrent、surveyDeleted、observedAt、origin | 当前关系更新时登记真实使用历史；移除只关闭当前状态，不删除历史累计 |
| operation_receipts | actorId、operation、requestKey、payloadHash、result、createdAt | 保存/选用/派生等重试得到同一个结果；无短TTL使旧重试重新执行 |
| schema_migrations | 原迁移记录及002_question_library状态 | 显式迁移、完成标记和核对摘要；普通启动不自动迁移全库 |
| admin_audit | 操作来源、targetUserId、role、createdAt | 本地受控管理员授予或撤销记录，不提供客户端自行提权入口 |

版本内容仅包括 `type/title/required/options/validation`。问卷实例的ID、题序和跳转不属于通用题目版本。选题时新建实例，选项ID保持版本中的值，跳转初始为空；不能把另一份问卷的目标ID直接复制过来。

```json
{
  "questionRefs": [{
    "instanceId": "原问卷实例ID",
    "questionId": "独立题目ObjectId",
    "questionVersionId": "正式版本ObjectId",
    "rootQuestionId": "最初来源ObjectId",
    "contentHash": "规范内容摘要"
  }]
}
```

上例为便于阅读的JSON，数据库中的三类来源ID实际为ObjectId，API经DTO转换为字符串。管理DTO返回来源，填写DTO不返回共享名单、内部来源管理信息或身份键。

## 索引和文档校验

`initialize_library` 为新增集合建立JSON Schema和索引，不删除旧文档。Schema要求主要ID类型、状态枚举、布尔开关、内容对象和修订号等；具体题型字段仍由领域校验器检查，Schema不代替当前用户的所有权判断。

| 索引 | 约束或查询用途 |
| --- | --- |
| questions.owner_library / public_library | 本人及公共列表的状态、更新时间查询 |
| questions.question_lineage | 来源根查询，不等于授权查询 |
| questions.legacy_origin_unique | 迁移来源键存在且为字符串时唯一，避免重跑重复建题 |
| questions.public_code_unique | 可选公共编号存在时唯一，编号不含版本号 |
| question_versions.question_version_unique | `(questionId, versionNumber)` 唯一 |
| question_versions.direct_version_source | 直接来源追溯 |
| question_version_state.version_state_unique | 一个版本只有一条状态记录 |
| question_bookmarks.bookmark_unique / personal_tags | 每人每题一条收藏、个人标签过滤 |
| question_grants.grant_unique / received_grants | 每题每接收者一条授权、“共享给我”查询 |
| question_usage.usage_unique | `(surveyId, surveyDefinitionVersion, instanceId, versionId)` 唯一 |
| question_usage.question_usage_counts / version_usage | 独立题目或版本的历史问卷去重计数 |
| surveys.owner_version_instances / owner_question_instances | 本人问卷的来源绑定定位 |
| responses.definition_responses | 问卷定义版本内的答卷读取与稳定排序 |
| operation_receipts.operation_idempotency | `(actorId, operation, requestKey)` 唯一 |

保留用户名、会话、分享链接、原答卷幂等和单次填写限制的旧索引。数组匹配和统计保留 `(surveyId, definitionVersion, instanceId)` 的元组关系，不使用几份独立ID列表拼出不真实的关联。

## 事务和并发边界

题库多文档写入要求实际副本集或分片事务能力。当前实现使用同一session的 `with_transaction`，read concern为snapshot、write concern为majority，操作读取主节点；不在单机部署上静默改成两个无事务写入。开发环境不因启用副本集就被描述为高可用环境。

| 业务动作 | 一起提交的写入 |
| --- | --- |
| 保存正式版本 | 管理记录CAS及编号递增、正式版本、初始版本状态、幂等回执 |
| 选入草稿 | 题目/版本/必要授权的guard、问卷快照和引用、usage、幂等回执 |
| 显式升级 | 草稿实例内容及引用、旧usage当前状态关闭、新usage登记、回执 |
| 发布问卷 | 补登记未关联本地题、usage、源题发布引用锁定和问卷发布 |
| 快照批量派生 | 独立题目、正式版本、状态、本人收藏和批次回执 |
| 正式迁移 | 每个定义的来源登记、版本/状态/收藏/usage和questionRefs |

权限预检查提高错误可读性，实际写入仍有资源、状态和预期revision条件。内容版本号和revision在同一管理更新中推进，事务失败一起回滚；无需扫描最大版本号后再插入。

选用会真实更新 `selectionGuard`，归档/下架/撤权在同一控制记录上产生写竞争。guard不当作内容版本，也不长时间锁住用户编辑页面。普通稿更新与发布都写同一题目记录，`hasPublishedUsage=false` 与预期revision一起检查；发布先提交则普通覆盖失败，反向顺序仍不改变已选用的正式快照。

## 历史、删除和迁移

`question_usage` 是从迁移登记基点起可追溯的历史，不是能凭当前问卷重建的纯缓存。累计N按不同surveyId计算；同卷双实例、多版本和重复选用不重复算问卷。维护者只能读受限总数，不读他人问卷标题、身份、时间和答案；普通接收者不能读维护指标。

物理删除正式版本不在本阶段范围。整题归档、版本停止新选用、个人收藏移除分别处理。当前未增加整卷删除接口，不能伪造迁移前已删除问卷的计数。

迁移以 `(surveyId, definitionVersion, instanceId)` 的稳定来源键登记原题，不凭文本归并。旧快照、题序、选项、跳转、业务版本和答案不重编号；只补来源及结构元数据。缺历史定义、所有者或不一致关联时停止并报告。重复执行复用既有关联，旧答卷不重写。

## 三个数据库设计问题

**为什么这样设计。** 填写时需要整份稳定定义，因此继续嵌入题目快照；题目需要独立共享、修订和溯源，因此把管理记录和不可变版本独立保存。增长的答案、授权和使用历史各自独立，避免把无限历史或答卷塞进同一问卷。个人分类保存在bookmark，避免共享题被不同用户互相改标签。冗余的快照、hash、owner与usage有明确校验和事务维护入口。

**为什么不照搬关系表结构。** 题型有不同配置，问卷读取天然以一个有序定义为单位。若为每个选项、校验字段和跳转拆表，填写页面需要多次组装，冻结也必须跨多个记录维护。这里按主要读取单元嵌入内容，但仍在确有独立生命周期的版本、授权和答案上引用，不把“MongoDB没有外键”当作可以放弃关联检查的理由。

**为什么适合MongoDB。** BSON能表达异构题型、选项数组和配置对象；单文档条件更新适合revision并发检查，唯一索引约束身份与幂等，聚合用于频数和计数，副本集事务用于少数跨集合业务边界。MongoDB并不自动提供按ownerId的行级授权或任意规模的低成本聚合，权限由服务端统一过滤，资源上限和课程规模取舍在统计规则中明确。
