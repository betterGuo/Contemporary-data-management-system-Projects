# 第二阶段逐场景验收对照

更新日期：2026年10月28日。

本表对应[执行计划](../../第二阶段执行计划.md)中的76个S2场景。判定依据是实际测试结果、真实浏览器操作和迁移核对记录；`@pytest.mark.case`只是索引，不自动代表场景全部通过。一个测试节点可以覆盖多个子项，也可能只覆盖某场景的一部分。

“已验证”表示本行所列核心行为有运行证据；“部分验证”说明尚未单独造出的细分组合或交互，不等同于该核心功能未实现或测试失败。静态审查只能说明代码结构，不代替故障、并发或权限运行证据。本表已据初次260项交付及本轮309项功能复查更新，不将计划的76行误称为76项均已独立自动化。

## 证据来源

- **P**：[初次交付全量结果](../evidence/stage2/final-2026-10-26/regression/test-results.json)，260通过、0失败、0跳过。本段所指初次交付自动节点均在该260项结果中通过；后补Q节点以309项结果为准。三份初次交付测试源码最后修改时间均早于该次运行开始，迁移旧key重放也在该次实际执行范围内。早期联调失败仍保留，不能当成最终失败，也不删除其历史记录。
- **UI**：[真实浏览器最终记录](../evidence/stage2/browser-2026-10-26/attempt-4/browser-results.json)，15项实际UI流程、16张截图，JavaScript执行异常0、非预期控制台错误0；401会话探测和撤权后404单列。API只读核对UI结果，不替代UI写入。
- **MIG**：[正式迁移](../evidence/stage2/development-2026-10-26/final-migration-apply.json)、[重复迁移](../evidence/stage2/development-2026-10-26/final-migration-repeat.json)及[旧数据保留](../evidence/stage2/development-2026-10-26/final-legacy-preservation.json)：8份原问卷、25实例登记；重复执行新增0，9用户与33答卷BSON保留，8份原统计核对一致。
- **CLEAN**：[新环境复现](../evidence/stage2/final-2026-10-26/clean-environment/reproduction.json)：新建Python3.12.6环境、锁定依赖校验、初始化、种子幂等、登录和页面/统计入口核验、全套260项通过，临时库与虚拟环境清理。
- **DEMO**：[正式数据与演示核对](../evidence/stage2/final-2026-10-26/data-and-demo.json)：原9用户/8问卷/33答卷保留，新增虚构示例；A卷两份0/20、B卷一份40，跨卷均值20，身份密钥和原库保留。
- **USCOPE**：[使用范围UI小检查](../evidence/stage2/browser-2026-10-26/usage-scope-ui.json)：预览端实际选择question/root/version，三个GET均200，DOM选定值准确，JavaScript异常0；只读查询，不改问卷和答卷。
- **FORMS**：[三题型真实表单补测](../evidence/stage2/browser-2026-10-26/forms-ui.json)：单选、多选、文本均实际创建编辑稿及正式v1；单/多选修改文字并普通保存后仍为0版，选项ID在草稿/版本之间不变，多选上下限1/2、文本字数2/100正确，JavaScript异常0。与UI2/3的数字题合计覆盖四种实际题库表单。
- **BACKUP**：[第二阶段最终备份恢复](../../artifacts/stage2/stage2-v2.0.0.archive.gz.manifest.json)：12个业务集合完整BSON、索引和验证器恢复一致，10份定义统计一致，恢复库应用启动/原账号登录/问卷列表通过，临时恢复库清理，源业务指纹不变。
- **LIVE**：[最终实际服务核对](../evidence/stage2/final-2026-10-26/live-api.json)：8000端口版本2.0.0、事务可用、旧登录与列表、三种usage范围、普通接收者无维护计数、管理员不获得他人答案统计、题库页面200。除登录会话外无业务写入。
- **BASE**：[M1基线](baseline.md)：原200项通过、工具专项修复后最终204项通过，以及实际备份恢复、源库和身份配置保护。
- **OLD**：原有回归节点，名称在最终全量结果中可直接检索；不将第一阶段的历史截图当作第二阶段页面验收。

