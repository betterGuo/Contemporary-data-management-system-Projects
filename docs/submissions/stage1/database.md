# MongoDB 数据库设计

> 第一阶段复核修订文档，stage1-v1.0.1，2026-10-20。修订代码基线65aa339；本轮主环境197项与全新环境197项均通过。原stage1-v1.0/a74cf92、原183项结果和原BSON保留；证据结论仅限实际检查。


## 为什么这样设计

用户、会话、问卷和答卷生命周期及增长规律不同，分别使用 users、sessions、surveys、responses 四个核心集合。schema_migrations 仅存结构迁移元数据。题目、选项和跳转随问卷整体读取和草稿修改，嵌入 surveys；一份提交的各答案整体验证和保存，嵌入一个 responses 文档。答卷随填写人数增长，不嵌入问卷，避免持续扩张单文档。

问卷用 ownerId 引用用户，答卷用 surveyId 和 surveyDefinitionVersion 引用冻结问卷定义。第一阶段不在每份答卷复制整个定义，不存可派生的统计缓存。适量冗余保存题型、实际路径及提交策略用于解释记录并支持后续迁移，须与版本定义一致。

## 为什么不用关系数据库结构

课程禁止关系数据库，但关系数据库能够实现此系统。我们不把用户、每个题型字段、选项、规则条件和答案都按实体拆成大量关联表；问卷的题型和校验字段差异较大，一次读取通常需要完整定义，文档嵌入更贴近该访问方式。若照搬逐字段拆表结构，将增加查询拼装和结构演进成本。

代价是 MongoDB 不提供跨集合外键约束；题目和选项引用、同卷唯一性、所有权和跨字段规则由业务层验证。统计需要数组展开和聚合；发布后编辑需要业务版本管理，不能靠“无固定 schema”跳过迁移。

## 为什么适合 MongoDB

问卷是有界的分层聚合对象，题型有共享字段和不同 validation，可用 BSON 文档表达；答卷是不断增长的独立聚合，适合独立集合追加写。单文档原子更新保证草稿一致替换，唯一及部分唯一索引支持注册、分享标识、幂等和防重复，数组聚合可直接生成统计。适用理由来自查询和修改模式，不是断言关系数据库不能完成。

## 集合及字段契约

下表是最终计划中的设计契约，实际validator/索引与运行已对照app/database.py、baseline-verification.json及恢复manifest。日期为 UTC BSON date，内部引用用 ObjectId，外部 JSON ID 用字符串。

### users

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| _id | ObjectId | 用户主键 |
| username / usernameNormalized | string | 展示名及 NFC/casefold 后唯一名 |
| passwordHash | string | Argon2 密码哈希 |
| createdAt | date | 注册时间 |
| schemaVersion | int | 存储版本，初始1 |

### sessions

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| _id / userId | ObjectId | 会话主键与用户引用 |
| tokenHash / csrfTokenHash | string | 会话及 CSRF 原令牌的摘要 |
| createdAt / expiresAt | date | 创建和截止时间 |

Cookie保存随机原令牌；数据库不保存密码、会话或 CSRF 明文。expiresAt必须在请求时检查，不能依赖 TTL 立即删除。

### surveys

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| _id / ownerId | ObjectId | 主键与所有者 |
| publicId | string | 唯一分享标识，不是管理授权 |
| title / description | string | 标题和说明 |
| allowAnonymous / allowMultipleSubmissions | bool | 匿名及重复设置 |
| status | enum string | draft / published / closed |
| closesAt | date 或 null | 截止，null不设置 |
| questions | array | 稳定 ID 的有序题目、选项、校验及 jumpRules |
| revision | int | 草稿乐观锁 |
| definitionVersion / schemaVersion | int | 业务定义版本 / BSON结构版本，初始1 |
| createdAt / updatedAt | date | 创建修改时间 |
| publishedAt / closedAt | date 或 null | 发布关闭时间 |

