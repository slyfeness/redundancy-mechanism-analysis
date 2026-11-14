# 长程智能体冗余机制分析

本项目研究长程智能体的冗余阶段，包含 Stage 机制分析、证据账本 Judge 和 Ledger-GRPO 事件计价框架。

## 项目代码与结果

| 内容 | 从这里打开 |
| --- | --- |
| **完整项目代码** | [完整交付分支](https://github.com/slyfeness/redundancy-mechanism-analysis/tree/release/ledger-grpo-framework) · [Ledger-GRPO 运行说明](https://github.com/slyfeness/redundancy-mechanism-analysis/blob/release/ledger-grpo-framework/ledger-grpo/README.md) · [一期 Judge 源码](https://github.com/slyfeness/redundancy-mechanism-analysis/tree/release/ledger-grpo-framework/src/redundancy_judge) |
| **Ledger-GRPO 试跑结果** | [试跑报告](https://github.com/slyfeness/redundancy-mechanism-analysis/blob/release/ledger-grpo-framework/artifacts/ledger_grpo_framework/README.md) · [单步试跑 182516](https://github.com/slyfeness/redundancy-mechanism-analysis/blob/release/ledger-grpo-framework/artifacts/ledger_grpo_framework/pilot-182516.json) · [历史计价回放 182501](https://github.com/slyfeness/redundancy-mechanism-analysis/blob/release/ledger-grpo-framework/artifacts/ledger_grpo_framework/event-price-audit-182501.json) |
| **一期证据账本诊断** | [根因诊断报告](https://github.com/slyfeness/redundancy-mechanism-analysis/blob/diagnosis/phase1-ledger-root-cause/artifacts/ledger_diagnosis_phase1_zhurong-184780/report.md) · [逐条索引与复现记录](https://github.com/slyfeness/redundancy-mechanism-analysis/tree/diagnosis/phase1-ledger-root-cause/artifacts/ledger_diagnosis_phase1_zhurong-184780) · [草稿 PR #2](https://github.com/slyfeness/redundancy-mechanism-analysis/pull/2) |

试跑使用一个训练种子和每臂一次更新，当前结果用于核验流程。诊断基于 400 条冻结轨迹和旧缓存，涵盖引文校验、取证充分度 `g` 和 R1 判别漏斗。

## BrowseComp-Plus、SAGE 与 SciCode 的 Stage 分析归档

本仓库保存三套已完成的 Stage 共性与作用机制分析人工审核包。根目录 ZIP 是原始封存归档，`reports/` 提供可直接浏览的 Markdown、CSV、JSON 与 JSONL 资料。

| 数据集 | 原始归档 | 在线阅读入口 | ZIP SHA-256 |
| --- | --- | --- | --- |
| BrowseComp-Plus | [ZIP](BrowseCompPlus_904Stage_Final_Function_Mechanism_Atlas.zip) | [reports/BrowseComp](reports/BrowseComp/INDEX.md) | `febee974be03cdae836b47cd255131c59e02e83d069fae62da9474789e2ee16c` |
| SAGE | [ZIP](SAGE100_V1.3.2_Stage删除四次续跑与AB340机制分析.zip) | [reports/SAGE](reports/SAGE/INDEX.md) | `3e0dce66794793b6b8fdd3df46412fef9acf5bd8173654d4e3fc635cb7de1737` |
| SciCode | [ZIP](SciCode_AB249_Stage共性与作用机制_完整分析.zip) | [reports/SciCode](reports/SciCode/INDEX.md) | `b4ae8136817df8fc358b49bfc5825d89d9558b77430c224e4b045fdc552a5b61` |

各数据集 `INDEX.md` 标出功能统计、机制支持数、支持案例、反例、逐 Stage 审阅、成本统计及源文件索引。SAGE 的重复原始轨迹仅保留在 ZIP 中，详情见其 [未展开清单](reports/SAGE/SKIPPED_FROM_EXPANSION.md)。