UI步骤按JSON中的顺序编号：1旧账号与迁移题库；2创建数字稿；3正式v1；4个人标签；5问卷A选用发布；6发布后普通稿锁定；7问卷B复用v1；8实际填写20和40；9创建v2且旧卷不变；10跨卷均值30；11共享与接收者选用；12撤权保留快照；13快照独立派生；14恢复v3及下架；15为360px布局。

本轮补充证据 **Q** 为[309项最终回归](../evidence/stage2/recheck-2026-10-26-363f82/regression-final/test-results.json)，**UIR** 为[33场景浏览器总览](../evidence/stage2/recheck-2026-10-26-363f82/browser/final-summary.json)。Q1～Q10依次指`tests/integration/test_stage2_recheck.py`中的两跳派生、关联重排、发布第二题回滚、身份/来源注入、空答跳题0混合、跨卷同实例ID、历史N去重、5有效实例批量派生、关闭后冻结、三用户标签隔离测试。完整函数名与逐节点结果均可在Q中检索。UIR区分真实UI与API负例，并保留截图和等待问题记录。

## 固定样本真实操作的补充映射

10月26日至28日另有[HM2真实操作记录](manual-acceptance.md)。前段由用户实际操作，AI指导并核对；后段经用户明确要求由AI接手。下面把这些新样本映射到原文八项需求，保留原S2矩阵的细分覆盖判定，不把HM2编号直接转换成pytest数量。

| 原文能力 | 已完成的固定样本 | 方法与结果 |
| --- | --- | --- |
| R2-01 保存与复用 | HM2-19～29、65～67 | 独立学习时长正式v1被B选用；个人副本v1在E选用两次，各自实例独立 |
| R2-02 共享使用 | HM2-45～60 | 接收者授权前后可见，第三账号不可见；撤回服务调用成功后，页面源题拒绝，D快照及6保持；独立副本不向原作者公开 |
| R2-03 保护已发布问卷 | HM2-30～44、69～72 | B仍原v1/24，C仍原v2/12；副本生成v2/16后E仍两个v1/24，旧定义及答案指纹保持 |
| R2-04 历史与恢复 | HM2-41～44 | 从原v1恢复为v3，三版保留，B/C不跟随，新v3无回答 |
| R2-05 多版并存 | HM2-30～40、69～72 | 原v1与v2分别供B/C使用并分别统计；副本v1/v2并存，旧版答案不混入新版 |
| R2-06 使用情况 | HM2-52～56、72 | 作者仅B/C明细及其他历史N1；接收者仅D且无维护者N；撤回后历史N不减为0 |
| R2-07 个人题库整理 | HM2-61～64 | 服务设标签、重命名；页面旧标签0/新标签1；UI移除收藏后本人题目仍在。原生prompt完成交互未判本轮通过 |
| R2-08 跨卷统计 | HM2-27～29、39～40、53～54、65～72 | 年龄0/20/40为3/3/2均20；原学时作者4、接收者6按本人分离；E为2/1/1均8，副本v2为空 |

固定样本详证据：[E双实例](../evidence/stage2/manual-acceptance-2026-10-26/hm2-65-68-E-formal-double-instance-check-2026-10-28.json)、[旧页冲突与保护](../evidence/stage2/manual-acceptance-2026-10-26/hm2-69-72-two-tab-conflict-final-check-2026-10-28.json)、[原数据完整性](../evidence/stage2/manual-acceptance-2026-10-26/hm2-post-cas-original-data-integrity-2026-10-28.json)。后段撤回与部分标签写入是服务测试，其余对应页面观察按实际记录；更深事务回滚、公共管理和归档组合继续引用Q/UIR等已执行自动结果。

## 自动测试节点索引

下列简称均指实际可检索的完整节点，不是另造测试结果。

