# 第二阶段浏览器脚本复现说明

更新日期：2026年10月28日。浏览器脚本是Python单元/集成测试之外的可选验证工具，应用运行本身不需要Node.js或Playwright。已执行的33场景结果、35张截图与具体方法见[最终浏览器总览](../evidence/stage2/recheck-2026-10-26-363f82/browser/final-summary.json)。本说明补齐现有脚本的依赖、预览数据和调用顺序，本次材料整理没有重新执行浏览器，也不把新准备命令当作新的通过结果。

## 依赖与实际范围

脚本使用CommonJS的require('playwright')。本机整理材料时可用的Playwright包为1.62.1，其声明需要Node.js 20及以上；原10月26日运行报告未分别记录每轮Node/Playwright版本，因此这个包版本不作为对历史环境的反推。可在独立工具目录准备依赖，不混入Python依赖锁：

```sh
npm install --prefix .browser-tools playwright@1.62.1
```

已有Chrome或Chromium时，把BROWSER_EXECUTABLE_PATH设置为其可执行文件绝对路径。脚本默认路径是macOS的/Applications/Google Chrome.app/Contents/MacOS/Google Chrome；其他系统必须明确设置正确路径。下述Node命令通过NODE_PATH定位刚安装的包。完整浏览器重跑需要MongoDB副本集与已经按[运行说明](../../README.md)准备的Python环境；数据库工具另按迁移/恢复说明配置。

## 准备新的独立预览数据库

脚本只接受localhost或127.0.0.1的8001端口。STAGE2_BROWSER_DATABASE只写入报告，不能改变后端连接；必须另外用MONGODB_DB给8001服务设置独立库。下面采用全新虚构演示库复演业务页面，不恢复当前A至E实测数据，也不替代原旧数据迁移证据。

在项目根目录选择从未使用过的新数据库名和证据目录，例如把YOUR_RUN替换为本次唯一标识。数据库名须在MongoDB长度范围内，并与正式survey_project1不同。

```sh
export SURVEY_BROWSER_URI='mongodb://localhost:27018/?replicaSet=survey-rs'
export SURVEY_BROWSER_DB='survey_project1_browser_preview_YOUR_RUN'
export SURVEY_BROWSER_OUT='docs/evidence/stage2/YOUR_NEW_BROWSER_RUN'
MONGODB_URI="$SURVEY_BROWSER_URI" MONGODB_DB="$SURVEY_BROWSER_DB" .venv/bin/python scripts/init_db.py
MONGODB_URI="$SURVEY_BROWSER_URI" MONGODB_DB="$SURVEY_BROWSER_DB" .venv/bin/python scripts/seed_demo.py
MONGODB_URI="$SURVEY_BROWSER_URI" MONGODB_DB="$SURVEY_BROWSER_DB" .venv/bin/python scripts/migrate_stage2.py --database "$SURVEY_BROWSER_DB" --apply --output "$SURVEY_BROWSER_OUT/migration.json"
MONGODB_URI="$SURVEY_BROWSER_URI" MONGODB_DB="$SURVEY_BROWSER_DB" .venv/bin/python scripts/seed_stage2_demo.py --include-admin-demo
MONGODB_URI="$SURVEY_BROWSER_URI" MONGODB_DB="$SURVEY_BROWSER_DB" APP_ORIGIN='http://127.0.0.1:8001' APP_PORT=8001 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

这组准备只针对新的专用演示库，生成虚构demo_owner和公共维护演示账号等脚本夹具。若目标是复现原旧数据保留，应改按[迁移与恢复](migration.md)从对应历史归档建立隔离副本，再执行核对；不能用seed生成的数据声称恢复了原9/8/33。

服务留在一个终端运行，在另一终端重新设置相同SURVEY_BROWSER_DB、SURVEY_BROWSER_OUT和浏览器路径，然后运行下列命令。不要把正式8000服务改为预览服务。

## 按依赖顺序运行四组脚本

先运行核心脚本，它会通过页面创建本轮新账号、题目和问卷，输出本轮用户及资源ID。脚本拒绝覆盖同名已有报告。

```sh
NODE_PATH="$PWD/.browser-tools/node_modules" STAGE2_BROWSER_DATABASE="$SURVEY_BROWSER_DB" STAGE2_BROWSER_OUTPUT="$SURVEY_BROWSER_OUT/core" node scripts/browser_stage2.cjs
```

核心成功后，从它的新报告取得本轮作者用户名。不要让表单脚本默认读取包内旧报告中的历史账号。

```sh
export SURVEY_BROWSER_OWNER=$(node -p "JSON.parse(require('fs').readFileSync(process.argv[1], 'utf8')).fixturePreparation[0].users[0]" "$SURVEY_BROWSER_OUT/core/browser-results.json")
NODE_PATH="$PWD/.browser-tools/node_modules" STAGE2_BROWSER_DATABASE="$SURVEY_BROWSER_DB" STAGE2_FORMS_USER="$SURVEY_BROWSER_OWNER" STAGE2_FORMS_OUTPUT="$SURVEY_BROWSER_OUT/forms" node scripts/browser_stage2_forms.cjs
NODE_PATH="$PWD/.browser-tools/node_modules" STAGE2_BROWSER_DATABASE="$SURVEY_BROWSER_DB" STAGE2_RECHECK_CORE_REPORT="$SURVEY_BROWSER_OUT/core/browser-results.json" STAGE2_RECHECK_OUTPUT="$SURVEY_BROWSER_OUT/supplement" node scripts/browser_stage2_recheck.cjs
NODE_PATH="$PWD/.browser-tools/node_modules" STAGE2_BROWSER_DATABASE="$SURVEY_BROWSER_DB" STAGE2_RACE_USER="$SURVEY_BROWSER_OWNER" STAGE2_RACE_OUTPUT="$SURVEY_BROWSER_OUT/race" STAGE2_RACE_ASSERT_FIXED=1 node scripts/browser_stage2_save_race.cjs
```

BROWSER_EXECUTABLE_PATH如设置，应在运行这些命令的终端export，使四组脚本共同使用。STAGE2_BROWSER_URL默认是http://127.0.0.1:8001，可显式设置，但不能指向8000。脚本夹具的公开虚构密码见各脚本，不使用accept2真实手测账号的自设密码。

## 检查结果与保留证据

分别检查core/browser-results.json、forms/forms-ui.json、supplement/supplement-ui.json和race/save-race-ui.json的status、场景、异常与截图。当前脚本结构对应15+3+11+4个场景单元；补充脚本中一组是两个显式API写权限负例，不计为真实UI。每次实际结果以新报告为准，不能只因进程启动或输出部分PASS就标整轮通过。

race脚本只延迟真实请求，不伪造成功响应；其固定行为还要求真实旧修订保存返回409、保留本地输入并解除表单锁。33场景的原始历史总览有详细错误分类和修复前证据，新运行不能覆盖它。

结束后停止自己启动的8001服务，只清理本次明确创建的隔离库和工具目录，保留本轮结果文件。正式8000及原27017学习库不属于本流程的清理对象。脚本不自动生成含个人配置的数据库归档，最新真实手测数据与历史备份的区别见[数据说明](data.md)。
