# 问卷工坊 第二阶段

MongoDB课程问卷系统，版本2.0.0。第二阶段在原系统上增加题目独立保存、持久编辑稿、不可变版本、共享、个人标签题库、来源与使用查询，以及精确版本的跨问卷汇总。原账号、问卷、答案、跳转、校验和单卷统计继续保留。

本次提交使用远端仓库[Contemporary-data-management-system-Projects](https://github.com/betterGuo/Contemporary-data-management-system-Projects)的[第二阶段分支`P1-stage2`](https://github.com/betterGuo/Contemporary-data-management-system-Projects/tree/P1-stage2)；第一阶段保留在[P1分支](https://github.com/betterGuo/Contemporary-data-management-system-Projects/tree/P1)。源码、配置示例、报告、测试和证据按仓库原目录提交，不需要下载或生成压缩包。

本机入口：[问卷工坊](http://127.0.0.1:8000) · [题目库](http://127.0.0.1:8000/library) · [API文档](http://127.0.0.1:8000/docs)。需要服务启动后访问。

最新[功能复查](docs/stage2/recheck-2026-10-26.md)：309项自动测试与33个浏览器联调场景通过。10月26日至28日又完成固定样例的[真实操作补测](docs/stage2/manual-acceptance.md)，区分用户亲测、AI页面操作和业务服务测试；原始业务数据和统计与开始前基线一致。初次全新环境260项、后续309项复查和本轮固定样例是不同批次，详见[测试结果](docs/stage2/tests.md)。

## 新环境启动

使用Python3.12、Docker Desktop及MongoDB。业务写入需要真实副本集；原27017学习实例保留，项目独立使用27018。

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.lock
.venv/bin/python scripts/setup.py
docker compose -f deploy/stage2.compose.yaml up -d
.venv/bin/python scripts/init_replica_set.py
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/seed_stage2_demo.py --include-admin-demo
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

这一入口用于新的空环境。`setup.py`只在缺少配置时生成随机持久密钥，不覆盖已有`.env`；新配置使用`mongodb://localhost:27018/?replicaSet=survey-rs`和`survey_project1`。种子脚本创建虚构演示数据，不还原本地历史测试账号、固定ID或15/15/42的总数。已有第一阶段数据时，使用下方“旧数据延续与迁移”入口，保留原身份密钥，不能清库或用seed代替迁移。

Docker配置采用项目专用持久卷，容器内外均使用27018；副本集成员地址为`localhost:27018`，供本机运行的Python应用使用。不要把这个地址照搬到另一Docker容器或远程服务器。单节点副本集支持本机事务演示，不宣称生产高可用。

`/health`返回版本与`transactionsAvailable`。正式版本保存、复用、发布及迁移均使用事务；连接standalone会明确拒绝，不退化为多次无事务写入。

## 演示账号和数据

新环境执行上述种子命令后，可使用下面三个专用虚构账号，演示密码为`Survey2026!`。延续本地旧库时，旧`demo_owner`、`demo_student`及原账号仍保持；这些旧账号不由第二阶段新库种子自动创建。

| 账号 | 用途 |
| --- | --- |
| stage2_owner | 管理两份复用问卷、共享私有题、查看跨卷汇总 |
| stage2_peer | 查看共享题、选用或派生，不能修改原题 |
| stage2_admin | 维护公共题、版本与可选状态；不能因此查看其他人的答案 |

`stage2_owner`的两份“第二阶段示例”问卷复用同一个公共年龄题v1和同一个私有选择题v1。三份虚构答案的年龄为0、20、40，跨卷均值20；选择题“愿意”2次、“暂不参加”1次。匿名人数只按每份问卷的填写账号去重，不显示跨卷总人数。

仅需补充虚构演示时可单独执行下面的显式命令；它不会替换旧账号或旧答案，重复执行不增加相同样本：

```sh
.venv/bin/python scripts/seed_stage2_demo.py --include-admin-demo
```

这个参数只为专用的新虚构`stage2_admin`授予公共维护权，不升级普通旧账号。其他管理员通过本地受控命令指定已有用户名，并保存审计记录：

```sh
.venv/bin/python scripts/manage_admin.py --username YOUR_USERNAME
```

## 数据状态和样例范围

| 节点 | 用户 | 问卷 | 答卷 | 含义 |
| --- | ---: | ---: | ---: | --- |
| 第一阶段原始业务数据 | 9 | 8 | 33 | 第二阶段扩展前保留的原数据 |
| 10月26日迁移与虚构演示完成后 | 12 | 10 | 36 | 已有第二阶段归档对应的历史节点 |
| 10月28日固定样例补测完成后 | 15 | 15 | 42 | 本地新增三个测试账号、A至E五份问卷和六份正式答卷后的状态 |

上述数量描述本地已执行节点，不是新库初始化的验收常量。新环境种子用于复现题目复用与年龄0/20/40的均值20；A至E、共享撤回、副本及双页冲突的实际输入、回执、截图和指纹保留在测试证据中。旧归档没有自动包含后续样例，详见[数据说明](docs/stage2/data.md)和[参考与归档说明](docs/submissions/stage2/REFERENCE_NOTES.md)。

## 使用方式

1. 在“题目库”创建四种题型之一，保存编辑稿。编辑稿仅维护者可见。
2. 显式保存为正式版本后，在自己的草稿问卷中选用；问卷记录精确版本与完整快照。
3. 同题可多次加入同卷，每次有独立实例ID，答案及跳转分别定位。
4. 任何发布问卷使用过该题后，普通编辑稿保存关闭，内容变更须保存为新版本。
5. 新版本不自动替换问卷。草稿可以显式升级，跳转不兼容时整次操作拒绝；已发布问卷不能替换。
6. 共享到准确用户名，接收者可选用或派生。撤回后原问卷快照和自己的独立副本继续保留，不能再读取源历史。
7. 使用个人收藏与标签整理；公共题库是公开题目的视图，不支持整题库授权。
8. 查看版本历史、直接来源和本人使用问卷；维护者另可见其他问卷的受限累计数，不含标题、身份和时间。
9. 跨卷汇总选择精确版本，只统计本人问卷；不同版本、同源变体及独立同名题分别统计。

跨卷只给汇总、分布和逐卷指标，不提供合并答卷明细或导出。原单卷查看文本与数字填写内容的功能保留。归档题目或停止某版新选用不删除版本正文，也不影响已选用快照。

## 测试与恢复

```sh
TEST_MONGODB_URI='mongodb://localhost:27018/?replicaSet=survey-rs' .venv/bin/python scripts/run_tests.py --output-dir docs/evidence/stage2/YOUR_NEW_RUN
.venv/bin/python scripts/backup_project.py --output artifacts/stage2/YOUR_NEW_BACKUP.archive.gz
MONGODB_URI='mongodb://localhost:27018/?replicaSet=survey-rs' TEST_MONGODB_URI='mongodb://localhost:27018/?replicaSet=survey-rs' .venv/bin/python scripts/reproduce_stage1.py --output docs/evidence/stage2/YOUR_NEW_REPRODUCTION/reproduction.json
```

运行器为每轮保存原始输出、JUnit与逐项结果，拒绝覆盖已有证据。测试使用随机`survey_project1_test_`库并清理自己创建的库；需要`mongodump`与`mongorestore`完成备份保护专项。`reproduce_stage1.py`沿用旧文件名，但运行当前锁定依赖和当前完整测试集，必须指定新的第二阶段输出路径。

上面的测试命令是可重新执行的入口，不代表本次提交整理重新运行了309项。可选浏览器脚本需要Node.js、Playwright和独立8001预览服务，依赖、执行顺序及隔离限制见[测试说明](docs/stage2/tests.md)。Python应用本身不依赖Node.js。

备份动态覆盖全部业务集合，排除可重新登录生成的sessions，核对BSON、索引、验证器和实际统计。旧布局备份不在恢复验证时暗中升级schema，第二阶段布局另做恢复库应用冒烟。原HMAC密钥必须私密保留，不能提交到Git或公开材料。

## 旧数据延续与迁移

只有持有第一阶段原库及其私密配置时才使用本入口。本机原27017库保留，27018正式库由停写后的最终备份恢复；旧8份问卷25个实例补充了来源关联，原9个账号和33份答卷保持。第二阶段虚构演示及后续真实测试另外增加，不覆盖原数据。公开仓库不提供原始BSON、原HMAC密钥或会话，保留恢复清单、指纹与统计证据。

迁移默认dry-run，显式apply才修改目标库，报告路径不可覆盖：

```sh
.venv/bin/python scripts/migrate_stage2.py --database survey_project1 --output docs/evidence/stage2/YOUR_NEW_MIGRATION/dry-run.json
.venv/bin/python scripts/migrate_stage2.py --database survey_project1 --apply --output docs/evidence/stage2/YOUR_NEW_MIGRATION/apply.json
.venv/bin/python scripts/verify_stage2_upgrade.py --output docs/evidence/stage2/YOUR_NEW_MIGRATION/preservation.json
```

最后一条默认对照本机原27017库和新27018库，其他机器需显式指定源/目标URI和库名。迁移只补引用、结构版本和独立题目记录，不修改旧答案、题目实例ID、选项ID、规则或提交摘要。同名旧题不自动合并。正式升级、失败续跑和切换限制见[迁移说明](docs/stage2/migration.md)。

## 材料

- [第二阶段材料索引](docs/submissions/stage2/README.md)
- [第二阶段完整实验报告（Markdown，当前提交版）](第二阶段完整实验报告.md)
- [测试用例与结果PDF](output/stage2/第二阶段测试用例与结果.pdf)、[可编辑DOCX](output/stage2/第二阶段测试用例与结果.docx)
- [第二阶段入口与进度](docs/stage2/README.md)
- [完整执行计划](第二阶段执行计划.md)
- [需求对照](docs/stage2/requirements.md)、[设计决策](docs/stage2/decisions.md)
- [系统设计](docs/stage2/architecture.md)、[MongoDB设计](docs/stage2/database.md)、[API](docs/stage2/api.md)、[关键规则](docs/stage2/rules.md)
- [测试记录](docs/stage2/tests.md)、[逐场景验收](docs/stage2/acceptance.md)、[数据说明](docs/stage2/data.md)
- [完成报告源文档](docs/stage2/report.md)、[演示步骤](docs/stage2/demo.md)、[AI使用说明](docs/stage2/ai-use.md)、[真实AI日志](docs/stage2/ai-log.md)
- [第一阶段原提交材料](docs/submissions/stage1/README.md)

第一阶段材料、教师原始要求和本地旧归档继续保留。第二阶段分支按原目录提供可运行源码、配置示例、技术文档、完整Markdown报告、既有导出文档及测试证据；本地旧BSON归档及真实配置不推送到远端。

## Git提交与材料核对

以本仓库的第二阶段分支`P1-stage2`作为本次提交入口。当前报告使用[完整Markdown版本](第二阶段完整实验报告.md)，包含九项正文、学生设计讨论与数据附录；报告先前的Word/PDF导出版保留在`output/stage2/`供参考，测试材料维持原有版本。材料逐项位置见[第二阶段材料索引](docs/submissions/stage2/README.md)。查看或克隆该分支后，直接按上面的新环境步骤运行，无需解压ZIP。

推送范围包括源码、脚本、测试、部署配置、依赖锁、教师要求、第二阶段计划、技术说明、报告和真实证据。私密`.env`、密钥、会话、原始BSON归档、`tmp/`、`dist/`、虚拟环境、缓存及文档渲染预览图不随分支提交。历史恢复清单仍公开，用于说明原数据迁移与保护结果。

先前ZIP整理、解压冒烟和完整性审计的记录作为已执行历史保留，不能误称为本轮新执行测试。当前提交以Git分支中的原生文件为准；历史日志中的宿主路径只作执行背景，不是克隆后运行依赖。