### responses

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| _id / surveyId | ObjectId | 答卷标识、问卷引用 |
| surveyDefinitionVersion | int | 作答所依据冻结版本 |
| respondentKey / hmacKeyVersion | string / int | 每问卷稳定 HMAC键及密钥版本 |
| respondentUserId | ObjectId 或 null | 非匿名用户引用；匿名时null |
| isAnonymous | bool | 本次匿名选择 |
| repeatMode | string | 服务端冻结策略 single / multiple |
| submissionKey / payloadHash | string | 幂等键及规范化请求摘要 |
| visitedQuestionIds | array<string> | 服务端重算路径 |
| answers | array | 路径上有效非空答案 |
| admittedAt / submittedAt | date | 最终准入及保存时间 |
| schemaVersion | int | 存储版本 |

答案形态为 questionId、服务端补入的type和value；single为optionId，multiple为不重复optionId数组，text为规范化文本，number为BSON Decimal128。合法空答不存答案，但保留到达路径。未知题、重复题、路径外答案拒绝。匿名作者接口不返回账号、respondentKey、摘要或会话信息。

### schema_migrations

记录迁移唯一版本、执行时间、处理数量及核对信息。不得把无真实业务意义的演示转换写入生产库；扩展演练在隔离库执行。

## 索引契约

| 集合 | 键 | 约束/目的 |
| --- | --- | --- |
| users | usernameNormalized | unique，防并发同名 |
| sessions | tokenHash | unique，定位会话 |
| sessions | expiresAt | TTL，expireAfterSeconds=0 |
| surveys | publicId | unique |
| surveys | ownerId,createdAt降序,_id降序 | 本人列表稳定分页 |
| responses | surveyId,submittedAt,_id | 统计及内容分页 |
| responses | surveyId,respondentKey,submissionKey | unique，同一次请求幂等 |
| responses | surveyId,respondentKey | partial unique，仅repeatMode=single，防并发重复 |

repeatMode、respondentKey由服务端生成。第一阶段冻结重复开关和HMAC密钥；否则历史single/multiple混合或键变化可能绕过防重复。仅“先查再插”不能代替唯一索引。

## 数据库与应用两层校验

MongoDB $jsonSchema限制核心必填字段、BSON类型和状态枚举；业务层检查正下限、上下界关系、题目/选项/规则唯一ID、跨题引用、所有权及生命周期。草稿更新条件同时含_id、ownerId、draft、revision。跨集合读问卷再插答卷不自动获得原子性，关闭并发边界见architecture.md。

## 统计查询

先匹配surveyId和必要的版本，再展开answers。单选按questionId/optionId计份数，并按respondentKey去重计人数；多选再展开value；全部配置选项补零。文本和数字完整内容按submittedAt、_id稳定分页。空答和跳过不作0，数字0计入平均，无数字时返回null。

数字聚合仍计算count和$avg，但最终API平均值不直接使用MongoDB中间结果。真实MongoDB 8.0.32联调发现，两份最大有限Decimal128的$avg可能为Infinity，而[1e40,1,-1e40]可能得到0，分别是中间溢出和抵消丢精度。实际实现exact_numeric_average对该题答案再用MongoDB游标流式读取，以Decimal上下文精度12400+len(str(answer_count))对齐并求和，以覆盖Decimal128支持的指数跨度；最后用34位有效数字进行一次除法，返回十进制字符串，不经二进制浮点、不另存持久计算副本。此实现牺牲一次数字答案扫描换取边界正确性；不把极端值演练当作大规模性能压测。

单选/多选/数字聚合代码在statistics_service.py。极端均值和抵消回归在tests/integration/test_statistics_and_versions.py，本次test-results.json记录通过。

## 演进与备份

实际结构初始化由 app/database.py 的 initialize_database 实现，scripts/init_db.py 调用它；已存在集合用 collMod 更新验证器，缺失集合才创建，索引采用固定名称，001_initial 迁移记录使用 $setOnInsert，不删除已有记录。当前资源常量为每卷100题、每题20选项、文本2000码点、题目标题2000码点、每题100规则，位于 question_types.py；数字输入长度8192、显式指数边界16384位于 storage_adapters.py。它们是公开的资源边界，不是原文规则，不通过未接入的环境变量假装可调。