| 简称 | 节点 |
| --- | --- |
| C1 | `tests/integration/test_library_core.py::test_persistent_working_copy_versions_and_restore` |
| C2 | `tests/integration/test_library_core.py::test_sharing_does_not_leak_working_copy_or_inherit_root_permission` |
| C3 | `tests/integration/test_library_core.py::test_public_maintenance_and_independent_version_availability` |
| C4 | `tests/integration/test_library_core.py::test_parallel_cas_and_idempotent_replay` |
| C5 | `tests/integration/test_library_core.py::test_version_insert_failure_rolls_back_pointer_number_and_receipt` |
| C6 | `tests/integration/test_library_core.py::test_personal_tags_never_change_source_question_or_other_bookmarks` |
| C7 | `tests/integration/test_library_core.py::test_regular_unicode_and_public_working_copy_are_kept_separate` |
| C8 | `tests/integration/test_library_core.py::test_shared_question_without_formal_version_is_not_visible` |
| C9 | `tests/integration/test_library_core.py::test_root_usage_only_includes_visible_family_and_counts_manageable_members` |
| C10 | `tests/integration/test_library_core.py::test_root_usage_receiver_gets_own_details_but_no_maintenance_count` |
| B1 | `tests/integration/test_library_bindings.py::test_repeated_instances_publish_freeze_and_old_answers` |
| B2 | `tests/integration/test_library_bindings.py::test_existing_full_patch_cannot_forge_source_content` |
| B3 | `tests/integration/test_library_bindings.py::test_explicit_upgrade_and_removal_keep_historical_usage` |
| B4 | `tests/integration/test_library_bindings.py::test_revoked_source_can_be_batch_derived_from_owned_snapshots` |
| B5 | `tests/integration/test_library_bindings.py::test_existing_local_instance_can_be_saved_and_publish_registered` |
| R1 | `tests/integration/test_library_concurrency.py::test_revoke_archive_or_unavailable_commits_before_waiting_selection[revoke/archive/unavailable]`，三个实际参数节点 |
| R2 | `tests/integration/test_library_concurrency.py::test_committed_selection_survives_later_revoke_and_can_publish` |
| R3 | `tests/integration/test_library_concurrency.py::test_publication_commits_before_paused_ordinary_working_save` |
| M1 | `tests/integration/test_library_migration.py::test_dry_run_then_repeat_apply_preserves_answers_and_content` |
| M2 | `tests/integration/test_library_migration.py::test_missing_historical_definition_stops_before_any_migration_write` |
| M3 | `tests/integration/test_library_migration.py::test_current_and_historical_definitions_get_distinct_exact_mappings` |
| M4 | `tests/integration/test_library_migration.py::test_interrupted_migration_resumes_without_duplicate_sources` |
| M5 | `tests/integration/test_library_migration.py::test_same_content_from_different_question_cannot_fake_a_mapping` |
| M6 | `tests/integration/test_library_migration.py::test_missing_legacy_reference_rebinds_original_v1_after_later_revision` |
| S1 | `tests/integration/test_cross_library_statistics.py::test_numeric_combination_zero_duplicates_and_within_survey_anonymous_accounts` |
| S2 | `tests/integration/test_cross_library_statistics.py::test_foreign_answers_and_all_downstream_statistics_respect_single_scope` |
| S3 | `tests/integration/test_cross_library_statistics.py::test_versions_are_separate_and_archived_source_does_not_hide_own_answers` |
| S4 | `tests/integration/test_cross_library_statistics.py::test_non_numeric_summaries_and_no_cross_response_detail[single/multiple/text]`，三个实际参数节点 |
| S5 | `tests/integration/test_cross_library_statistics.py::test_unmapped_answered_definition_errors_but_unanswered_draft_does_not` |
| S6 | `tests/integration/test_cross_library_statistics.py::test_extreme_decimal_average_keeps_cancellation_residual` |
| S7 | `tests/integration/test_cross_library_statistics.py::test_new_response_during_aggregates_enters_next_statistics_request_only` |
| S8 | `tests/integration/test_cross_library_statistics.py::test_cross_statistics_filter_resource_limit_is_explicit` |
| S9 | `tests/integration/test_cross_library_statistics.py::test_missing_historical_account_key_is_unknown_not_an_invented_person_count` |
| S10 | `tests/integration/test_cross_library_statistics.py::test_revoked_source_access_does_not_remove_statistics_of_own_held_snapshot` |
| E1 | `tests/integration/test_stage2_acceptance_edges.py::test_upgrade_removing_rule_option_is_atomic_and_preserves_usage` |
| E2 | `tests/integration/test_stage2_acceptance_edges.py::test_mixed_v1_v3_usage_and_highest_version_down_do_not_hide_v1_update` |
| E3 | `tests/integration/test_stage2_acceptance_edges.py::test_migrated_old_answer_and_new_reuse_join_the_same_exact_version` |
| E4 | `tests/integration/test_stage2_acceptance_edges.py::test_unanswered_version_has_zero_counts_null_range_and_empty_groups` |
| E5 | `tests/integration/test_stage2_acceptance_edges.py::test_numeric_frequency_pages_are_numeric_sorted_and_do_not_change_totals` |
| E6 | `tests/integration/test_stage2_acceptance_edges.py::test_exception_after_version_and_state_insert_rolls_back_every_write` |
| E7 | `tests/integration/test_stage2_acceptance_edges.py::test_standalone_rejects_transaction_without_calling_the_write_callback` |
| E8 | `tests/integration/test_stage2_acceptance_edges.py::test_unchanged_ordinary_working_save_keeps_revision_and_content_version` |
| E9 | `tests/integration/test_stage2_acceptance_edges.py::test_search_is_literal_and_invalid_or_missing_ids_are_structured` |
| E10 | `tests/integration/test_stage2_acceptance_edges.py::test_five_item_batch_with_last_foreign_instance_rolls_back_earlier_copies` |

