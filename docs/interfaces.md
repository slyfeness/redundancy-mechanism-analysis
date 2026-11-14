# 接口

输入和输出采用 JSON 对象。原始字符位置为 Unicode 左闭右开区间，策略坐标是按响应顺序拼接的原始生成 Token，区间亦为左闭右开。

| 函数签名 | 输入和输出 |
|---|---|
| `parse_stages(trajectory, format_config=None, legacy_blocks=None)` | 原生捕获和可选分词器／旧分块。返回 stages、tool_events、position_map、异常、策略位置和完整状态。 |
| `init_task_ledger(question, judge)` | 题面字符串。返回固定约束和空账本。约束只接受精确题面引文。 |
| `resolve_action_target(task, before, stage, judge, *, threshold=0.8)` | 基于本次工具参数、调用前输出及历史状态推断动作目标。置信度不足返回 unknown。 |
| `update_evidence_ledger(task, before, stage, event, judge)` | 对本次返回的候选事实更新校验字符引用。返回独立账本和增量，提取失败保留原因。 |
| `judge_stage(task, before, after, stage, event, target, delta, judge, *, threshold=0.8, previous_targets=None)` | 返回 R1、R2b、R2a、保护项、可判时点、位置和计价候选。 |
| `summarize_trajectory(trajectory, task, ledger, stages, judgments, *, submitted_candidate=None)` | 返回覆盖、成本、约束支持比例、局部事件和独立结果。 |
| `audit_judge(judgments, human_annotations=(), legacy_links=(), *, config=None, planned_reviews=None)` | 按标签报告自动覆盖、独立人工指标、旧关联和批准清单。 |
| `build_grpo_inputs(annotations, config=None, approved_labels=None)` | 返回题内留一优势、同伴门控、扣分明细、掩码、逐 Token 优势、排除记录和断言。 |

`tests/unit/test_semantic_pipeline.py` 用首次取证和相同查询的重复返回演示前六个接口。`tests/unit/test_audit_judge.py` 与 `tests/unit/test_build_grpo_inputs.py` 给出可直接运行的人工记录结构和手算例。
