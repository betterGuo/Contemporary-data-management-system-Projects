# 当代数据管理系统：Project 1（第一阶段）

基于MongoDB的在线问卷系统，支持注册登录、本人问卷管理、四种题型、条件跳转、填写校验、匿名与重复策略、幂等提交和整卷／单题统计。后端为Python 3.12、FastAPI、PyMongo，前端为Jinja2模板和原生JavaScript，无前端构建步骤。

## 四类材料入口

| 材料 | 文件 |
| --- | --- |
| 代码、schema与配置 | [app/](app)、[MongoDB初始化](app/database.py)、[初始化脚本](scripts/init_db.py)、[配置示例](.env.example)、[锁定依赖](requirements.lock) |
| 文档 | [系统说明](docs/architecture.md)、[数据库设计](docs/database.md)、[API说明](docs/api.md)、[关键逻辑](docs/rules.md)、[需求对照](docs/requirements.md)、[AI使用日志](docs/ai-log.md) |
| 测试用例 | [测试步骤与结果](docs/tests.md)、[测试代码](tests)、[人工验收摘要](docs/manual-acceptance.md)、[关键执行证据](docs/evidence/README.md) |
| 实验报告 | [项目完成报告](docs/report.md)；第6节包含AI使用四问，详细过程见[AI使用说明](docs/ai-use.md) |

报告及说明均为Markdown。本分支只保留一份正式文档和必要测试证据；本机配置、数据库快照、历史Git对象、课程原DOCX、设计预览、重复副本、截图及内部整理记录均不提交。

## 运行

仓库默认分支为`main`，第一阶段材料在`P1`。先取得指定分支：

```sh
git clone --branch P1 --single-branch https://github.com/betterGuo/Contemporary-data-management-system-Projects.git
cd Contemporary-data-management-system-Projects
```

需要Python 3.12和MongoDB。默认连接`mongodb://localhost:27017/`，数据库`survey_project1`；可按`.env.example`调整。使用Docker时可先启动独立MongoDB：

```sh
docker run -d --name survey-mongodb -p 127.0.0.1:27017:27017 -v survey-mongodb-data:/data/db mongo:8.0
```

已运行MongoDB时直接使用现有连接。在仓库根目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python scripts/setup.py
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/seed_demo.py
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

也可使用`uv venv --python 3.12 .venv`及`uv pip install --python .venv/bin/python -r requirements.lock`安装依赖。`setup.py`仅在`.env`不存在时生成持久随机密钥；初始化和演示数据脚本可重复执行，不清空数据库。`.env`不进入Git。

若macOS上的Python安装缺少CA证书，pip可能报`CERTIFICATE_VERIFY_FAILED`。可完成该Python安装器的证书配置，或使用上述uv安装方式；本次新环境验证已通过uv方式完成。

打开[首页](http://127.0.0.1:8000)、[API文档](http://127.0.0.1:8000/docs)或[健康检查](http://127.0.0.1:8000/health)。

## 演示

演示账号`demo_owner`负责创建、编辑和查看统计，`demo_student`负责填写，公共演示密码均为`Survey2026!`。这些账号和样本均为虚构数据，由种子脚本重新生成，无须原开发数据库。

1. 登录后创建草稿，添加单选、多选、文本、数字题，设置约束、跳转和需要的截止时间。
2. 保存和预览后发布，复制分享链接；填写者须登录。
3. 填写并提交，作者进入统计页查看结果，可关闭问卷。发布后定义和截止时间冻结，需在发布前检查。

种子问卷覆盖统计基准、三类跳转、匿名防重复及同人多次填写。统计基准四份答卷的预期为单选A=3/B=1，多选X=2/Y=4/Z=2，数字平均60（含0），文本甲乙丙丁。新增答卷后应按真实数据核算，不能继续套用四份样本预期。

## 测试

```sh
.venv/bin/python -m pytest tests -q
```

测试使用真实MongoDB，只创建、清理随机命名的`survey_project1_test_`隔离库。2026-10-22完整测试记录为**200项通过、0失败、0跳过**，其中新增3项初始化安全测试；[逐项结果](docs/evidence/stage1/final-review-2026-10-22/test-results.json)和[原始输出](docs/evidence/stage1/final-review-2026-10-22/pytest-output.txt)可核对。人工反馈的平均年龄19与当次读回110仍单独标注待核实。

直接运行pytest时，测试连接由环境变量`TEST_MONGODB_URI`指定，未设置时使用`mongodb://localhost:27017/`，不会读取`.env`中的`MONGODB_URI`。若应用使用其他地址或端口，运行测试时也应显式指定对应地址，例如：

```sh
TEST_MONGODB_URI='mongodb://localhost:27018/' .venv/bin/python -m pytest tests -q
```

可选的新环境复现需已安装`uv`并先完成`setup.py`，输出另存到本机：

```sh
.venv/bin/python scripts/reproduce_stage1.py --output artifacts/private/reproduction-new.json
```

该脚本新建临时Python环境和数据库，安装锁定依赖并验证种子、API与完整测试，结束后清理自己的临时资源。其测试默认沿用应用实际配置的`MONGODB_URI`（包括`.env`），也接受显式的`TEST_MONGODB_URI`覆盖。[最新复现记录](docs/evidence/stage1/reproduction.json)为10月22日从远端P1新克隆后验证的结果：Python 3.12.6、MongoDB 8.0.34、全新环境200项通过，并完成真实HTTP和浏览器检查。10月20日197项的历史版本保留在此前P1提交中。`run_tests.py`会写固定证据路径；复测时优先直接使用pytest，保留已提交的历史记录。

## 第二阶段衔接

题型、答案校验和统计处理器按模块注册；跳转运算符可扩展。发布定义以版本读取，题目和选项有稳定ID，草稿编辑通过revision检测冲突；`schemaVersion`与迁移入口用于数据结构演进。新增题型仍需补齐编辑、填写和统计处理器，不能只注册名称。

第一阶段冻结发布内容、只允许向后续题或结束跳转；第二阶段按正式变更在现有代码及旧数据上修改。历史备份、身份密钥和原开发标签留在本机，不上传公开仓库；本分支以远端原有历史为基础发布当前代码。完整限制和兼容性说明见[报告](docs/report.md)及[数据库设计](docs/database.md)。