参数化简称中的斜线是简写，JSON内实际节点分别为`[single]`等，不能将简写原样当成pytest nodeid执行。

## 76项对照

| 场景 | 当前判定 | 可核验依据及准确范围 |
| --- | --- | --- |
| S2-01 四题型编辑稿及正式首版 | 已验证 | C1/S4为四题型接口路径；UI2、3实际数字表单，FORMS实际单选/多选/文本编辑稿及v1，选择ID和上下界均核验。 |
| S2-02 同名独立题不合并 | 部分验证 | S3独立同内容题的答案未混入目标统计；独立root不同未作单独断言。 |
| S2-03 两次生成版本 | 已验证 | C1明确v1/v2及历史内容保留，UI9新增v2后旧卷仍为v1。 |
| S2-04 无变化普通保存 | 已验证 | E8同内容普通保存后revision、版本号、最新指针及题目BSON不变，版本仍仅一份。 |
| S2-05 历史恢复 | 已验证 | C1及UI14，从v1内容生成v3，直接来源及中间历史保留。 |
| S2-06 多次派生来源链 | 已验证 | Q1实际二次派生，核对root、逐跳直接来源、各级所有权及不继承反向权限。 |
| S2-07 同版本两问卷 | 已验证 | UI5、7实际选入两份问卷；S1、S4真实复用后统计。 |
| S2-08 同卷双实例 | 已验证 | B1同卷两个实例分别回答10/30；S1跨卷汇总中双实例计回答、单response计答卷。 |
| S2-09 有v2后仍明确选v1 | 已验证 | E2先生成v1/v2/v3，再向草稿明确选入v1和v3，引用及内容保持请求版本。 |
| S2-10 伪造来源/内容 | 已验证 | B2拒绝自造questionRefs与改快照；Q4新增选题夹带内容/root返回422，业务指纹不变。 |
| S2-11 已发布旧内容冻结 | 已验证 | B1逐字节比较旧问卷、旧答案，单卷均值仍10/30；UI9检查v2不改变旧问卷标题和引用。 |
| S2-12 显式升级保留实例 | 已验证 | B3版本范围120变80且实例ID不变。 |
| S2-13 升级使选项跳转无效 | 已验证 | E1删除被eq条件引用的选项b，升级422；问卷、usage及题目guard的BSON回滚，回执不存在。 |
| S2-14 原整卷PATCH旁路 | 已验证 | B2真实PATCH返回VERSION_REQUIRED，并核对原问卷BSON不变。 |
| S2-15 单题/删除/排序一致 | 已验证 | B2单题PATCH、B3删除与B1发布；Q2补已关联题排序PUT及之后真实提交，来源与答案按实例保持。 |
| S2-16 本地题登记和发布 | 已验证 | B5本地题登记发布；Q3在发布登记第二题时注入失败，整卷、题目、版本及使用记录均回滚。 |
| S2-17 共享三用户隔离 | 已验证 | C2甲乙丙访问隔离及接收者仅正式内容；UI11实际共享、接收者选用。 |
| S2-18 非所有者修改/伪造owner | 已验证 | C2非所有者403；Q4伪造owner/root字段422且完整业务指纹不变。 |
| S2-19 撤权来源失效 | 已验证 | C2、B4及UI12源访问拒绝；原快照保留。浏览器没有单独枚举所有搜索缓存路径。 |
| S2-20 已有快照与派生保留 | 已验证 | C2派生正文在撤权后仍可读；B4旧卷BSON不变；UI12、13实际从已持有快照创建副本。 |
| S2-21 归档前后使用 | 已验证 | S3原统计保留，R1[archive]阻止新选用；UIR公共题归档后旧发布卷快照不变并显示来源失效提示。 |
| S2-22 管理员产生及防提权 | 部分验证 | C3普通用户403，Q4注册夹带role为422且无写入；DEMO受控管理员audit与LIVE答案隔离保留。本轮未将fixture赋role说成新增CLI边界测试。 |
| S2-23 公共维护 | 已验证 | C3/C7维护及编辑稿隔离；UIR补公共管理员v1/v2、普通用户只读与403、发布卷不升级、归档保留快照完整角色流程。 |
| S2-24 收藏/标签整理不改源 | 已验证 | C6真实标签重命名、移除收藏；源内容和其他用户标签保持，历史版本保留；UI4标签保存。 |
| S2-25 不自动跟随新版 | 已验证 | B3升级前仍120，UI9旧卷v1不变；更新提示仅辅助，未自动替换。 |
| S2-26 搜索范围和正则边界 | 已验证 | E9输入`.*`仅命中字面标题，非全库正则展开；C2/C7私密稿不可搜索；非法ID422、不存在ID404结构明确。超长搜索的具体边界未另造例。 |
| S2-27 版本/本题/同源使用范围 | 已验证 | C9/C10分别核对root可见成员、本人的明细、仅可维护成员他人N、普通接收者无N；USCOPE实际DOM三范围切换成功。 |
| S2-28 并发CAS与保留输入 | 已验证 | C4并发CAS单成功；UIR保存竞态包含真实第二窗口先保存造成409，失败页面保留输入并解锁，三条成功保存路径阻止后输入丢失。 |
| S2-29 管理指针更新后失败 | 已验证 | C5在版本写入入口注入失败，指针、编号、revision、版本及回执均回滚。 |
| S2-30 版本已插入后失败 | 已验证 | E6先真实插入版本及version_state并在事务内读到，再抛错；事务外版本/状态/回执均不存在，管理BSON复原。 |
| S2-31 成功重试幂等 | 部分验证 | C4版本重放、B3选用重放、B4批量派生重放均同结果；相同键同时竞争的独立线程变体未另证。 |
| S2-32 同键异内容 | 已验证 | C4改变答案内容沿用key得到409。 |
| S2-33 选用先于撤权提交 | 已验证 | R2已选快照保留且撤权后仍能发布。 |
| S2-34 撤权先提交 | 已验证 | R1[revoke]用Event暂停真实事务读取，再撤权，确认事务重试后拒绝且无实例、usage和回执残留。 |
| S2-35 归档和选用顺序 | 已验证 | R1[archive]验证归档先提交；S3先选用再归档后原回答仍统计。 |
| S2-36 standalone拒绝事务写 | 已验证 | E7只在27017随机独立测试库尝试transaction，503/TRANSACTIONS_REQUIRED，写回调未调用，marker原文档不变并清理。 |
| S2-37 dry-run只读 | 已验证 | M1比较完整manifest，dry-run前后无变化；实际MIG扫描存量。 |
| S2-38 当前与历史定义迁移 | 已验证 | M1/M3与MIG，现有实例、定义版本和答案不变；同实例字符串跨历史版本映射不同。 |
| S2-39 旧提交迁移后重放 | 已验证 | M1已保存迁移前真实submissionKey、匿名选择和答案，迁移后重POST，200/replayed=true且回执ID不变；同一最终P运行实际通过。 |
| S2-40 中断续跑与重复执行 | 已验证 | M4中断后续跑不重复，M1二次apply无变更；MIG正式repeat的wouldBind和bound均为0。 |
| S2-41 缺定义/错误映射 | 已验证 | M2在任何写入前拒绝缺历史定义；M5同内容却冒用其他题目版本的映射被拒；M6缺引用只重绑原始v1，不绑到后来的新版；S5跨卷缺映射明确MIGRATION_INCOMPLETE。 |
| S2-42 未迁移数据兼容 | 部分验证 | S5已答定义缺映射拒绝跨卷、未答草稿不阻断；原功能兼容路径由旧回归与迁移前后统计核对，未覆盖每个混合状态UI组合。 |
| S2-43 原答案、用户和密钥 | 已验证 | MIG/BASE逐条BSON核对9用户与33答卷、旧实例内容及8份统计；配置私密保护不公开密钥。 |
| S2-44 迁移旧题复用新卷 | 已验证 | E3旧题先答10，迁移后将其精确版本选入新卷再答30，合并2次/2卷、均值20，旧答卷BSON不变。 |
| S2-45 四题型手算跨卷汇总 | 已验证 | S1、S4三参数及UI10，选择次数、不同文本数、0值和数字均值按真实答案核对。 |
| S2-46 排除他人回答 | 已验证 | S2把他人999作为干扰值，所有计数、分布、均值及来源被排除；替换scope后只剩一个合法问卷。 |
| S2-47 版本/派生/同名不误并 | 已验证 | S3同时有v2、独立同名题及同源派生的80/999/888，v1均值仍10。 |
| S2-48 双实例/重复/跨卷匿名 | 已验证 | S1回答4次、答卷3份、问卷2份，两个逐卷账号数均1；不返回跨卷respondentCount。 |
| S2-49 空答、跳过与0 | 已验证 | S1含0；Q5新增两份问卷，混合空答、分支跳过和0，核对答案/答卷/问卷数及精确均值。 |
| S2-50 极端数字及不同样本量 | 已验证 | S6保留大数抵消残差；DEMO的A卷2份0/20、B卷1份40，合并均值20，而非两个卷均值的平均25。 |
| S2-51 统计中插入答案 | 已验证 | S7真实插入新答卷，第一次仅原成员均值10，刷新后2份均值20。 |
| S2-52 数值频数跨页完整性 | 已验证 | E5把页大小设2，0/2/10的频数跨三页完整、按数值排序且总数及均值各页不变；S1另核对双实例回答次数。未声称大规模压力性能。 |
| S2-53 资源上限 | 已验证 | S8把筛选BSON上限降到1，实际响应503/STATISTICS_TOO_LARGE；非实测百万级性能。 |
| S2-54 撤权/归档后自己的统计 | 已验证 | S3归档、S10撤权后仍返回自己持有快照答案42；原作者不因此获得回答。 |
| S2-55 原200项回归 | 已验证 | BASE原200项通过；最终P逐节点比对原200项均通过，新环境CLEAN全260项通过。 |
| S2-56 原特殊ID和数字边界 | 已验证 | OLD `test_encoded_question_ids_keep_identity_through_edit_delete_publish_fill_and_single_statistics[group/item/题目/年龄/literal%2Fitem]`及原数字参数化节点；C7补普通Unicode。 |
| S2-57 页面/360px/异常交互 | 部分验证 | UIR已复查360px和真实revision冲突保留输入；2000字长标题的页面组合仍未另行造例。 |
| S2-58 DTO与日志不泄漏 | 部分验证 | C2/C7正式内容隔离、S4跨卷无raw内容、LIVE管理员无他人答案；填写DTO采用白名单为静态审查，尚无本行独立的所有敏感字段响应断言。 |
| S2-59 新全集合备份与重启 | 已验证 | BACKUP实际恢复全部12业务集合、10份定义统计及原登录/列表，恢复后启动通过且源数据不变；CLEAN另有新环境启动。未将此解释为整机断电演练。 |
| S2-60 全新环境安装复现 | 已验证 | CLEAN新建Python3.12.6环境、锁定依赖检查、初始化和幂等种子、应用/登录/HTML/静态资源/统计核验，以及260项全部通过；不引用第一阶段197项记录顶替。 |
| S2-61 不同问卷同实例字符串 | 已验证 | M3同卷历史版本；Q6进一步强制不同问卷同实例字符串、分别绑定同题不同版本，答案不会跨配。 |
| S2-62 无回答版本 | 已验证 | E4确证回答/答卷/问卷/不同值计数全0，均值/上下界null，options/distribution/bySurvey为空，且无虚构跨卷人数。 |
| S2-63 统一scope入口 | 已验证 | S2 monkeypatch统一入口限制到一个问卷，计数、均值及分布同步收缩。 |
| S2-64 持久稿不推进版本 | 已验证 | C1在正式版前后分别保存编辑稿，编号仍0/1，历史v1内容不被后续稿覆盖。 |
| S2-65 发布与普通保存竞争 | 部分验证 | R3暂停普通保存再提交发布，重试后409且原内容不变；反向交错未单独用屏障执行。 |
| S2-66 root不授予访问权 | 已验证 | C2甲无法访问乙派生题；C9/C10完整root使用查询只包括可见成员，并限制维护者计数，不读取隐藏派生题。 |
| S2-67 维护者N去重与历史 | 已验证 | B4他人双实例N=1且接收者无维护计数；Q7实际经历双用、升级、移除、再选用，历史他人问卷N仍1。 |
| S2-68 下架与选用竞争 | 已验证 | R1[unavailable]保证过期读取重试后拒绝且无残留；C3正文不变，UI14实际下架状态。 |
| S2-69 最新下架及旧实例提示 | 已验证 | E2同时持有v1/v3，下架v3后latest实际仍3、latestSelectable为2、收藏v1仍hasUpdate，问卷BSON不变；UI15实际旧v1提示可选v2。 |
| S2-70 五实例撤权后派生 | 部分验证 | B4撤权两实例去重；Q8恰好5有效实例成功、去重、幂等，原卷不暗中替换；UIR真实批量派生再明确替换。恰好5实例并同时撤权的联合变体未单独执行。 |
| S2-71 批量失败与幂等 | 已验证 | E10前4项为本人、最后1项他人，404后题目/版本/状态/收藏/回执全部BSON复原；B4同键回放及6项422覆盖重试和上限。 |
| S2-72 编辑稿不对共享者公开 | 已验证 | C2、C8、C7包含共享/公共编辑稿、无首版稿及搜索过滤。 |
| S2-73 匿名本卷去重 | 已验证 | S1匿名/实名重复及双实例仍每卷1账号；S9缺稳定键返回null，不发明人数。 |
| S2-74 跨卷无明细/单卷保留 | 已验证 | S4文本内容不出现在跨卷结果；OLD `test_four_response_statistics_match_hand_calculation_and_pages_are_complete`保留单卷所有文本及分页。 |
| S2-75 个人标签隔离 | 已验证 | C6基础隔离；Q10甲乙丙三用户同时整理各自标签，互不更改，也不改源内容。 |
| S2-76 发布锁定不逆转 | 已验证 | B1/UI6原发布冻结；Q9补关闭原发布卷并移除其他草稿引用后，普通编辑仍被拒绝。 |

