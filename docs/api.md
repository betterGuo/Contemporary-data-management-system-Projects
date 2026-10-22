# API 契约

> 第一阶段正式文档。2026-10-22完整测试为200项通过、0失败、0跳过；复测方法、历史结果及证据范围见[测试说明](tests.md)和[关键验证证据](evidence/README.md)。

本文已静态对照 app/api/*.py、app/schemas/requests.py、app/main.py、response_service.py 和 statistics_service.py；具体请求运行结果已在tests.md与test-results.json对照。交互文档入口 /docs，机器接口描述 /openapi.json。JSON中ObjectId用字符串、日期用带时区ISO8601、数字答案用十进制字符串。

## 通用约束和错误

API写请求要求 Content-Type: application/json、Origin 与服务端请求来源一致。注册/登录不要求已有会话；其他写请求还要求 survey_session Cookie和X-CSRF-Token。GET只校验会话及相应所有权。登录设置survey_session（HttpOnly）和csrf_token（同源JS可读），路径均为/；前端跨页或刷新后从Cookie读取CSRF原令牌，不能从数据库摘要恢复。退出同时清除两个Cookie。

请求模型拒绝额外字段，禁止传ownerId、respondentKey、repeatMode等内部数据。分页page从1开始，pageSize为1–100，默认20。

```json
{
  "error": {
    "code": "INVALID_ANSWER",
    "message": "请检查题目输入。",
    "details": [{"questionId":"q1","field":"value","message":"此处为具体错误"}]
  }
}
```

| 状态 | 含义 |
| --- | --- |
| 200 / 201 | 查询/更新/幂等重取成功；新建成功 |
| 401 | 未登录、错误凭证、会话失效 |
| 403 | Origin或CSRF校验失败 |
| 404 | 资源不存在、非所有者访问管理、草稿分享 |
| 409 | revision/状态/版本/重复填写/同键不同内容冲突 |
| 410 | 关闭或到期的新提交 |
| 413 / 415 | 请求过大 / 写请求非JSON |
| 422 | 请求、定义、答案或ID格式校验失败 |
| 503 | 数据库不可用，不能假报提交成功 |

## 路由清单

| 方法 | 路径 | 请求及权限 | 成功结果 |
| --- | --- | --- | --- |
| POST | /api/auth/register | username,password；未登录；Origin | 201，user安全投影 |
| POST | /api/auth/login | username,password；Origin | 200，user及两个Cookie |
| GET | /api/auth/me | 登录 | user，不返回CSRF原令牌或摘要 |
| POST | /api/auth/logout | 登录及CSRF；JSON空对象 | ok:true，清除Cookie |
| POST | /api/surveys | 登录及CSRF；创建设置 | 201，survey |
| GET | /api/surveys | 登录；page/pageSize | surveys,total,page,pageSize，仅本人 |
| GET | /api/surveys/{surveyId} | 所有者 | survey |
| PATCH | /api/surveys/{surveyId} | 所有者草稿；revision及变化字段 | survey，revision递增 |
| POST | /api/surveys/{surveyId}/questions | 所有者草稿；revision,question | 201，更新后survey |
| PATCH | /api/surveys/{surveyId}/questions/{questionId} | 所有者草稿；revision,question | survey，ID保持稳定 |
| DELETE | /api/surveys/{surveyId}/questions/{questionId} | 所有者草稿；JSON含revision | survey，检查规则引用 |
| PUT | /api/surveys/{surveyId}/question-order | 所有者草稿；revision,questionIds | survey，完整不重复ID列表 |
| POST | /api/surveys/{surveyId}/publish | 所有者草稿；revision | survey，发布并冻结 |
| POST | /api/surveys/{surveyId}/close | 所有者；JSON空对象 | survey，已关闭时可重复关闭 |
| GET | /api/surveys/{surveyId}/preview | 所有者 | survey,isPreview:true；不创建答卷 |
| GET | /api/participation/{publicId} | 登录；问卷允许新提交 | 必要定义survey，含definitionVersion |
| POST | /api/participation/{publicId}/responses | 登录及CSRF；Submission | 201新答卷或200原回执 |
| GET | /api/surveys/{surveyId}/statistics | 所有者；page/pageSize | statistics，整卷和各题 |
| GET | /api/surveys/{surveyId}/questions/{questionId}/statistics | 所有者；page/pageSize | statistics，单题及内容分页 |
| GET | /health | 连通检查 | status,database,version，无凭据 |

## 注册、创建及草稿更新

Credentials为字符串username/password；用户名3–32码点，密码8–128字符。用户名去两端空白、NFC、casefold后唯一；密码内容不自动去空白。

```json
{"title":"课程反馈","description":"用于演示","allowAnonymous":true,"allowMultipleSubmissions":false,"closesAt":null}
```

创建不接受questions，先创建草稿，再调用题目接口或主PATCH。主PATCH支持revision与title、description、allowAnonymous、allowMultipleSubmissions、closesAt、questions；缺省字段不修改，closesAt:null清除截止。非空截止必须含时区，如2026-10-30T18:00:00+08:00；发布时必须在未来。

```json
{
  "revision":1,
  "question":{
    "type":"multiple","title":"喜欢哪些内容","required":false,
    "options":[{"id":"x","label":"理论"},{"id":"y","label":"实验"}],
    "validation":{"minSelections":2,"maxSelections":2},
    "jumpRules":[]
  }
}
```

单题接口外层是revision和question，不能把题目字段直接放外层。可省略新题/选项/规则的id，由服务端生成；编辑不得改变现有题目id。选项或规则的稳定id应在后续保存中原样保留。重排请求为{"revision":2,"questionIds":["q2","q1"]}，须包含全部题且不重复，重排后规则仍须合法。

multiple的validation含minSelections/maxSelections，text含minLength/maxLength，number含minValue/maxValue/integerOnly；限制可单独设置。数字边界和规则阈值使用字符串，between的value为两个字符串数组。

## 提交契约、版本和幂等

```json
{
  "definitionVersion":1,
  "submissionKey":"一次新填写生成的UUID",
  "isAnonymous":true,
  "answers":[
    {"questionId":"单选题ID","value":"选项ID"},
    {"questionId":"多选题ID","value":["x","y"]},
    {"questionId":"数字题ID","value":"18.0"},
    {"questionId":"文本题ID","value":"反馈内容"}
  ]
}
```

submissionKey实际接口接受1–128字符，浏览器约定为每次新填写生成UUID；请求重试保留原key。answers只包含questionId和value，不能传type或客户端path。不能提交未知题、重复题、重复选项或路径外答案，包括路径外显式空答。required=false不覆盖正数量/字数下限。

GET返回definitionVersion，POST必须携带，缺版本422，不存在409，不自动改最新版。服务端摘要包含版本、匿名选择、规范化答案，忽略答案排序、多选顺序和等价数字表达的差异。先按历史定义验证真实路径和答案形状（含路径外显式空答），再重取成功回执，最后检查新请求准入；关闭、到期或版本停止接收不应把历史成功回执改成失败。

```json
{"response":{"id":"答卷ObjectId字符串","submittedAt":"UTC ISO8601","definitionVersion":1},"replayed":false}
```

新答卷201/replayed=false；同key同规范化内容200/replayed=true，返回相同答卷id；同key不同答案或匿名选择409。允许重复时新key代表新答卷；不允许重复时同用户同卷由部分唯一索引最多保存一份。

## 统计返回字段与口径

整卷statistics含surveyId、title、definitionVersion、submissionCount、respondentCount、questions。单题含questionId、title、type、answerCount、respondentCount、unansweredCount、totalValues、page、pageSize、average和values；选择题另有options，每项id/label/count/respondentCount。

count为份数或被选择次数，respondentCount为HMAC键去重人数；同人多次选择不同选项可能分别计入不同选项人数。text/number的values含responseId、value、submittedAt，按稳定顺序分页，所有页覆盖全部内容。number average为十进制字符串或null，空答和跳过不作0，数字0正常计入。实际平均由流式高精度Decimal求和、最终34位有效数字除法产生，以避免MongoDB $avg的中间溢出与抵消误差。作者不能取得账号、内部去标识键或任何凭据。

## 页面入口

/register、/login、/dashboard、/surveys/{id}/edit、/surveys/{id}/preview、/surveys/{id}/statistics、/survey/{publicId}。未登录网页跳转登录并保留站内next路径；API返回401。预览和真实填写共用模板但预览不得产生正式答卷。

## 复核补充：日期、旧字段与题ID

closesAt带时区但UTC转换超出Python日期范围时，创建与修改均返回422/INVALID_DEADLINE，不创建半份问卷或部分改标题。读取旧文档缺少description、allowAnonymous、allowMultipleSubmissions、closesAt时，仅在响应和业务视图补默认值，读取不自动执行数据库迁移。

题目编辑、删除、单题统计实际路由使用{question_id:path}保留斜线ID。请求路径中的题IDencodeURIComponent一次；不要手动再次解码literal%2F等内容。普通Unicode、斜线、百分号和all均合法；END、.、..及Unicode Cc/Cs字符题ID在定义校验时拒绝422，错误详情不回显非法代理字符。前端整卷范围哨兵为空串，不与合法all题ID冲突。

单题内容翻页会同步替换本题完整统计卡；整卷摘要只在整卷刷新后更新，页面分别说明更新时间，不能把不同时间的查询宣称为全局事务快照。
