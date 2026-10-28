# 第二阶段 API 说明

原注册、登录、问卷、填写、提交和单卷统计接口继续使用。新接口与原页面同源，需登录；写操作使用JSON、正确Origin和 `X-CSRF-Token`。服务端会话决定用户身份，不接受客户端指定ownerId或管理员角色。实例ID仍按不透明字符串处理，路径中仅编码一次。

交互式OpenAPI位于运行应用的 `/docs`。下表以实际路由为准；错误统一为 `{"error":{"code":"...","message":"...","details":[]}}`。

请求字符串（含嵌套通用字段和对象键）须为有效Unicode，孤立代理字符返回422/INVALID_REQUEST。revision与definitionVersion范围为1～9223372036854775807；所有分页page范围为1～92233720368547759，pageSize范围1～100，服务层也校验。此限制防止BSON整数或分页偏移溢出。

## 内容和修订号

题目content示例：

```json
{
  "type": "number",
  "title": "你的年龄是",
  "required": true,
  "options": [],
  "validation": {"minValue": "0", "maxValue": "120", "integerOnly": true}
}
```

支持single、multiple、text、number。选项有稳定id和label；通用版本不包含实例id、题序和jumpRules。四题型约束继续由原领域校验器执行，数字以字符串传入。

管理记录revision、问卷revision和版本状态revision是不同记录的修订号，必须使用对应读取结果。尤其版本可选状态接口使用version DTO中的revision，不使用题目管理revision。

## 题目和正式版本

| 方法和路径 | 请求或查询 | 返回及主要规则 |
| --- | --- | --- |
| GET `/api/library-questions` | scope=mine/shared/public/bookmarks；q最长100字；tag；page；pageSize≤100 | questions、total、page、pageSize；先限定授权，不搜索他人私有稿 |
| POST `/api/library-questions` | content、visibility默认private、requestKey | 201 question；先创建持久编辑稿，正式版本号0；public仅管理员 |
| GET `/api/library-questions/{id}` | 无 | question；非维护者不含workingContent |
| POST `/{id}/working-content` | revision、content | question；未曾发布使用时可保存稿，版本号不变；锁定后409 |
| GET `/{id}/versions` | 无 | versions；维护者可见全部历史，非维护者仅可选正式版本 |
| POST `/{id}/versions` | revision、sourceVersionId、content、requestKey、可选reason | 201 question和version；首次sourceVersionId可为null，后续明确来源 |
| GET `/{id}/versions/{versionId}` | 无 | version；非维护者不能读取已下架版本 |
| POST `/{id}/restore` | revision、versionId、requestKey | 201 question和version；旧内容生成新版 |
| POST `/{id}/derive` | versionId、requestKey、可选content | 201 question；生成本人完整副本，保留来源 |
| POST `/{id}/archive` | revision | question；归档不删除历史 |
| POST `/{id}/versions/{versionId}/availability` | 版本状态revision、selectable | version；改变新选用资格，不改正文 |

表中简写的 `/{id}` 均以 `/api/library-questions` 为前缀。题目DTO包含id、ownerId、authorName、title、type、latestVersionId/Number、latestSelectableVersionId/Number、revision、visibility、status、rootQuestionId、hasPublishedUsage、canManage、bookmarkTags、selectedVersionId、hasUpdate和content。维护者另有workingContent、workingBaseVersionId。最新正式版与最新可选版可能不同。

版本DTO包含id、questionId、versionNumber、content、contentHash、derivedFromVersionId、reason、createdAt、selectable和状态revision。来源ID不自动授予来源内容访问权。

保存版本示例：

```json
{
  "revision": 1,
  "sourceVersionId": null,
  "content": {"type":"text","title":"建议","required":false,"options":[],"validation":{"maxLength":200}},
  "requestKey": "client-generated-unique-operation-key",
  "reason": "建立首版"
}
```

## 共享和个人分类

| 方法和路径 | 参数 | 返回及规则 |
| --- | --- | --- |
| GET `/api/library-questions/{id}/grants` | 无 | grants，只有维护者可查看授权名单 |
| POST `/{id}/grants` | 题目revision、准确username | question、grants；目标须为另一个已注册用户 |
| DELETE `/{id}/grants/{grantId}` | 题目revision | question、grants；撤回不破坏既有问卷 |
| GET `/api/question-bookmarks` | q、tag、page、pageSize | questions、分页及本人tags |
| POST `/api/question-bookmarks` | questionId、可选versionId、tags数组 | question；每题最多20标签，每标签1～50字 |
| DELETE `/api/question-bookmarks/{questionId}` | 空JSON对象 | removed；不删除源题 |
| POST `/api/question-tags` | oldTag、newTag（null表示移除） | modified；只修改本人标签，单次最多500收藏 |
| GET `/api/library-questions/{id}/usage` | scope=version/question/root，可选versionId；version范围必须有versionId | usage对象，见下 |