## 静态审查与运行证据的界线

已经看到的结构包括：版本正文与可选状态分离、管理/填写DTO分开、旧整卷写入检查来源一致性、集中权限与scope入口、事务共同guard、持久稿发布锁定、批量派生原子写入。上述代码结构支持正确实现，但本表没有因“用了事务”便自动给所有失败点和并发交错判通过。

同样，恢复库原BSON与统计一致不能证明新字段授权全部正确；无横向溢出不能证明全部页面交互都已人工验收；测试数量不能换算成76个场景全部通过。最终交付应保留本表中的具体覆盖边界。

八项原文需求均有核心运行证据：R2-01对应C1/B1和UI2～7，R2-02对应C2/B4及UI11～13，R2-03对应B1/UI9，R2-04对应C1/UI14，R2-05对应B3/E2，R2-06对应C9/C10/USCOPE，R2-07对应C6/UI4，R2-08对应S1～S10、E3～E5和UI10。两跳派生、关联题排序、浏览器冲突输入恢复、5有效实例成功及三用户标签等已由本轮Q/UIR补齐；其余8行保留具体细分边界，例如反向发布交错、2000字标题页面与5实例同时撤权，不扩写成不存在的运行证据。当前为68行核心行为已验证、8行部分验证；这不是测试节点数量。
