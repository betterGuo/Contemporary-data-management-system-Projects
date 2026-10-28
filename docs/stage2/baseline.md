# M1 当前代码与数据基线

执行日期：2026年10月26日。运行标识：`m1-2026-10-26-f628973f`。

M1核对并保护第一阶段实际提交后的工作目录和数据库，供第二阶段增量扩展使用。没有重置到旧标签，没有改写业务代码，没有重新生成身份密钥，没有创建第二阶段业务集合或执行来源迁移。

## 当前代码和环境

- Git HEAD 为 `176fd5b7a8eca826bf8433e13d79dec52ab15b62`；现有未提交的第一阶段整理材料和初始化测试一并保留，不能用该提交号替代当前目录。
- 启动时发现 Docker Desktop 未运行，本轮启动原有 Docker 环境；既有 `mongodb-study` 容器随之恢复并健康，不重建持久卷。
- Python 为现有 `.venv` 中的3.12；MongoDB当前为 standalone。本轮不重复安装依赖或声称已验证全新环境。
- 建立162个非私密基线文件的清单和本地恢复副本。副本位于被 Git 忽略的 `artifacts/private/stage2/m1-2026-10-26-f628973f/`，同时私密保留原配置，文件权限为600。该副本不是提交包。

文件起点见[文件清单](../evidence/stage2/m1-2026-10-26-f628973f/files-before.json)，恢复副本核对见[快照记录](../evidence/stage2/m1-2026-10-26-f628973f/code-snapshot.json)。最终本轮文件改动范围见同目录 `files-after.json`。

## 实际数据

源库：`survey_project1`。

| 集合 | 文档数 |
| --- | --- |
| users | 9 |
| surveys | 8 |
| responses | 33 |
| schema_migrations | 1 |

sessions属于可重新登录生成且会正常TTL过期的数据，不纳入业务指纹和本次BSON归档。上述数字来自本轮真实盘点，没有沿用早期7用户、6问卷、29答卷的记录。

源库只读盘点全部业务集合、BSON指纹、索引和验证器，并计算8份现有问卷的实际统计。验证前后这些数据与统计均一致，原 `.env` 与私密副本逐字节一致。

## 备份和恢复验证

实际归档为 `artifacts/stage2/m1-2026-10-26-f628973f.archive.gz`，SHA-256：

```text
63b4009f6ce9515970230b3f8f325744ee7e8a556c804a3b0934cd8129c60a05
```

备份恢复到本次随机生成的独立临时库，依次核对：

1. 全部业务集合的文档数、BSON、索引与校验器。
2. 全部8份当前问卷的实际统计摘要及结果指纹；不要求演示问卷永远保持固定样本数。
3. 恢复库应用启动、健康、原demo_owner账号登录及本人问卷列表。
4. 启动后业务数据与元数据保持一致；会话变化不进入业务指纹。
5. 清理本次临时恢复库，结束时没有残留 `survey_project1_test_` 测试库。

实际恢复报告见[备份清单](../../artifacts/stage2/m1-2026-10-26-f628973f.archive.gz.manifest.json)，前后总核对见[verification.json](../evidence/stage2/m1-2026-10-26-f628973f/verification.json)。统计快照保存摘要和结果指纹，不导出答卷原始文本。

## 本轮工具改动

| 文件 | 改动与原因 |
| --- | --- |
| `scripts/run_tests.py` | 增加 `--output-dir`、唯一默认目录、拒绝覆盖及运行占位、保存原始输出与收集错误；按测试节点汇总，避免忽略setup/teardown失败 |
| `scripts/backup_project.py` | 动态核验所有业务集合，比较源/恢复实际统计；检查源数据前后稳定，保留失败报告；初始化和登录仅发生在恢复库 |
| `tests/conftest.py` | app settings显式读取 `TEST_MONGODB_URI`，保证备份和fixture数据库处于同一实例，供M2独立环境使用 |
| `tests/integration/test_baseline_tools.py` | 新增4项保护测试，覆盖扩展集合及非固定样本、恢复目标碰撞、源库变化和历史结果防覆盖 |

`reproduce_stage1.py` 已支持 `--output`，本轮未修改也未运行；以后使用时必须指定新的第二阶段路径，不能使用其stage1默认输出覆盖历史结果。

## 实际测试结果

| 运行 | 结果 | 说明 |
| --- | --- | --- |
| 原有回归 | 200通过、0失败、0跳过 | 改工具后、增加专项用例前，验证原代码基线 |
| 工具专项首轮 | 3通过、1失败 | 新测试误替换全局uuid函数，影响PyMongo会话；真实失败记录保留 |
| 工具专项复测 | 4通过、0失败、0跳过 | 改为只替换备份模块局部依赖后通过 |
| 最终全量 | 204通过、0失败、0跳过 | 原200项与新增4项；运行器总时长14.25秒，pytest输出13.96秒 |

各次运行都写入独立目录：

- [原200项](../evidence/stage2/m1-2026-10-26-f628973f/regression/test-results.json)
- [专项首轮真实失败](../evidence/stage2/m1-2026-10-26-f628973f/tooling-check/test-results.json)
- [专项复测](../evidence/stage2/m1-2026-10-26-f628973f/tooling-check-r2/test-results.json)
- [最终204项](../evidence/stage2/m1-2026-10-26-f628973f/final-regression/test-results.json)

有1条既有Starlette/httpx测试客户端弃用警告，没有因此升级依赖。T80～T84本来由新环境、材料、恢复和浏览器等独立证据处理，本轮不伪造pytest覆盖；M1真实恢复也不替代整阶段浏览器验收。第二阶段76个业务场景仍待实现和逐项验收。

本轮命令使用显式新路径；以下路径已存在，再运行必须换新的运行标识：

```sh
.venv/bin/python scripts/run_tests.py --output-dir docs/evidence/stage2/m1-2026-10-26-f628973f/regression
.venv/bin/python scripts/backup_project.py --output artifacts/stage2/m1-2026-10-26-f628973f.archive.gz
.venv/bin/python scripts/run_tests.py --output-dir docs/evidence/stage2/m1-2026-10-26-f628973f/tooling-check -k baseline_tools
.venv/bin/python scripts/run_tests.py --output-dir docs/evidence/stage2/m1-2026-10-26-f628973f/tooling-check-r2 -k baseline_tools
.venv/bin/python scripts/run_tests.py --output-dir docs/evidence/stage2/m1-2026-10-26-f628973f/final-regression
```

M1已完成，下一步为M2数据结构与事务环境。第一阶段正式库保持原结构和原业务数据。