usage含surveys、scope、visibleQuestionCount、coverage、canSeeOtherCount。surveys只含本人历史使用问卷的id/title/status/responseCount/currentInstances；只有维护者另得otherSurveyCount和deletedOtherSurveyCount，不含他人标识、身份、时间或答案。root范围仅包含当前可见同源题，计数只针对其中有维护权的题目；根关系不赋予派生题权限。累计数按surveyId去重，覆盖起点明确，不能据此统计他人回答。

## 问卷绑定和快照派生

| 方法和路径 | 请求 | 返回及规则 |
| --- | --- | --- |
| POST `/api/surveys/{id}/library-instances` | 问卷revision、versionId、requestKey | 201 survey；新增独立实例及快照，明确版本不跟随latest |
| POST `/api/surveys/{id}/library-instances/save` | revision、instanceId、requestKey | survey；将本人草稿中的本地题登记为正式题并关联 |
| POST `/api/surveys/{id}/library-instances/upgrade` | revision、instanceId、versionId、requestKey | survey；保留实例ID，重新校验规则，仅草稿可用 |
| POST `/api/library-questions/derive-batch` | instances、requestKey | 201 questions与mappings；最多5个本人实例，整体事务 |

批量输入的每个实例为 `{surveyId, definitionVersion, instanceId}`。同源版本和内容相同的快照去重生成一份个人题；mappings给出各实例到新题/版本的对应。它只创建副本，不自动改发布问卷引用。

原整卷PATCH与单题PATCH不能提交自造questionRefs，也不能覆盖已关联快照后继续声明旧版本。删除、排序和发布继续调用原接口并同步来源规则。填写DTO不暴露内部来源与授权元数据，旧提交请求不增加题库字段，旧payloadHash保持语义。

## 跨问卷汇总

GET `/api/library-questions/{id}/statistics?versionId=...&page=1&pageSize=20` 返回statistics。参数page≥1，pageSize为1～100，仅用于数字值频数的分组分页。

主要字段：questionId、versionId、versionNumber、title、type、answerCount、responseCount、surveyCount、average、min、max、distinctValueCount、options、distribution、bySurvey、scope、respondentLabel、page、pageSize。

- scope固定为my-surveys；所有分支共用统计范围，不因公共题或共享权限纳入他人答案。
- options为 `{id,label,count}`；distribution为 `{value,count}` 数字分组，不是原始答卷。
- bySurvey为 `{surveyId,title,answerCount,responseCount,respondentCount}`；人数标签为本卷去重填写账号数，历史缺键时为null。
- 文本只给次数及不同内容数，不返回原文；没有跨卷总去重人数、合并回答明细或导出。
- 无回答时计数0、均值和范围null、分布为空。已有本人快照可在源归档/撤权后继续统计。

## 重要错误和重试

| 错误 | 含义 |
| --- | --- |
| INVALID_REQUEST / INVALID_DEFINITION等422 | 结构、题型配置、ID或分页不合法 |
| NOT_FOUND 404 | 资源不存在或完全不可见，不借错误区分私有资源 |
| FORBIDDEN 403 | 可见但无维护或执行权限 |
| REVISION_CONFLICT 409 | 当前记录已变化，保留输入并重新加载比较 |
| VERSION_REQUIRED 409 | 不能覆盖关联版本内容，或发布引用后普通覆盖稿被禁止 |
| SOURCE_UNAVAILABLE | 归档、下架或共享撤回等导致不能新增选用 |
| IDEMPOTENCY_CONFLICT 409 | 同一操作键被用于不同参数 |
| MIGRATION_INCOMPLETE 409 | 本人已答定义来源不完整，统计不得静默漏算 |
| TRANSACTIONS_REQUIRED 503 | 当前部署不具备题库写事务能力 |
| STATISTICS_TOO_LARGE 503 | 查询条件超过资源上限，不返回截断结果冒充全部 |

创建、版本保存、恢复、派生、选用、升级和批量操作的requestKey作用域包含用户与操作。同键同请求返回原结果，同键不同请求拒绝。请求重试沿用原键和参数；业务冲突不能用自动更换revision或新键掩盖。
