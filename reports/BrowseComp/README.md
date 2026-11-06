# 904组Stage功能—机制分析

先读FINAL_904_STAGE_SYNTHESIS.md。它将A/B原工作功能、实际作用链、结果与成本分开解释；没有用结果变化频率代替机制。

- DECISIONS：每个原Stage及四续跑的模型亲写分析，20例为已封存试点原样复用。
- STAGE_FUNCTION_MAPPING.csv与FUNCTION_FAMILY_MEMBERS.csv：具体原工作及明确共同功能家族，复合功能可多归。
- STAGE_MECHANISM_MAPPING.csv：全部局部链四态、位置、证据、候选归属和定义兼容结论；开放链完整保留。
- MECHANISM_SUPPORT_COUNTEREXAMPLES.csv、MECHANISM_AB_DISTINCT_SQL.csv：分A/B、条件、四态的去重统计。OBSERVED不等原U必含该机制或因果必要。
- COST_AND_RESULT_3616.csv：真实切点对齐的原新结果和成本。G一次、Prompt另列、CHAR只区间，不相加独立干预节省。
- PRECISE_EVIDENCE_INDEX.jsonl、FACTUAL_RECORDS、SOURCE_TRAJECTORY_INDEX.csv：关键原文、六类材料索引和完整本地源位置/SHA。
- BATCH_REVIEW_RECORDS、AUDIT_INPUTS：逐批比较、试点复用、定义兼容与机械检查依据。
- REPRODUCE：确定性统计和校验程序，不含自动语义分类器。

引用里的original/new1…4指源包内两侧；JSON Pointer先选该侧再定位。完整原始bundle未复制进ZIP，仍在SOURCE_TRAJECTORY_INDEX列出的Windows本地位置；关键引文实际在ZIP内，不依赖服务器。完整源文件只读且永久保留，研究者需全文时按SHA索引打开。

A/B是筛选子集，不代表全400条或全删除实验的自然比例。一个Stage多链/多功能，数字不可跨行直接相加；四续跑和同题多个Stage不能当不同题。所有教师条件ORACLE_ANCHORED，TERMINAL无G独立分组；不将本次续跑解释成纯无引导删除因果效应。

Codex审阅并非独立人工验收。研究者待裁定问题与保留反例见UNRESOLVED_CASES.csv及各逐案attribution_limit。没有新运行、GPU、Stage调整或旧评价覆盖。

NOT_OBSERVED_LOCAL只表示本条已检查局部窗口没有该链，不是通用机制被证伪；未覆盖的机制不自动填ABSENT。候选定义中的历史支持数保持原文，本轮数量以全量CSV/SQL为准。

复算：在本目录执行 `python REPRODUCE/recompute_statistics.py`。它不需要GPU或第三方库，不改语义记录；输出用于和OFFLINE_RECOUNT_RECEIPT对账。REPRODUCE其余脚本保存当时完整构建/检查实现，若需重建源审计须使用AUDIT_INPUTS中的原布局与本地SOURCE_TRAJECTORY_INDEX原文件。