scripts/migrate.py 默认 dry-run；--apply 运行明确迁移；--example 仅允许 survey_project1_test_ 前缀隔离库。示例为给缺失 displayHint 的问卷添加空字符串，第二次执行应 modified=0，并保留 exercise_optional_display_hint 记录；示例不是第二阶段正式需求。load_definition 在主问卷版本不匹配时尝试 survey_versions 历史来源，不存在即409；第一阶段只正式发布v1，历史来源用于兼容契约和测试，不等于已开放多版本编辑。

schemaVersion、definitionVersion、revision分工不同。第二阶段先保留代码标签、依赖、BSON归档和统计基线；新字段兼容默认读取，迁移须dry-run、可重复、隔离恢复后核对数量和统计；旧答案不凭空补造新必答内容。新增集合允许合理扩展，禁止清库重建。

实际schema与索引见app/database.py及备份manifest，列表explain和各题聚合结果见baseline-verification.json；并发、E03及版本回归见test-results.json，BSON恢复结果见baseline.archive.gz.manifest.json。业务数据库与临时测试库隔离，测试只清理由本次运行生成且命名受保护的库。

## 已取得的真实数据库基准证据

`scripts/verify_stage1.py` 的实际输出保存在 `evidence/stage1/baseline-verification.json`，status=passed。该快照的统计基准为单选A=3/B=1、多选X=2/Y=4/Z=2、数字有效数4、平均值字符串"60"且0参与计算；文本甲乙丙丁全部返回。多次填写样例为2份答卷、1位独立填写者。`single_response_per_user`实际为unique且过滤repeatMode=single。

本人列表的MongoDB 8.0.32 explain实际采用FETCH→IXSCAN，索引owner_recent，键为ownerId升序、createdAt/_id降序，执行成功。扫描/返回数量见该JSON的executionStats；这是该小规模演示数据的一次结果，不能据此宣称大规模性能。索引和聚合代码在app/database.py及statistics_service.py，运行输出与代码可对应。

此基准仅证明列出的检查，不代替并发、分页、迁移、恢复和全部T/E验收。完整测试与恢复manifest已保存，分别核对对应证据。

## 请求成员固定与已恢复的基线

每次统计先查询response IDs，给所有聚合、分页和精确平均传同一个response_filter，确保一个响应的数字与份数使用同一组不可变答卷；这不是MongoDB跨查询事务。ID内存O(n)，筛选BSON超过15MiB返回503/STATISTICS_TOO_LARGE，不截断冒充全部数据。未来规模增大时再评估副本集快照或分批归并。

真实归档artifacts/stage1/baseline.archive.gz已用mongodump生成并mongorestore到全新隔离库；manifest验证users7、surveys6、responses29、schema_migrations1的数量、BSON SHA、索引及验证器完全一致。sessions排除于基线；恢复后重新登录原账号、读取本人列表、health与固定统计均通过，恢复测试库已清理。HMAC密钥只在本机.secrets另存，不进入公开材料。

## 复核中的真实旧数据演练

scripts/audit_stage1_extension.py从保留的原BSON归档恢复到新的survey_project1_test_recheck_库，先核对数量、BSON、索引与验证器，再对同一批6份真实旧问卷演练displayHint默认字段迁移：dry-run处理0、计划6；首次apply改6，第二次apply改0。原用户、29份原答卷BSON、问卷原有核心字段、固定统计均未改变。该脚本随后在同一个恢复库保存v1历史定义、模拟v2新增提交，旧29份答案逐字节不变；演练结束移除隔离库，不访问运行中的项目库。

证据分别为recheck-extension.json与无.git源目录下重跑的recheck-extension-source-package.json。无Git时不声称核验过标签，但始终核对原BSON SHA-256。原归档哈希87a683db98a51be11d0c11de57bb978c78493e9388dab78b6781a9dce12d036f未变。

生产读取另由from_storage_survey实际适配4个已知可选字段缺失，不仅提供未调用的工具函数；适配不回写BSON，显式null仍保留，不将未知业务字段任意补造。该契约与displayHint隔离迁移演练是两种不同证据。
